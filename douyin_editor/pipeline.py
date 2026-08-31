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

from config import BlurRegion, CookieConfig, PipelineConfig, TRANSLATION_TOPIC_PRESETS
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
    Thực hiện lần lượt các bước từ link Douyin đến video thành phẩm MP4.
    Tích hợp AI UVR MDX-Net bóc tách nhạc nền gốc ra MP3 320k, làm chậm 0.70x và giữ 100% âm lượng gốc.
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
        table.add_row("Tốc độ video (Speed)", f"{self.config.speed_factor}x (Chậm {int((1-self.config.speed_factor)*100)}%)")
        table.add_row("Tốc độ xuất bản", f"{getattr(self.config, 'final_speed', 1.20)}x")
        table.add_row("Vùng mờ Sub gốc (Blur)", f"Y: {self.config.blur_region.y_ratio*100:.0f}% | Height: {self.config.blur_region.height_ratio*100:.0f}%")
        table.add_row("Whisper Model", f"{self.config.whisper_model_size} (Lang: {self.config.whisper_language})")
        ai_model_name = getattr(self.config, "deepseek_model_name", "deepseek-v4-flash")
        table.add_row("AI Dịch thuật", f"DeepSeek AI ({ai_model_name})")
        topic_info = TRANSLATION_TOPIC_PRESETS.get(getattr(self.config, "topic_preset", "minecraft_kids"), {}).get("name", "Minecraft cho Trẻ Em")
        table.add_row("Chủ đề dịch thuật", topic_info)
        table.add_row("Giọng đọc tiếng Việt (TTS)", self.config.tts_config.voice)
        table.add_row("Font chữ Hardsub", f"{self.config.subtitle_style.font_name} (Size: {self.config.subtitle_style.font_size}px)")
        
        sep_status = f"Bật AI MDX-Net ({self.config.separation_speed.upper()})" if self.config.keep_bgm else "Tắt (Mute)"
        table.add_row("Tách giọng gốc / BGM", sep_status)
        table.add_row("Âm lượng BGM gốc", f"{int(self.config.bgm_volume * 100)}% (Giữ nguyên âm lượng gốc)")

        console.print(Panel(table, title="[bold yellow]🚀 DOUYIN AUTO VIDEO EDITING PIPELINE (MDX-NET AI)[/bold yellow]", expand=False))

    def run(
        self,
        douyin_url_or_text: str,
        custom_name: Optional[str] = None,
        progress_callback: Optional[Callable[[int, int, str, str], None]] = None,
        interactive_roi_callback: Optional[Callable[[Path, BlurRegion, Optional[SubtitleStyle]], Tuple[BlurRegion, Optional[SubtitleStyle]]]] = None
    ) -> Path:
        """
        Kích hoạt toàn bộ quy trình tự động.
        :param progress_callback: Hàm nhận (current_step, total_steps, step_name, log_message)
        :param interactive_roi_callback: Hàm mở Studio cho người dùng khoanh vùng mờ & chỉnh tay phụ đề trên video vừa tải
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

            # Người dùng tự chọn vùng làm mờ và chỉnh tay phụ đề trên video vừa tải (nếu bật)
            if interactive_roi_callback:
                notify(2, "Bước 2: Chỉnh sửa trực quan", "Vui lòng khoanh vùng làm mờ & chỉnh vị trí phụ đề trên cửa sổ xem trước...")
                chosen_res = interactive_roi_callback(raw_video, self.config.blur_region, self.config.subtitle_style)
                if isinstance(chosen_res, tuple) and len(chosen_res) == 2:
                    chosen_region, chosen_style = chosen_res
                    if chosen_region:
                        self.config.blur_region = chosen_region
                        self.preprocessor.blur_config = chosen_region
                    if chosen_style:
                        self.config.subtitle_style = chosen_style
                        self.burner.style = chosen_style
                elif chosen_res:
                    self.config.blur_region = chosen_res
                    self.preprocessor.blur_config = chosen_res

            # Thư mục tạm riêng cho từng video
            session_work_dir = self.config.work_dir / video_id
            session_work_dir.mkdir(parents=True, exist_ok=True)

            # Khai báo đường dẫn các tài nguyên trung gian
            original_srt = session_work_dir / "original_subtitles.srt"
            raw_vietnamese_srt = session_work_dir / "vietnamese_raw_subtitles.srt"
            synced_vietnamese_srt = session_work_dir / "vietnamese_synced_subtitles.srt"
            tts_synced_audio = session_work_dir / f"{video_id}_tts_synced.wav"
            final_output_video = self.config.output_dir / f"output_{video_id}_vi.mp4"

            raw_video_info = self.preprocessor.get_video_info(raw_video)
            video_width = raw_video_info["width"]
            video_height = raw_video_info["height"]
            orig_duration = raw_video_info["duration"]
            total_duration = orig_duration / self.config.speed_factor if self.config.speed_factor > 0 else orig_duration

            # ==========================================
            # BƯỚC 2: TÁCH GIỌNG AI MDX-NET, BGM 0.70x & WHISPER STT
            # ==========================================
            bgm_track_path: Optional[Path] = None

            if self.config.keep_bgm:
                notify(2, "Bước 2: Tách Giọng AI MDX-Net", "Đang bóc tách nhạc nền gốc ra MP3 320k & giọng nói tiếng Trung...")
                console.print("[bold cyan]▶ BƯỚC 2: Tách giọng AI MDX-Net -> Xuất BGM MP3 320k & Làm chậm 0.70x (100% âm lượng)...[/bold cyan]")
                
                bgm_orig_mp3, bgm_slowed, vocals_slowed = self.separator.process_pipeline_audio(
                    raw_video_path=raw_video,
                    session_work_dir=session_work_dir,
                    video_id=video_id,
                    speed_factor=self.config.speed_factor,
                    progress_callback=lambda p, msg: notify(2, "Bước 2: Tách Giọng AI MDX-Net", msg)
                )
                bgm_track_path = bgm_slowed
                whisper_audio_source = vocals_slowed
            else:
                notify(2, "Bước 2: Trích xuất Audio Siêu Tốc", f"Đang trích xuất audio và giảm tốc độ {self.config.speed_factor}x...")
                extracted_audio = session_work_dir / f"{video_id}_slowed_audio.wav"
                self.preprocessor.extract_audio_for_stt(
                    input_video=raw_video,
                    output_audio=extracted_audio
                )
                bgm_track_path = None
                whisper_audio_source = extracted_audio

            notify(2, "Bước 2: Whisper Speech-to-Text", "Đang nhận diện giọng nói tiếng Trung sang file phụ đề SRT (trên track sạch)...")
            console.print("[bold cyan]▶ BƯỚC 2 (tiếp): Whisper AI nhận diện giọng nói tiếng Trung trên track Vocals sạch -> SRT...[/bold cyan]")
            self.transcriber.transcribe(
                audio_path=whisper_audio_source,
                output_srt=original_srt
            )
            overall_pbar.update(1)

            # ==========================================
            # BƯỚC 3: DỊCH THUẬT VỚI DEEPSEEK AI
            # ==========================================
            notify(3, "Bước 3: Dịch thuật DeepSeek", "Đang dịch phụ đề Trung -> Việt giữ nguyên timeline...")
            console.print(f"[bold cyan]▶ BƯỚC 3: Dịch phụ đề sang Tiếng Việt bằng DeepSeek API ({self.translator.model_name})...[/bold cyan]")
            raw_vn_subtitles = self.translator.translate_srt(
                input_srt_path=original_srt,
                output_srt_path=raw_vietnamese_srt
            )
            overall_pbar.update(1)

            # ==========================================
            # BƯỚC 4: CAPCUT TTS & ĐỒNG BỘ PHỤ ĐỀ TỪNG CÂU KHỚP GIỌNG NÓI
            # ==========================================
            notify(4, "Bước 4: CapCut TTS & Đồng bộ phụ đề", f"Đang đọc giọng {self.config.tts_config.preset_name or self.config.tts_config.voice} và căn khớp từng câu...")
            console.print(f"[bold cyan]▶ BƯỚC 4: Đọc phụ đề tiếng Việt bằng CapCut TTS ({self.config.tts_config.preset_name}) & đồng bộ timeline từng câu ngắn...[/bold cyan]")
            tts_synced_audio, synced_vn_subtitles = self.tts_syncer.generate_and_sync(
                subtitles=raw_vn_subtitles,
                total_duration_seconds=total_duration,
                output_audio_path=tts_synced_audio,
                output_srt_path=synced_vietnamese_srt
            )
            overall_pbar.update(2)

            # ==========================================
            # BƯỚC 5, 6, 7 & 8: SINGLE-PASS MASTER RENDER (GỘP TẤT CẢ TRONG 1 LẦN RENDER DUY NHẤT)
            # ==========================================
            sub_count = len(synced_vn_subtitles) if synced_vn_subtitles else len(raw_vn_subtitles)
            notify(6, "Bước Cuối: Master Render 1-Pass", f"Đang làm chậm {self.config.speed_factor:.2f}x, làm mờ sub cũ, đóng {sub_count} câu phụ đề & mix BGM (100% vol)...")
            console.print(f"[bold cyan]▶ BƯỚC CUỐI: Single-Pass Master Render (0.70x + Blur + Hardsub {sub_count} câu + Lồng tiếng CapCut & BGM 100% âm lượng)...[/bold cyan]")
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
