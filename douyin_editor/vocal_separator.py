"""
vocal_separator.py - Vocal Separation and Background Music (BGM) Isolation
"""

import logging
from pathlib import Path
import shutil
import subprocess
from typing import Optional
from tqdm import tqdm

from config import PipelineConfig

logger = logging.getLogger(__name__)


class VocalSeparator:
    """
    Module tách giọng nói gốc và giữ lại nhạc nền (BGM) / hiệu ứng âm thanh.
    Sử dụng Demucs (Hybrid Transformer) hoặc fallback thuật toán FFmpeg Center-Channel Cancellation.
    """

    def __init__(self, config: PipelineConfig):
        self.config = config

    def _is_demucs_available(self) -> bool:
        """Kiểm tra xem Demucs đã được cài đặt trong môi trường chưa"""
        try:
            import demucs
            return True
        except ImportError:
            return False

    def separate_with_demucs(self, audio_path: Path, output_bgm_path: Path) -> Path:
        """
        Sử dụng Demucs AI để tách giọng nói và lấy kênh BGM (no_vocals / other + bass + drums).
        """
        import torch
        from demucs.apply import apply_model
        from demucs.pretrained import get_model
        import torchaudio

        logger.info("[Bước 5] Đang nạp mô hình Demucs để tách giọng nói gốc...")
        device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Sử dụng thiết bị xử lý Demucs: {device.upper()}")

        model = get_model("htdemucs")
        model.to(device)

        wav, sr = torchaudio.load(str(audio_path))
        if sr != model.samplerate:
            resampler = torchaudio.transforms.Resample(sr, model.samplerate)
            wav = resampler(wav)
            sr = model.samplerate

        # Chuẩn hóa về 2 kênh stereo
        if wav.shape[0] == 1:
            wav = wav.repeat(2, 1)

        wav = wav.to(device)
        # wav shape: (channels, samples) -> (batch, channels, samples)
        ref = wav.mean(0)
        wav = (wav - ref.mean()) / ref.std()

        logger.info("[Bước 5] Đang thực hiện tách âm thanh (Vocal vs Background)...")
        with torch.no_grad():
            sources = apply_model(model, wav[None], device=device, progress=True)[0]

        # Model htdemucs trả về 4 nguồn: drums (0), bass (1), other (2), vocals (3)
        # BGM = drums + bass + other (tất cả trừ vocals)
        bgm_tensor = sources[0] + sources[1] + sources[2]
        bgm_tensor = bgm_tensor * ref.std() + ref.mean()

        torchaudio.save(str(output_bgm_path), bgm_tensor.cpu(), sr)
        logger.info(f"Đã tách và lưu nhạc nền BGM: {output_bgm_path}")
        return output_bgm_path

    def separate_with_ffmpeg_fallback(self, audio_path: Path, output_bgm_path: Path) -> Path:
        """
        Thuật toán FFmpeg DSP: Triệt tiêu giọng nói ở kênh giữa (Center-Channel Vocal Cancellation)
        và lọc tần số để giữ lại nhạc nền (BGM) và hiệu ứng âm thanh (SFX) của video gốc.
        """
        logger.info("[Bước 4 Fallback] Tách nhạc nền bằng bộ lọc âm thanh FFmpeg Vocal Cut...")
        filter_str = (
            "stereotools=mlev=0.15:slev=1.35,"
            "highpass=f=80,lowpass=f=15000,"
            "volume=1.2"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", str(audio_path),
            "-af", filter_str,
            "-ar", "44100",
            "-ac", "2",
            str(output_bgm_path)
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            logger.warning(f"Lỗi khi lọc BGM bằng FFmpeg ({res.stderr[:200]}). Dùng bộ lọc pan stereo...")
            cmd2 = [
                "ffmpeg", "-y",
                "-i", str(audio_path),
                "-af", "pan=stereo|c0=c0-0.8*c1|c1=c1-0.8*c0,volume=1.2",
                "-ar", "44100",
                "-ac", "2",
                str(output_bgm_path)
            ]
            subprocess.run(cmd2, capture_output=True, text=True)
        return output_bgm_path

    def process(self, audio_path: Path, output_bgm_path: Path) -> Optional[Path]:
        """
        Tách âm thanh gốc và xử lý BGM.
        - Nếu có file nhạc nền riêng (custom_bgm_path): Sử dụng trực tiếp file nhạc sạch (100% không tiếng Trung).
        - Nếu keep_bgm=True và có Demucs AI: Sử dụng Deep Learning để bóc tách vocal.
        - Nếu không có Demucs AI: Mute hoàn toàn âm thanh gốc để triệt tiêu 100% giọng nói tiếng Trung cũ.
        """
        custom_bgm = getattr(self.config, "custom_bgm_path", None)
        if custom_bgm and Path(custom_bgm).exists():
            logger.info(f"[Bước 4] Sử dụng file nhạc nền BGM tùy chỉnh (sạch 100%): {custom_bgm}")
            return Path(custom_bgm).resolve()

        if not self.config.keep_bgm:
            logger.info("[Bước 4] Đã tắt âm thanh gốc -> Mute hoàn toàn để giọng đọc Tiếng Việt trong trẻo 100%.")
            return None

        audio_path = Path(audio_path).resolve()
        output_bgm_path = Path(output_bgm_path).resolve()
        output_bgm_path.parent.mkdir(parents=True, exist_ok=True)

        with tqdm(total=100, desc="[Bước 4] Tách giọng nói & Giữ BGM", leave=False) as pbar:
            if self._is_demucs_available():
                try:
                    self.separate_with_demucs(audio_path, output_bgm_path)
                    pbar.update(100)
                    return output_bgm_path
                except Exception as e:
                    logger.warning(f"Demucs AI gặp lỗi ({e}). Để tránh lẫn tiếng Trung, hệ thống sẽ tắt âm thanh gốc.")
                    return None
            else:
                logger.info("[Bước 4] Chưa cài đặt Demucs AI -> Mute hoàn toàn âm thanh gốc để loại bỏ 100% tiếng Trung cũ. (Bạn có thể chọn file MP3 riêng để lồng nhạc nền).")
                pbar.update(100)
                return None
