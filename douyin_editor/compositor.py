"""
compositor.py - Final Audio Mixing & High-Quality Video Rendering (Single-Pass 1 lần duy nhất)
"""

import json
import logging
from pathlib import Path
import re
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
    - Hỗ trợ tăng tốc video xuất bản ở Bước 8 lên 1.2x (hoặc tùy chỉnh) với âm thanh giữ nguyên cao độ (pitch) và phụ đề đồng bộ 100%.
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

    @staticmethod
    def scale_srt_file(input_srt: Path, output_srt: Path, speed: float) -> Path:
        """Căn chỉnh lại toàn bộ mốc thời gian phụ đề theo tốc độ tăng tốc final_speed (ví dụ 1.2x)"""
        if abs(speed - 1.0) < 0.001 or not input_srt.exists():
            return input_srt
        content = input_srt.read_text(encoding="utf-8")
        if not content.strip():
            return input_srt

        def repl(match):
            h1, m1, s1, ms1, h2, m2, s2, ms2 = map(int, match.groups())
            t1 = (h1 * 3600 + m1 * 60 + s1 + ms1 / 1000.0) / speed
            t2 = (h2 * 3600 + m2 * 60 + s2 + ms2 / 1000.0) / speed

            def fmt(t):
                if t < 0:
                    t = 0.0
                h = int(t // 3600)
                m = int((t % 3600) // 60)
                s = int(t % 60)
                ms = int(round((t - int(t)) * 1000))
                if ms >= 1000:
                    s += 1
                    ms -= 1000
                return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

            return f"{fmt(t1)} --> {fmt(t2)}"

        pattern = r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})"
        scaled_content = re.sub(pattern, repl, content)
        output_srt.write_text(scaled_content, encoding="utf-8")
        return output_srt

    @staticmethod
    def parse_srt_intervals(srt_path: Path, merge_gap: float = 0.35, pad_sec: float = 0.10) -> list[tuple[float, float]]:
        """
        Trích xuất danh sách các khoảng thời gian (start, end) có phụ đề hiển thị từ file SRT.
        Tự động mở rộng nhẹ (pad_sec) và gộp các khoảng gần nhau (gap <= merge_gap giây)
        để che phủ trọn vẹn 100% phụ đề gốc, không để lọt bất kỳ khung hình tiếng Trung nào.
        """
        if not srt_path.exists():
            return []
        try:
            content = srt_path.read_text(encoding="utf-8")
        except Exception:
            return []
        if not content.strip():
            return []

        pattern = r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
        raw_intervals = []
        for m in re.finditer(pattern, content):
            h1, m1, s1, ms1, h2, m2, s2, ms2 = map(int, m.groups())
            t1 = max(0.0, h1 * 3600 + m1 * 60 + s1 + ms1 / 1000.0 - pad_sec)
            t2 = h2 * 3600 + m2 * 60 + s2 + ms2 / 1000.0 + pad_sec
            if t2 > t1:
                raw_intervals.append((t1, t2))

        if not raw_intervals:
            return []

        # Sắp xếp và gộp các khoảng thời gian gần nhau
        raw_intervals.sort(key=lambda x: x[0])
        merged = [raw_intervals[0]]
        for cur_start, cur_end in raw_intervals[1:]:
            prev_start, prev_end = merged[-1]
            if cur_start <= prev_end + merge_gap:
                merged[-1] = (prev_start, max(prev_end, cur_end))
            else:
                merged.append((cur_start, cur_end))
        return merged

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
            f"Alignment={s.alignment}",
            f"BorderStyle={getattr(s, 'border_style', 1)}"
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
        - Làm chậm video 0.70x (setpts) và tăng tốc xuất bản 1.2x ở Bước 8
        - Làm mờ phụ đề cũ (chỉ làm mờ thông minh khi có phụ đề xuất hiện trên màn hình, tự động ẩn khi không có phụ đề)
        - Đóng cứng phụ đề tiếng Việt (subtitles filter chuẩn tốc độ 1.2x)
        - Hòa âm giọng đọc CapCut + Nhạc nền (TTS + BGM amix + atempo=1.2x)
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

        final_speed = float(getattr(self.config, "final_speed", 1.20))
        if final_speed <= 0:
            final_speed = 1.0

        # Tính toán PTS hiệu dụng: Kết hợp làm chậm 0.70x và tăng tốc xuất bản 1.2x
        pts_mult = (1.0 / self.config.speed_factor) / final_speed
        real_target_duration = total_duration_sec / final_speed if final_speed > 0 else total_duration_sec

        x, y, w, h = self.calculate_blur_box(video_width, video_height)
        power = self.config.blur_region.blur_power
        safe_power = max(1, min(power, min(w, h) // 4, 25))

        # Căn chỉnh lại file SRT theo tốc độ 1.2x
        burn_srt_file = srt_file
        if has_subtitles and abs(final_speed - 1.0) >= 0.001:
            scaled_srt_path = output_path.parent / f"{output_path.stem}_scaled_{final_speed}x.srt"
            burn_srt_file = self.scale_srt_file(srt_file, scaled_srt_path, final_speed)

        # Lấy danh sách khoảng thời gian có phụ đề (trên timeline xuất bản)
        sub_intervals = self.parse_srt_intervals(burn_srt_file) if has_subtitles else []
        has_valid_subs = len(sub_intervals) > 0

        # 1. Xây dựng video filter (Làm mờ động thông minh: chỉ mờ khi có sub hiển thị, không có sub thì giữ nguyên video gốc)
        v_filter_parts = []
        if self.config.blur_region.enabled and w >= 4 and h >= 4 and has_valid_subs:
            # Tạo biểu thức enable cho overlay chỉ kích hoạt trong các khoảng thời gian có phụ đề
            enable_expr = "+".join(f"between(t,{st:.3f},{en:.3f})" for st, en in sub_intervals)
            escaped_srt = self._escape_ffmpeg_path(burn_srt_file)
            force_style = self.build_force_style_string()
            v_filter_parts.append(f"[0:v]setpts={pts_mult:.6f}*PTS,format=yuv420p,split=2[v_speed][v_crop];")
            v_filter_parts.append(f"[v_crop]crop={w}:{h}:{x}:{y},boxblur={safe_power}:5[v_blurred];")
            v_filter_parts.append(f"[v_speed][v_blurred]overlay={x}:{y}:enable='{enable_expr}',subtitles='{escaped_srt}':force_style='{force_style}'[v_out]")
        elif has_valid_subs:
            # Có phụ đề nhưng người dùng tắt tùy chọn làm mờ
            escaped_srt = self._escape_ffmpeg_path(burn_srt_file)
            force_style = self.build_force_style_string()
            v_filter_parts.append(f"[0:v]setpts={pts_mult:.6f}*PTS,format=yuv420p,subtitles='{escaped_srt}':force_style='{force_style}'[v_out]")
        else:
            # Hoàn toàn không có phụ đề: Giữ nguyên video gốc sắc nét, tuyệt đối không làm mờ
            logger.info("Video không có phụ đề (hoặc file phụ đề rỗng) -> Tự động bỏ làm mờ để giữ nguyên hình ảnh gốc sắc nét đẹp mắt.")
            v_filter_parts.append(f"[0:v]setpts={pts_mult:.6f}*PTS,format=yuv420p[v_out]")

        v_filter_str = "".join(v_filter_parts)

        # 2. Xây dựng audio filter (kèm atempo=final_speed giữ nguyên pitch)
        preset = "veryfast" if self.config.video_preset in ["medium", "slow"] else self.config.video_preset
        crf = str(min(self.config.video_crf, 20))

        atempo_filter = f",atempo={final_speed:.4f}" if abs(final_speed - 1.0) >= 0.001 else ""

        if has_bgm:
            bgm_vol = self.config.bgm_volume
            tts_vol = self.config.tts_volume
            a_filter_str = (
                f";[1:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,volume={tts_vol}[tts];"
                f"[2:a]aloop=loop=-1:size=2e+09,aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,volume={bgm_vol}[bgm];"
                f"[tts][bgm]amix=inputs=2:duration=first:dropout_transition=2:normalize=0{atempo_filter}[a_out]"
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
            a_filter_str = f";[1:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo{atempo_filter}[a_out]"
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

        logger.info(f"[Master Render 1-Pass] Render video hoàn thiện với tốc độ {final_speed}x (Thời lượng đích: {real_target_duration:.1f}s)...")
        run_ffmpeg_with_progress(
            cmd=cmd,
            total_duration_sec=real_target_duration,
            desc=f"[Bước 8] Render Master Video ({final_speed}x)",
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
