"""
preprocessor.py - Video Preprocessing (Speed 0.70x, Subtitle Boxblur, Audio Extraction) with Real-Time Progress
"""

import json
import logging
from pathlib import Path
import re
import subprocess
import time
from typing import Callable, Dict, Optional, Tuple
from tqdm import tqdm

from config import BlurRegion, PipelineConfig

logger = logging.getLogger(__name__)


def run_ffmpeg_with_progress(
    cmd: list,
    total_duration_sec: float,
    desc: str = "FFmpeg Processing",
    progress_callback: Optional[Callable[[float, str], None]] = None
) -> None:
    """
    Thực thi lệnh FFmpeg với thanh tiến trình thời gian thực (Real-time Progress Bar & FPS/Speed).
    """
    # Thêm -progress pipe:1 để FFmpeg in tiến trình máy đọc được qua stdout
    enhanced_cmd = []
    has_progress_flag = False
    for arg in cmd:
        enhanced_cmd.append(arg)
        if arg == "-y":
            enhanced_cmd.extend(["-progress", "pipe:1", "-nostats"])
            has_progress_flag = True

    if not has_progress_flag:
        enhanced_cmd = [cmd[0], "-progress", "pipe:1", "-nostats"] + cmd[1:]

    proc = subprocess.Popen(
        enhanced_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        bufsize=1
    )

    pbar = tqdm(total=100, desc=desc, leave=False, bar_format="{l_bar}{bar}| {n_fmt}% [{elapsed}<{remaining}, {postfix}]")

    current_fps = "0"
    current_speed = "0x"
    last_update_time = 0
    stderr_lines = []

    def read_stderr():
        for line in proc.stderr:
            stderr_lines.append(line)
            if len(stderr_lines) > 50:
                stderr_lines.pop(0)

    import threading
    t_err = threading.Thread(target=read_stderr, daemon=True)
    t_err.start()

    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue

        if line.startswith("fps="):
            current_fps = line.split("=")[1].strip()
        elif line.startswith("speed="):
            current_speed = line.split("=")[1].strip()
        elif line.startswith("out_time_us="):
            # out_time_us tính bằng microsecond
            try:
                out_us = int(line.split("=")[1].strip())
                current_time_sec = out_us / 1_000_000.0
                if total_duration_sec > 0:
                    percent = min(max((current_time_sec / total_duration_sec) * 100.0, 0.0), 99.9)
                    pbar.n = int(percent)
                    pbar.set_postfix_str(f"fps={current_fps}, speed={current_speed}, {current_time_sec:.1f}s/{total_duration_sec:.1f}s")
                    pbar.refresh()

                    # Cập nhật GUI mỗi 0.5s
                    now = time.time()
                    if now - last_update_time > 0.5:
                        last_update_time = now
                        if progress_callback:
                            progress_callback(percent, f"Đang render: {percent:.1f}% (fps: {current_fps}, speed: {current_speed})")
            except Exception:
                pass
        elif line == "progress=end":
            pbar.n = 100
            pbar.set_postfix_str("Hoàn tất 100%")
            pbar.refresh()

    proc.wait()
    t_err.join(timeout=1.0)
    pbar.close()

    if proc.returncode != 0:
        err_msg = "".join(stderr_lines)
        raise RuntimeError(f"FFmpeg thực thi thất bại (Exit code {proc.returncode}):\n{err_msg[-600:]}")


