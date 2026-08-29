"""
subtitle_burner.py - Hardcode (Burn-in) Subtitles to Video with Custom Styling and Real-Time Progress
"""

import logging
from pathlib import Path
import subprocess
from typing import Callable, Optional
from tqdm import tqdm

from config import PipelineConfig, SubtitleStyle
from preprocessor import run_ffmpeg_with_progress

logger = logging.getLogger(__name__)


class SubtitleBurner:
    """
    Module chèn phụ đề cứng (Hardsub / Burn-in) vào video bằng FFmpeg.
    Cho phép tùy biến Font chữ, Kích thước, Màu sắc, Viền chữ (Outline), Bóng (Shadow), Vị trí.
    """

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.style: SubtitleStyle = config.subtitle_style

    @staticmethod
    def _escape_ffmpeg_path(path: Path) -> str:
        """Escape đường dẫn file SRT để dùng an toàn trong FFmpeg filter trên Windows/Linux"""
        raw_str = str(path.resolve()).replace("\\", "/")
        if len(raw_str) > 1 and raw_str[1] == ":":
            raw_str = raw_str[0] + "\\:" + raw_str[2:]
        return raw_str.replace("'", "\\'").replace("[", "\\[").replace("]", "\\]")

    def build_force_style_string(self) -> str:
        s = self.style
        style_parts = [
            f"FontName={s.font_name}",
            f"FontSize={s.font_size}",
            f"PrimaryColour={s.primary_color}",
            f"OutlineColour={s.outline_color}",
            f"BackColour={s.back_color}",
            f"Bold={s.bold}",
            f"Outline={s.outline_width}",
            f"Shadow={s.shadow}",
            f"MarginV={s.margin_v}",
            f"Alignment={s.alignment}",
            f"BorderStyle={getattr(s, 'border_style', 1)}"
        ]
        return ",".join(style_parts)

    def burn_subtitles(
        self,
        input_video: Path,
        srt_file: Path,
        output_video: Path,
        total_duration_sec: float = 0.0,
        progress_callback: Optional[Callable[[float, str], None]] = None
    ) -> Path:
        """Hardcode file SRT vào video với các thông số kiểu dáng đã cấu hình"""
        input_video = Path(input_video).resolve()
        srt_file = Path(srt_file).resolve()
        output_video = Path(output_video).resolve()
        output_video.parent.mkdir(parents=True, exist_ok=True)

        if not input_video.exists():
            raise FileNotFoundError(f"Không tìm thấy video đầu vào: {input_video}")
        if not srt_file.exists():
            raise FileNotFoundError(f"Không tìm thấy file SRT: {srt_file}")

        # Kiểm tra file SRT có nội dung hợp lệ không
        srt_content = srt_file.read_text(encoding="utf-8").strip()
        if not srt_content:
            logger.warning("[Bước 4] File SRT rỗng (không có câu phụ đề nào). Bỏ qua filter burn-in và sao chép video trực tiếp...")
            cmd_copy = [
                "ffmpeg", "-y",
                "-i", str(input_video),
                "-c", "copy",
                str(output_video)
            ]
            subprocess.run(cmd_copy, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            return output_video

        escaped_srt = self._escape_ffmpeg_path(srt_file)
        force_style = self.build_force_style_string()

        subtitle_filter = f"subtitles='{escaped_srt}':force_style='{force_style}'"

        preset = "veryfast" if self.config.video_preset in ["medium", "slow"] else self.config.video_preset
        crf = str(min(self.config.video_crf, 20))

        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_video),
            "-vf", subtitle_filter,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", preset,
            "-crf", crf,
            "-c:a", "copy",
            str(output_video)
        ]

        logger.info(f"[Bước 4] Đang hardcode phụ đề vào video: {output_video.name}...")
        run_ffmpeg_with_progress(
            cmd=cmd,
            total_duration_sec=total_duration_sec,
            desc="[Bước 4] Hardcode Phụ Đề (Burn-in)",
            progress_callback=progress_callback
        )

        logger.info(f"Hoàn thành chèn phụ đề: {output_video}")
        return output_video
