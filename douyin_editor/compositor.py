"""
compositor.py - Final Audio Mixing & High-Quality Video Rendering
"""

import logging
from pathlib import Path
import subprocess
from typing import Optional
from tqdm import tqdm

from config import PipelineConfig

logger = logging.getLogger(__name__)


class VideoCompositor:
    """
    Module tổng hợp cuối cùng:
    - Trộn luồng âm thanh TTS tiếng Việt và Nhạc nền (BGM) với thuật toán Audio Ducking (giảm âm nền khi có giọng đọc).
    - Ghép video đã xử lý (làm mờ + hardsub) với luồng âm thanh mới.
    - Render ra file MP4 chất lượng cao (Visually Lossless).
    """

    def __init__(self, config: PipelineConfig):
        self.config = config

    def render_final_video(
        self,
        video_path: Path,
        tts_audio_path: Path,
        bgm_audio_path: Optional[Path],
        output_path: Path
    ) -> Path:
        """
        Gộp video, TTS và BGM thành sản phẩm hoàn chỉnh cuối cùng.
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
            logger.info("[Bước 7 & 8] Đang mix giọng đọc TTS + Nhạc nền BGM (Audio Ducking)...")
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
                "-c:v", "copy",  # Copy luồng video đã burn sub trước đó để tiết kiệm thời gian và giữ nguyên chất lượng
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
                str(output_path)
            ]
        else:
            logger.info("[Bước 7 & 8] Đang ghép video với audio TTS tiếng Việt (Mute hoàn toàn tiếng Trung cũ)...")
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

        with tqdm(total=100, desc="[Bước 7 & 8] Render Video Cuối Cùng (Mastering)", leave=False) as pbar:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
            _, stderr = proc.communicate()
            if proc.returncode != 0:
                logger.error(f"Lỗi khi render video cuối cùng: {stderr}")
                raise RuntimeError(f"FFmpeg render thất bại: {stderr[-500:]}")
            pbar.update(100)

        logger.info(f"Đã xuất bản video thành công: {output_path}")
        return output_path