class VideoPreprocessor:
    """
    Module tiền xử lý video:
    - Làm chậm tốc độ video xuống 0.70x (PTS & atempo).
    - Làm mờ vùng phụ đề gốc bằng filter boxblur của FFmpeg.
    - Trích xuất audio 16kHz mono chuẩn để đưa vào Whisper.
    """

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.speed_factor = config.speed_factor
        self.blur_config = config.blur_region

    def get_video_info(self, video_path: Path) -> Dict:
        """Lấy thông tin kích thước (width, height), fps, thời lượng video bằng ffprobe"""
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(video_path)
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            probe = json.loads(result.stdout)
            
            video_stream = next(
                (s for s in probe.get("streams", []) if s.get("codec_type") == "video"),
                None
            )
            if not video_stream:
                raise ValueError(f"Không tìm thấy luồng video trong file: {video_path}")

            audio_stream = next(
                (s for s in probe.get("streams", []) if s.get("codec_type") == "audio"),
                None
            )

            width = int(video_stream.get("width", 0))
            height = int(video_stream.get("height", 0))
            duration = float(probe.get("format", {}).get("duration", 0.0))
            if duration <= 0:
                duration = float(video_stream.get("duration", 0.0))

            return {
                "width": width,
                "height": height,
                "duration": duration,
                "has_audio": audio_stream is not None,
                "video_stream": video_stream,
                "audio_stream": audio_stream
            }
        except Exception as e:
            logger.error(f"Lỗi ffprobe: {e}")
            raise RuntimeError(f"ffprobe thất bại: {e}") from e

    def calculate_blur_box(self, width: int, height: int) -> Tuple[int, int, int, int]:
        """Tính toán tọa độ pixel (x, y, w, h) cho vùng làm mờ phụ đề chuẩn chẵn (divisible by 2)"""
        b = self.blur_config
        w = b.width if b.width is not None else width
        h = b.height if b.height is not None else int(height * b.height_ratio)
        x = b.x if b.x is not None else int((width - w) / 2)
        y = b.y if b.y is not None else int(height * b.y_ratio)

        # Đảm bảo chia hết cho 2 để chuẩn hóa tương thích YUV420p & libx264
        x = max(0, min(int(x), width - 2)) // 2 * 2
        y = max(0, min(int(y), height - 2)) // 2 * 2
        w = max(2, min(int(w), width - x)) // 2 * 2
        h = max(2, min(int(h), height - y)) // 2 * 2

        return x, y, w, h

    def extract_audio_for_stt(
        self,
        input_video: Path,
        output_audio: Path
    ) -> float:
        """
        Trích xuất và làm chậm âm thanh siêu tốc mà KHÔNG CẦN RENDER VIDEO (mất 1-3 giây thay vì 2 phút).
        :return: target_duration_sec (thời lượng video sau khi làm chậm)
        """
        input_video = Path(input_video).resolve()
        output_audio = Path(output_audio).resolve()
        output_audio.parent.mkdir(parents=True, exist_ok=True)

        info = self.get_video_info(input_video)
        duration = info["duration"]
        has_audio = info.get("has_audio", True)
        target_duration = duration / self.speed_factor if self.speed_factor > 0 else duration

        logger.info(
            f"[Bước 2.1 Siêu Tốc] Trích xuất audio không cần render video (Thời lượng gốc: {duration:.1f}s -> Sau chậm: {target_duration:.1f}s)..."
        )

        if has_audio:
            cmd = [
                "ffmpeg", "-y",
                "-i", str(input_video),
                "-vn",
                "-filter:a", f"atempo={self.speed_factor:.4f}",
                "-acodec", "pcm_s16le",
                "-ar", "16000",
                "-ac", "1",
                str(output_audio)
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-f", "lavfi",
                "-i", "anullsrc=r=16000:cl=mono",
                "-t", f"{target_duration:.2f}",
                "-acodec", "pcm_s16le",
                str(output_audio)
            ]

        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            logger.warning(f"Lỗi khi trích xuất audio siêu tốc: {res.stderr[-300:]}")

        return target_duration

    def process(
        self,
        input_video: Path,
        output_video: Path,
        extracted_audio: Path,
        progress_callback: Optional[Callable[[float, str], None]] = None
    ) -> Tuple[Path, Path]:
        """Thực hiện giảm tốc độ 0.70x, làm mờ phụ đề gốc và trích xuất audio"""
        input_video = Path(input_video).resolve()
        output_video = Path(output_video).resolve()
        extracted_audio = Path(extracted_audio).resolve()
        output_video.parent.mkdir(parents=True, exist_ok=True)
        extracted_audio.parent.mkdir(parents=True, exist_ok=True)

        info = self.get_video_info(input_video)
        width, height = info["width"], info["height"]
        duration = info["duration"]
        has_audio = info.get("has_audio", True)
        target_duration = duration / self.speed_factor if self.speed_factor > 0 else duration

        logger.info(
            f"Thông số video: {width}x{height} | Có audio: {has_audio} | Thời lượng gốc: {duration:.2f}s "
            f"-> Sau khi giảm {self.speed_factor}x: ~{target_duration:.2f}s ({target_duration/60:.1f} phút)"
        )

        pts_mult = 1.0 / self.speed_factor
        x, y, w, h = self.calculate_blur_box(width, height)
        power = self.blur_config.blur_power
        safe_power = max(1, min(power, min(w, h) // 4, 25))

        logger.info(f"Vùng làm mờ phụ đề (Bounding Box): x={x}, y={y}, w={w}, h={h}")

        if self.blur_config.enabled and w >= 4 and h >= 4:
            if has_audio:
                filter_complex = (
                    f"[0:v]setpts={pts_mult:.6f}*PTS,format=yuv420p,split=2[v_speed][v_crop];"
                    f"[v_crop]crop={w}:{h}:{x}:{y},boxblur={safe_power}:5[v_blurred];"
                    f"[v_speed][v_blurred]overlay={x}:{y}[v_out];"
                    f"[0:a]atempo={self.speed_factor:.4f},aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[a_out]"
                )
            else:
                filter_complex = (
                    f"[0:v]setpts={pts_mult:.6f}*PTS,format=yuv420p,split=2[v_speed][v_crop];"
                    f"[v_crop]crop={w}:{h}:{x}:{y},boxblur={safe_power}:5[v_blurred];"
                    f"[v_speed][v_blurred]overlay={x}:{y}[v_out];"
                    f"anullsrc=r=44100:cl=stereo,atrim=duration={target_duration:.2f}[a_out]"
                )
        else:
            if has_audio:
                filter_complex = (
                    f"[0:v]setpts={pts_mult:.6f}*PTS,format=yuv420p[v_out];"
                    f"[0:a]atempo={self.speed_factor:.4f},aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[a_out]"
                )
            else:
                filter_complex = (
                    f"[0:v]setpts={pts_mult:.6f}*PTS,format=yuv420p[v_out];"
                    f"anullsrc=r=44100:cl=stereo,atrim=duration={target_duration:.2f}[a_out]"
                )

        preset = "veryfast" if self.config.video_preset in ["medium", "slow"] else self.config.video_preset
        crf = str(min(self.config.video_crf, 20))

        cmd_video = [
            "ffmpeg", "-y",
            "-i", str(input_video),
            "-filter_complex", filter_complex,
            "-map", "[v_out]",
            "-map", "[a_out]",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", preset,
            "-crf", crf,
            "-c:a", "aac",
            "-b:a", "192k",
            str(output_video)
        ]

        logger.info(f"[Bước 2.1] Bắt đầu render video làm chậm và làm mờ (Thời lượng đích: {target_duration:.1f}s)...")
        run_ffmpeg_with_progress(
            cmd=cmd_video,
            total_duration_sec=target_duration,
            desc="[Bước 2.1] Tiền xử lý (0.70x & Blur)",
            progress_callback=progress_callback
        )

        # Trích xuất audio 16kHz mono cho Whisper
        logger.info("[Bước 2.2] Đang trích xuất file audio cho Whisper AI...")
        cmd_audio = [
            "ffmpeg", "-y",
            "-i", str(output_video),
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            str(extracted_audio)
        ]
        res = subprocess.run(cmd_audio, capture_output=True, text=True)
        if res.returncode != 0:
            logger.warning(f"Lệnh trích xuất audio trả về lỗi: {res.stderr[-200:]}")

        logger.info(f"Hoàn thành tiền xử lý: Video -> {output_video.name}, Audio -> {extracted_audio.name}")
        return output_video, extracted_audio
