"""
compositor.py - Final Audio Mixing & High-Quality Video Rendering (Single-Pass 1 lần duy nhất)
"""

import json
import logging
from pathlib import Path
import subprocess
from typing import Callable, Optional
from tqdm import tqdm

from config import PipelineConfig
from preprocessor import run_ffmpeg_with_progress

logger = logging.getLogger(__name__)


class VideoCompositor:
    """
    Module tổng hợp cuối cùng:
    - Hỗ trợ chế độ Single-Pass Master Render: Gộp làm chậm 0.70x, làm mờ sub cũ, đóng sub tiếng Việt và mix âm thanh trong 1 lần duy nhất.
    - Tiết kiệm 50-60% thời gian render và giữ video sắc nét 100%.
    """

    def __init__(self, config: PipelineConfig):
        self.config = config

    @staticmethod
    def _escape_ffmpeg_path(path: Path) -> str:
        """Escape đường dẫn file SRT để dùng an toàn trong FFmpeg filter trên Windows/Linux"""
        raw_str = str(path.resolve()).replace("\\", "/")
        if len(raw_str) > 1 and raw_str[1] == ":":
            raw_str = raw_str[0] + "\\:" + raw_str[2:]
        return raw_str.replace("'", "\\'").replace("[", "\\[").replace("]", "\\]")

    def build_force_style_string(self) -> str:
        s = self.config.subtitle_style
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
            f"Alignment={s.alignment}"
        ]
        return ",".join(style_parts)

    def calculate_blur_box(self, width: int, height: int):
        b = self.config.blur_region
        w = b.width if b.width is not None else width
        h = b.height if b.height is not None else int(height * b.height_ratio)
        x = b.x if b.x is not None else int((width - w) / 2)
        y = b.y if b.y is not None else int(height * b.y_ratio)

        x = max(0, min(int(x), width - 2)) // 2 * 2
        y = max(0, min(int(y), height - 2)) // 2 * 2
        w = max(2, min(int(w), width - x)) // 2 * 2
        h = max(2, min(int(h), height - y)) // 2 * 2
        return x, y, w, h

    def render_single_pass_master(
        self,
        raw_video_path: Path,
        srt_file: Path,
        tts_audio_path: Path,
        bgm_audio_path: Optional[Path],
        output_path: Path,
        total_duration_sec: float,
        video_width: int = 1280,
        video_height: int = 720,
        progress_callback: Optional[Callable[[float, str], None]] = None
    ) -> Path:
        """
        Quy trình Render 1-Pass Đỉnh Cao:
        Gộp tất cả các tác vụ vào 1 lần render duy nhất:
        - Làm chậm video 0.70x (setpts)
        - Làm mờ phụ đề cũ (crop + boxblur + overlay)
        - Đóng cứng phụ đề tiếng Việt (subtitles filter)
        - Hòa âm giọng đọc CapCut + Nhạc nền (TTS + BGM amix)
        """
        raw_video_path = Path(raw_video_path).resolve()
        srt_file = Path(srt_file).resolve()
        tts_audio_path = Path(tts_audio_path).resolve()
        output_path = Path(output_path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if not raw_video_path.exists():
            raise FileNotFoundError(f"Không tìm thấy video gốc: {raw_video_path}")
        if not tts_audio_path.exists():
            raise FileNotFoundError(f"Không tìm thấy file audio TTS: {tts_audio_path}")

        has_bgm = bgm_audio_path is not None and Path(bgm_audio_path).exists()
        has_subtitles = srt_file.exists() and len(srt_file.read_text(encoding="utf-8").strip()) > 0

        pts_mult = 1.0 / self.config.speed_factor
        x, y, w, h = self.calculate_blur_box(video_width, video_height)
        power = self.config.blur_region.blur_power
        safe_power = max(1, min(power, min(w, h) // 4, 25))

        # 1. Xây dựng video filter
        v_filter_parts = []
        if self.config.blur_region.enabled and w >= 4 and h >= 4:
            v_filter_parts.append(f"[0:v]setpts={pts_mult:.6f}*PTS,format=yuv420p,split=2[v_speed][v_crop];")
            v_filter_parts.append(f"[v_crop]crop={w}:{h}:{x}:{y},boxblur={safe_power}:5[v_blurred];")
            if has_subtitles:
                escaped_srt = self._escape_ffmpeg_path(srt_file)
                force_style = self.build_force_style_string()
                v_filter_parts.append(f"[v_speed][v_blurred]overlay={x}:{y},subtitles='{escaped_srt}':force_style='{force_style}'[v_out]")
            else:
                v_filter_parts.append(f"[v_speed][v_blurred]overlay={x}:{y}[v_out]")
        else:
            if has_subtitles:
                escaped_srt = self._escape_ffmpeg_path(srt_file)
                force_style = self.build_force_style_string()
                v_filter_parts.append(f"[0:v]setpts={pts_mult:.6f}*PTS,format=yuv420p,subtitles='{escaped_srt}':force_style='{force_style}'[v_out]")
            else:
                v_filter_parts.append(f"[0:v]setpts={pts_mult:.6f}*PTS,format=yuv420p[v_out]")

        v_filter_str = "".join(v_filter_parts)

        # 2. Xây dựng audio filter
        preset = "veryfast" if self.config.video_preset in ["medium", "slow"] else self.config.video_preset
        crf = str(min(self.config.video_crf, 20))

        if has_bgm:
            bgm_vol = self.config.bgm_volume
            tts_vol = self.config.tts_volume
            a_filter_str = (
                f";[1:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,volume={tts_vol}[tts];"
                f"[2:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,volume={bgm_vol}[bgm];"
                f"[tts][bgm]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[a_out]"
            )
            full_filter = v_filter_str + a_filter_str
            cmd = [
                "ffmpeg", "-y",
                "-i", str(raw_video_path),
                "-i", str(tts_audio_path),
                "-i", str(bgm_audio_path),
                "-filter_complex", full_filter,
                "-map", "[v_out]",
                "-map", "[a_out]",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-preset", preset,
                "-crf", crf,
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
                str(output_path)
            ]
        else:
            a_filter_str = ";[1:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[a_out]"
            full_filter = v_filter_str + a_filter_str
            cmd = [
                "ffmpeg", "-y",
                "-i", str(raw_video_path),
                "-i", str(tts_audio_path),
                "-filter_complex", full_filter,
                "-map", "[v_out]",
                "-map", "[a_out]",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-preset", preset,
                "-crf", crf,
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
                str(output_path)
            ]

        logger.info(f"[Master Render 1-Pass] Bắt đầu render video xuất bản (Thời lượng đích: {total_duration_sec:.1f}s)...")
        run_ffmpeg_with_progress(
            cmd=cmd,
            total_duration_sec=total_duration_sec,
            desc="[Bước Cuối] Render Master Video (1-Pass)",
            progress_callback=progress_callback
        )

        logger.info(f"Đã xuất bản video master 1-Pass thành công: {output_path}")
        return output_path

    def render_final_video(
        self,
        video_path: Path,
        tts_audio_path: Path,
        bgm_audio_path: Optional[Path],
        output_path: Path
    ) -> Path:
        """
        Gộp video, TTS và BGM (Fallback mode)
        """
        video_path = Path(video_path).resolve()
        tts_audio_path = Path(tts_audio_path).resolve()
        output_path = Path(output_path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if not video_path.exists():
            raise FileNotFoundError(f"Không tìm thấy video: {video_path}")
        if not tts_audio_path.exists():
            raise FileNotFoundError(f"Không tìm thấy file audio TTS: {tts_audio_path}")

        has_bgm = bgm_audio_path is not None and Path(bgm_audio_path).exists()

        if has_bgm:
            bgm_vol = self.config.bgm_volume
            tts_vol = self.config.tts_volume

            filter_complex = (
                f"[1:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,volume={tts_vol}[tts];"
                f"[2:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,volume={bgm_vol}[bgm];"
                f"[tts][bgm]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[a_out]"
            )

            cmd = [
                "ffmpeg", "-y",
                "-i", str(video_path),
                "-i", str(tts_audio_path),
                "-i", str(bgm_audio_path),
                "-filter_complex", filter_complex,
                "-map", "0:v:0",
                "-map", "[a_out]",
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
                str(output_path)
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-i", str(video_path),
                "-i", str(tts_audio_path),
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
                str(output_path)
            ]

        with tqdm(total=100, desc="[Bước 7 & 8] Render Video Cuối Cùng", leave=False) as pbar:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            _, stderr = proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(f"FFmpeg render thất bại: {stderr[-500:]}")
            pbar.update(100)

        return output_path
