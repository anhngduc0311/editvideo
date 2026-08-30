"""
pipeline.py - Master Pipeline Orchestrator for Automated Douyin Video Editing
"""

from __future__ import annotations

import logging
from pathlib import Path
import time
from typing import Callable, Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from tqdm import tqdm

from config import BlurRegion, CookieConfig, PipelineConfig
from downloader import DouyinDownloader
from preprocessor import VideoPreprocessor
from transcriber import WhisperTranscriber
from translator import create_translator
from subtitle_burner import SubtitleBurner
from vocal_separator import VocalSeparator
from tts_synchronizer import VietnameseTTSSynchronizer
from compositor import VideoCompositor

logger = logging.getLogger(__name__)
console = Console()


class DouyinAutoPipeline:
    """
    Quy trình tự động hóa hoàn chỉnh (Pipeline Orchestrator):
    Thực hiện lần lượt 8 bước từ link Douyin đến video thành phẩm MP4.
    Hỗ trợ hook callback cho GUI / Web interface.
    """

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.config.setup_directories()

        # Khởi tạo các module chuyên biệt (OOP Architecture)
        self.downloader = DouyinDownloader(
            download_dir=self.config.download_dir,
            cookie_config=self.config.cookie_config
        )
        self.preprocessor = VideoPreprocessor(config=self.config)
        self.transcriber = WhisperTranscriber(config=self.config)
        self.translator = create_translator(config=self.config)
        self.burner = SubtitleBurner(config=self.config)
        self.separator = VocalSeparator(config=self.config)
        self.tts_syncer = VietnameseTTSSynchronizer(config=self.config)
        self.compositor = VideoCompositor(config=self.config)

    def print_pipeline_banner(self, input_url: str):
        """Hiển thị thông tin tổng quan quy trình làm việc trên Console"""
        table = Table(show_header=True, header_style="bold magenta", border_style="cyan")
        table.add_column("Thuộc tính", style="cyan", width=25)
        table.add_column("Cấu hình thiết lập", style="green")

        table.add_row("Douyin Input", input_url[:60] + ("..." if len(input_url) > 60 else ""))
        table.add_row("Tốc độ video (Speed)", f"{self.config.speed_factor}x (Chậm 30%)")
        table.add_row("Vùng mờ Sub gốc (Blur)", f"Y: {self.config.blur_region.y_ratio*100:.0f}% | Height: {self.config.blur_region.height_ratio*100:.0f}%")
        table.add_row("Whisper Model", f"{self.config.whisper_model_size} (Lang: {self.config.whisper_language})")
        ai_provider_name = "DeepSeek AI" if getattr(self.config, "llm_provider", "deepseek") == "deepseek" else "Google Gemini"
        ai_model_name = getattr(self.config, "deepseek_model_name", "deepseek-v4-flash") if getattr(self.config, "llm_provider", "deepseek") == "deepseek" else self.config.gemini_model_name
        table.add_row("AI Dịch thuật", f"{ai_provider_name} ({ai_model_name})")
        table.add_row("Giọng đọc tiếng Việt (TTS)", self.config.tts_config.voice)
        table.add_row("Font chữ Hardsub", f"{self.config.subtitle_style.font_name} (Size: {self.config.subtitle_style.font_size}px)")
        table.add_row("Tách giọng gốc / BGM", "Bật (Demucs/FFmpeg DSP)" if self.config.keep_bgm else "Tắt (Mute)")

        console.print(Panel(table, title="[bold yellow]🚀 DOUYIN AUTO VIDEO EDITING PIPELINE (OOP)[/bold yellow]", expand=False))

    def run(
        self,
        douyin_url_or_text: str,
        custom_name: Optional[str] = None,
        progress_callback: Optional[Callable[[int, int, str, str], None]] = None,
        interactive_roi_callback: Optional[Callable[[Path, BlurRegion], Optional[BlurRegion]]] = None
    ) -> Path:
        """
        Kích hoạt toàn bộ quy trình 8 bước tự động.
        :param progress_callback: Hàm nhận (current_step, total_steps, step_name, log_message)
        :param interactive_roi_callback: Hàm mở UI cho người dùng khoanh vùng mờ trên video vừa tải
        """
        start_time = time.time()
        self.print_pipeline_banner(douyin_url_or_text)

        total_steps = 8
        overall_pbar = tqdm(total=total_steps, desc="[Tiến độ tổng thể]", bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} bước [{elapsed}<{remaining}]")

        def notify(step: int, title: str, msg: str):
            logger.info(f"[{step}/{total_steps}] {title} - {msg}")
            if progress_callback:
                progress_callback(step, total_steps, title, msg)

        try:
            # ==========================================
            # BƯỚC 1: TẢI VIDEO TỪ DOUYIN
            # ==========================================
            notify(1, "Bước 1: Tải video Douyin", "Đang phân tích link và tải video chất lượng cao...")
            console.print("\n[bold cyan]▶ BƯỚC 1: Đang tải video từ Douyin (Multi-Engine Auto-Fallback)...[/bold cyan]")
            raw_video = self.downloader.download(
                douyin_url_or_text,
                custom_filename=custom_name,
                progress_callback=lambda p, msg: notify(1, "Bước 1: Tải video Douyin", msg)
            )
            video_id = raw_video.stem
            overall_pbar.update(1)

            # Người dùng tự chọn vùng làm mờ phụ đề trên video vừa tải (nếu bật)
            if interactive_roi_callback:
                notify(2, "Bước 2: Chọn vùng làm mờ", "Vui lòng khoanh vùng phụ đề trên cửa sổ xem trước...")
                chosen_region = interactive_roi_callback(raw_video, self.config.blur_region)
                if chosen_region:
                    self.config.blur_region = chosen_region
                    self.preprocessor.blur_config = chosen_region

            # Thư mục tạm riêng cho từng video
            session_work_dir = self.config.work_dir / video_id
            session_work_dir.mkdir(parents=True, exist_ok=True)

            # Khai báo đường dẫn các tài nguyên trung gian
            slowed_blurred_video = session_work_dir / f"{video_id}_slowed_blurred.mp4"
            extracted_audio = session_work_dir / f"{video_id}_slowed_audio.wav"
            original_srt = session_work_dir / "original_subtitles.srt"
            raw_vietnamese_srt = session_work_dir / "vietnamese_raw_subtitles.srt"
            synced_vietnamese_srt = session_work_dir / "vietnamese_synced_subtitles.srt"
            hardsub_video = session_work_dir / f"{video_id}_hardsub.mp4"
            bgm_audio = session_work_dir / f"{video_id}_bgm_track.wav"
            tts_synced_audio = session_work_dir / f"{video_id}_tts_synced.wav"
            final_output_video = self.config.output_dir / f"output_{video_id}_vi.mp4"

            # ==========================================
            # BƯỚC 2: TRÍCH XUẤT AUDIO SIÊU TỐC & WHISPER AI (KHÔNG RENDER VIDEO)
            # ==========================================
            notify(2, "Bước 2: Trích xuất Audio Siêu Tốc", f"Đang trích xuất audio và giảm tốc độ {self.config.speed_factor}x (không cần render video)...")
            console.print("[bold cyan]▶ BƯỚC 2: Trích xuất audio 0.70x siêu tốc trong 1-3 giây (Bỏ qua render video)...[/bold cyan]")
            
            raw_video_info = self.preprocessor.get_video_info(raw_video)
            video_width = raw_video_info["width"]
            video_height = raw_video_info["height"]
            total_duration = self.preprocessor.extract_audio_for_stt(
                input_video=raw_video,
                output_audio=extracted_audio
            )

            notify(2, "Bước 2: Whisper Speech-to-Text", "Đang nhận diện giọng nói tiếng Trung sang file phụ đề SRT...")
            console.print("[bold cyan]▶ BƯỚC 2 (tiếp): Whisper AI nhận diện giọng nói tiếng Trung -> SRT...[/bold cyan]")
            self.transcriber.transcribe(
                audio_path=extracted_audio,
                output_srt=original_srt
            )
            overall_pbar.update(1)

            # ==========================================
            # BƯỚC 3: DỊCH THUẬT VỚI AI (DEEPSEEK / GEMINI)
            # ==========================================
            prov_name = "DeepSeek" if getattr(self.config, "llm_provider", "deepseek") == "deepseek" else "Gemini"
            notify(3, f"Bước 3: Dịch thuật {prov_name}", "Đang dịch phụ đề Trung -> Việt giữ nguyên timeline...")
            console.print(f"[bold cyan]▶ BƯỚC 3: Dịch phụ đề sang Tiếng Việt bằng {prov_name} API ({self.translator.model_name})...[/bold cyan]")
            raw_vn_subtitles = self.translator.translate_srt(
                input_srt_path=original_srt,
                output_srt_path=raw_vietnamese_srt
            )
            overall_pbar.update(1)

            # ==========================================
            # BƯỚC 4: XÓA GIỌNG NÓI GỐC & TÁCH BGM
            # ==========================================
            notify(4, "Bước 4: Tách Vocal & BGM", "Đang tách giọng nói gốc và bảo tồn nhạc nền...")
            console.print("[bold cyan]▶ BƯỚC 4: Xóa giọng nói gốc và tách nhạc nền (BGM)...[/bold cyan]")
            bgm_track_path = self.separator.process(
                audio_path=extracted_audio,
                output_bgm_path=bgm_audio
            )
            overall_pbar.update(1)

            # ==========================================
            # BƯỚC 5: CAPCUT TTS & ĐỒNG BỘ PHỤ ĐỀ TỪNG CÂU KHỚP GIỌNG NÓI
            # ==========================================
            notify(5, "Bước 5: CapCut TTS & Đồng bộ phụ đề", f"Đang đọc giọng {self.config.tts_config.preset_name or self.config.tts_config.voice} và căn khớp từng câu...")
            console.print(f"[bold cyan]▶ BƯỚC 5: Đọc phụ đề tiếng Việt bằng CapCut TTS ({self.config.tts_config.preset_name}) & đồng bộ timeline từng câu ngắn...[/bold cyan]")
            tts_synced_audio, synced_vn_subtitles = self.tts_syncer.generate_and_sync(
                subtitles=raw_vn_subtitles,
                total_duration_seconds=total_duration,
                output_audio_path=tts_synced_audio,
                output_srt_path=synced_vietnamese_srt
            )
            overall_pbar.update(1)

            # ==========================================
            # BƯỚC 6, 7 & 8: SINGLE-PASS MASTER RENDER (GỘP TẤT CẢ TRONG 1 LẦN RENDER DUY NHẤT)
            # ==========================================
            sub_count = len(synced_vn_subtitles) if synced_vn_subtitles else len(raw_vn_subtitles)
            notify(6, "Bước Cuối: Master Render 1-Pass", f"Đang làm chậm 0.70x, làm mờ sub cũ, đóng {sub_count} câu phụ đề & mix nhạc...")
            console.print(f"[bold cyan]▶ BƯỚC CUỐI: Single-Pass Master Render (0.70x + Blur + Hardsub {sub_count} câu + Lồng tiếng CapCut & BGM)...[/bold cyan]")
            final_video = self.compositor.render_single_pass_master(
                raw_video_path=raw_video,
                srt_file=synced_vietnamese_srt if synced_vietnamese_srt.exists() else raw_vietnamese_srt,
                tts_audio_path=tts_synced_audio,
                bgm_audio_path=bgm_track_path,
                output_path=final_output_video,
                total_duration_sec=total_duration,
                video_width=video_width,
                video_height=video_height,
                progress_callback=lambda p, msg: notify(6, "Master Render 1-Pass", msg)
            )
            overall_pbar.update(3)

            elapsed_time = time.time() - start_time
            overall_pbar.close()

            notify(8, "Hoàn thành 100%", f"Đã xuất bản video thành công trong {elapsed_time:.1f}s: {final_video.name}")

            console.print(Panel(
                f"[bold green]✔ HOÀN THÀNH XUẤT SẮC QUY TRÌNH EDIT VIDEO![/bold green]\n\n"
                f"• Đường dẫn file thành phẩm: [bold yellow]{final_video.resolve()}[/bold yellow]\n"
                f"• Kích thước: [bold cyan]{final_video.stat().st_size / (1024*1024):.2f} MB[/bold cyan]\n"
                f"• Thời gian xử lý: [bold cyan]{elapsed_time:.2f} giây[/bold cyan]",
                title="[bold green]🎉 THÀNH CÔNG[/bold green]",
                border_style="green"
            ))

            return final_video

        except Exception as e:
            overall_pbar.close()
            logger.exception("Có lỗi nghiêm trọng trong quy trình xử lý:")
            if progress_callback:
                progress_callback(-1, total_steps, "LỖI XỬ LÝ", str(e))
            console.print(Panel(
                f"[bold red]❌ LỖI TRONG QUÁ TRÌNH XỬ LÝ:[/bold red]\n{str(e)}",
                title="[bold red]ERROR[/bold red]",
                border_style="red"
            ))
            raise e
