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
        table.add_row("Độ phân giải xuất", f"{getattr(self.config, 'export_resolution', '1080p').upper()} (Chuẩn Full HD)")
        blur_status = f"Y: {self.config.blur_region.y_ratio*100:.0f}% | Height: {self.config.blur_region.height_ratio*100:.0f}%" if self.config.blur_region.enabled else "Tắt (Không làm mờ)"
        table.add_row("Vùng mờ Sub gốc (Blur)", blur_status)
        if getattr(self.config, "llm_provider", "deepseek") == "chatgpt_cookie":
            ai_info = f"ChatGPT Web Cookie ({getattr(self.config, 'chatgpt_model_name', 'auto')})"
        else:
            ai_model_name = getattr(self.config, "deepseek_model_name", "deepseek-v4-flash")
            ai_info = f"DeepSeek AI ({ai_model_name})"
        table.add_row("AI Dịch thuật", ai_info)
        topic_info = TRANSLATION_TOPIC_PRESETS.get(getattr(self.config, "topic_preset", "general_storytelling"), {}).get("name", "Kể Chuyện Viral Tổng Hợp")
        if getattr(self.config, "custom_translation_prompt", None):
            topic_info += " (+ Ghi chú kịch bản)"
        table.add_row("Chủ đề dịch thuật", topic_info)
        table.add_row("Giọng đọc tiếng Việt (TTS)", self.config.tts_config.voice)
        sub_status = f"{self.config.subtitle_style.font_name} (Size: {self.config.subtitle_style.font_size}px)" if getattr(self.config, "enable_subtitles", True) else "Tắt (Không đóng phụ đề)"
        table.add_row("Phụ đề Hardsub", sub_status)
        
        audio_mode = getattr(self.config, "audio_mode", "keep_original")
        if audio_mode == "keep_original":
            orig_vol_pct = int(getattr(self.config, "original_audio_volume", 0.60) * 100)
            table.add_row("Âm thanh video gốc", f"Giữ nguyên (Ko tách giọng) - Âm lượng {orig_vol_pct}%")
        elif audio_mode == "separate_bgm" or (audio_mode is None and self.config.keep_bgm):
            sep_status = f"Bật AI MDX-Net ({self.config.separation_speed.upper()})"
            table.add_row("Tách giọng gốc / BGM", sep_status)
            table.add_row("Âm lượng BGM gốc", f"{int(self.config.bgm_volume * 100)}% (Nhạc nền tách AI)")
        else:
            table.add_row("Âm thanh nền", "Tắt (Chỉ giữ giọng đọc AI TTS)")

        console.print(Panel(table, title="[bold yellow]🚀 DOUYIN AUTO VIDEO EDITING PIPELINE[/bold yellow]", expand=False))

    def run(
        self,
        douyin_url_or_text: str,
        custom_name: Optional[str] = None,
        progress_callback: Optional[Callable[[int, int, str, str], None]] = None,
        interactive_roi_callback: Optional[Callable[[Path, BlurRegion, Optional[SubtitleStyle]], Tuple[BlurRegion, Optional[SubtitleStyle]]]] = None,
        subtitles_callback: Optional[Callable[[dict], None]] = None,
        review_subtitles_callback: Optional[Callable[[Path, Path], None]] = None
    ) -> Path:
        """
        Kích hoạt toàn bộ quy trình tự động.
        :param progress_callback: Hàm nhận (current_step, total_steps, step_name, log_message)
        :param interactive_roi_callback: Hàm mở Studio cho người dùng khoanh vùng mờ & chỉnh tay phụ đề trên video vừa tải
        :param subtitles_callback: Hàm nhận dữ liệu cập nhật danh sách & thống kê phụ đề thời gian thực lên GUI
        :param review_subtitles_callback: Hàm dừng lại chờ người dùng kiểm tra / duyệt phụ đề trước khi render
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
                if isinstance(chosen_res, tuple):
                    if len(chosen_res) >= 1 and chosen_res[0]:
                        self.config.blur_region = chosen_res[0]
                        self.preprocessor.blur_config = chosen_res[0]
                    if len(chosen_res) >= 2 and chosen_res[1]:
                        self.config.subtitle_style = chosen_res[1]
                        self.burner.style = chosen_res[1]
                    if len(chosen_res) >= 3 and chosen_res[2] is not None:
                        self.config.enable_subtitles = bool(chosen_res[2])
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
            # BƯỚC 2: XỬ LÝ ÂM THANH (GIỮ NGUYÊN GỐC / TÁCH BGM) & WHISPER STT
            # ==========================================
            bgm_track_path: Optional[Path] = None
            audio_mode = getattr(self.config, "audio_mode", "keep_original")
            if not self.config.keep_bgm:
                audio_mode = "mute_original"

            if audio_mode == "keep_original":
                orig_vol_pct = int(getattr(self.config, "original_audio_volume", 0.60) * 100)
                notify(2, "Bước 2: Trích Xuất Âm Thanh Gốc", f"Đang trích xuất âm thanh gốc 0.70x (không tách giọng, âm lượng {orig_vol_pct}%)...")
                console.print(f"[bold cyan]▶ BƯỚC 2: Giữ nguyên âm thanh video gốc 0.70x (Không tách giọng, âm lượng {orig_vol_pct}%)...[/bold cyan]")
                
                orig_slowed_audio = session_work_dir / f"{video_id}_orig_slowed_44k.wav"
                self.preprocessor.extract_slowed_original_audio(
                    input_video=raw_video,
                    output_audio=orig_slowed_audio,
                    sample_rate=44100,
                    channels=2
                )
                bgm_track_path = orig_slowed_audio
                whisper_audio_source = orig_slowed_audio
                # Đặt âm lượng hòa âm cho compositor
                self.config.bgm_volume = getattr(self.config, "original_audio_volume", 0.60)

            elif audio_mode == "separate_bgm":
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

            else:  # "mute_original"
                notify(2, "Bước 2: Trích xuất Audio Siêu Tốc", f"Đang trích xuất audio và giảm tốc độ {self.config.speed_factor}x...")
                extracted_audio = session_work_dir / f"{video_id}_slowed_audio.wav"
                self.preprocessor.extract_audio_for_stt(
                    input_video=raw_video,
                    output_audio=extracted_audio
                )
                bgm_track_path = None
                whisper_audio_source = extracted_audio

            notify(2, "Bước 2: Local Speech-to-Text", "Đang nhận diện giọng nói tiếng Trung qua Local STT Engine...")
            console.print("[bold cyan]▶ BƯỚC 2 (tiếp): Local STT nhận diện giọng nói tiếng Trung -> SRT...[/bold cyan]")
            original_sub_items = self.transcriber.transcribe(
                audio_path=whisper_audio_source,
                output_srt=original_srt
            )
            
            # Tính toán thống kê tình trạng phụ đề
            from transcriber import calculate_subtitle_stats
            stt_stats = calculate_subtitle_stats(original_sub_items, total_duration=total_duration)
            
            if subtitles_callback:
                subtitles_callback({
                    "stage": "stt",
                    "items": [item.to_dict() for item in original_sub_items],
                    "stats": stt_stats,
                    "original_srt": str(original_srt)
                })

            notify(2, "Bước 2: STT Hoàn Tất", f"Đã nhận diện {len(original_sub_items)} câu thoại ({stt_stats['status_badge']}).")
            overall_pbar.update(1)

            # ==========================================
            # BƯỚC 3: DỊCH THUẬT VỚI AI (DEEPSEEK / CHATGPT)
            # ==========================================
            provider_title = "ChatGPT Web" if getattr(self.config, "llm_provider", "deepseek") == "chatgpt_cookie" else "DeepSeek"
            model_info = getattr(self.translator, "model_name", "auto")
            notify(3, f"Bước 3: Dịch thuật {provider_title}", f"Đang dịch phụ đề Trung -> Việt bằng {provider_title} AI ({model_info})...")
            console.print(f"[bold cyan]▶ BƯỚC 3: Dịch phụ đề sang Tiếng Việt bằng {provider_title} AI ({model_info})...[/bold cyan]")
            raw_vn_subtitles = self.translator.translate_srt(
                input_srt_path=original_srt,
                output_srt_path=raw_vietnamese_srt
            )

            # Ghép phụ đề dịch vào danh sách gốc
            for idx, vn_item in enumerate(raw_vn_subtitles):
                if idx < len(original_sub_items):
                    original_sub_items[idx].translated_text = vn_item.text

            if subtitles_callback:
                subtitles_callback({
                    "stage": "translated",
                    "items": [item.to_dict() for item in original_sub_items],
                    "stats": stt_stats,
                    "original_srt": str(original_srt),
                    "translated_srt": str(raw_vietnamese_srt)
                })

            notify(3, f"Bước 3: Dịch {provider_title} Xong", f"Đã dịch {len(raw_vn_subtitles)} câu sang tiếng Việt chuẩn ngữ cảnh.")
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

            if subtitles_callback:
                # Cập nhật timeline đã sync
                synced_items_data = []
                for idx, syn_item in enumerate(synced_vn_subtitles):
                    orig_text = original_sub_items[idx].text if idx < len(original_sub_items) else ""
                    synced_items_data.append({
                        "index": syn_item.index,
                        "start_seconds": syn_item.start_seconds,
                        "end_seconds": syn_item.end_seconds,
                        "start_str": syn_item.start_str,
                        "end_str": syn_item.end_str,
                        "duration": round(syn_item.end_seconds - syn_item.start_seconds, 2),
                        "text": orig_text,
                        "translated_text": syn_item.text
                    })
                subtitles_callback({
                    "stage": "synced",
                    "items": synced_items_data,
                    "stats": stt_stats,
                    "original_srt": str(original_srt),
                    "translated_srt": str(raw_vietnamese_srt),
                    "synced_srt": str(synced_vietnamese_srt)
                })

            overall_pbar.update(2)

            # Tùy chọn dừng lại để người dùng duyệt / sửa phụ đề trên GUI
            if review_subtitles_callback:
                notify(5, "Bước 5: Kiểm tra & Duyệt Phụ đề", "Đang chờ bạn kiểm tra & xác nhận phụ đề trên giao diện GUI...")
                review_subtitles_callback(session_work_dir, synced_vietnamese_srt if synced_vietnamese_srt.exists() else raw_vietnamese_srt)

            # ==========================================
            # BƯỚC 5, 6, 7 & 8: SINGLE-PASS MASTER RENDER (GỘP TẤT CẢ TRONG 1 LẦN RENDER DUY NHẤT)
            # ==========================================
            sub_count = len(synced_vn_subtitles) if synced_vn_subtitles else len(raw_vn_subtitles)
            blur_status_str = "BẬT" if self.config.blur_region.enabled else "TẮT"
            sub_status_str = f"BẬT ({sub_count} câu)" if getattr(self.config, "enable_subtitles", True) else "TẮT"
            notify(6, "Bước Cuối: Master Render 1-Pass", f"Đang render (Làm mờ: {blur_status_str} | Phụ đề: {sub_status_str} | Tốc độ {getattr(self.config, 'final_speed', 1.2):.2f}x)...")
            console.print(f"[bold cyan]▶ BƯỚC CUỐI: Single-Pass Master Render (Làm mờ: {blur_status_str} | Phụ đề: {sub_status_str} | Lồng tiếng CapCut & Audio gốc)...[/bold cyan]")
            final_video = self.compositor.render_single_pass_master(
                raw_video_path=raw_video,
                srt_file=synced_vietnamese_srt if synced_vietnamese_srt.exists() else raw_vietnamese_srt,
                tts_audio_path=tts_synced_audio,
                bgm_audio_path=bgm_track_path,
                output_path=final_output_video,
                total_duration_sec=total_duration,
                video_width=video_width,
                video_height=video_height,
                progress_callback=lambda p, msg: notify(6, "Master Render 1-Pass", msg),
                original_srt_file=original_srt if original_srt.exists() else None
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
