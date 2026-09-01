"""
vocal_separator.py - High-Performance AI Vocal & Instrumental Separator (UVR MDX-Net ONNX)
Tách giọng nói (Vocals) và Nhạc nền (Instrumental / BGM) bằng mô hình Deep Learning UVR MDX-Net,
hỗ trợ tăng tốc SciPy PocketFFT đa luồng, Zero-copy buffer, xuất file MP3 320kbps và làm chậm 0.70x.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Callable, Dict, Optional, Tuple, Any, List
import urllib.request

import numpy as np
import onnxruntime as ort
import scipy.fft as sfft

# Tự động nạp static_ffmpeg nếu có
try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
except Exception:
    pass

logger = logging.getLogger(__name__)

# Danh mục mô hình UVR MDX-Net ONNX
MODELS_DATA = {
    "UVR-MDX-NET-Inst_HQ_3": {
        "filename": "UVR-MDX-NET-Inst_HQ_3.onnx",
        "url": "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/UVR-MDX-NET-Inst_HQ_3.onnx",
        "dim_f": 3072,
        "dim_t": 256,
        "n_fft": 6144,
        "hop_length": 1024,
        "sample_rate": 44100,
        "compensate": 1.035,
        "target": "instrumental",
        "name_vi": "MDX-Net Inst HQ 3 (Chuẩn - Khuyên dùng cho Nhạc Nền)",
        "description": "Tối ưu trọn vẹn dải âm nhạc nền, bass, drums và synths."
    },
    "UVR_MDXNET_KIM_Vocal_2": {
        "filename": "UVR_MDXNET_KIM_Vocal_2.onnx",
        "url": "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/UVR_MDXNET_KIM_Vocal_2.onnx",
        "dim_f": 3072,
        "dim_t": 256,
        "n_fft": 6144,
        "hop_length": 1024,
        "sample_rate": 44100,
        "compensate": 1.035,
        "target": "vocals",
        "name_vi": "MDX-Net Kim Vocal 2 (Lọc Giọng Nói)",
        "description": "Chuyên bóc tách giọng nói, loại bỏ tạp âm và nhạc nền."
    }
}

SPEED_PRESETS = {
    "turbo": 0.0,      # 0% Overlap: Siêu tốc ~2.4x real-time
    "fast": 0.25,      # 25% Overlap: Nhanh
    "balanced": 0.50,  # 50% Overlap: Cân bằng
    "hq": 0.75         # 75% Overlap: Chất lượng cao
}


def get_ffmpeg_cmd() -> str:
    return "ffmpeg"


def download_model(
    model_key: str,
    models_dir: Path | str = "models",
    progress_callback: Optional[Callable[[float, str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None
) -> str:
    """Tải ONNX model từ repository nếu chưa có trên máy cục bộ."""
    if model_key not in MODELS_DATA:
        raise ValueError(f"Mô hình không hợp lệ: {model_key}")

    models_dir = Path(models_dir).resolve()
    models_dir.mkdir(parents=True, exist_ok=True)
    info = MODELS_DATA[model_key]
    dest_path = models_dir / info["filename"]

    # Kiểm tra file mô hình sẵn có
    if dest_path.exists() and dest_path.stat().st_size > 10_000_000:
        return str(dest_path)

    # Kiểm tra ở thư mục cha / models
    parent_model = models_dir.parent / "models" / info["filename"]
    if parent_model.exists() and parent_model.stat().st_size > 10_000_000:
        return str(parent_model)

    # Kiểm tra ở tachgiong/models
    alt_tachgiong = models_dir.parent / "tachgiong" / "models" / info["filename"]
    if alt_tachgiong.exists() and alt_tachgiong.stat().st_size > 10_000_000:
        return str(alt_tachgiong)

    temp_path = str(dest_path) + ".tmp"
    url = info["url"]

    if progress_callback:
        progress_callback(0.0, f"Đang tải mô hình AI ({info['filename']})...")

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp:
        total_size = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        block_size = 1024 * 1024  # 1MB chunks

        with open(temp_path, "wb") as f:
            while True:
                if cancel_check and cancel_check():
                    f.close()
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                    raise RuntimeError("Quá trình tải mô hình AI đã bị hủy.")

                chunk = resp.read(block_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)

                if total_size > 0 and progress_callback:
                    pct = downloaded / total_size
                    mb_down = downloaded / (1024 * 1024)
                    mb_tot = total_size / (1024 * 1024)
                    progress_callback(pct, f"Đang tải AI Model: {mb_down:.1f}/{mb_tot:.1f} MB ({pct*100:.1f}%)")

    if dest_path.exists():
        dest_path.unlink()
    os.rename(temp_path, str(dest_path))

    if progress_callback:
        progress_callback(1.0, "Tải mô hình AI thành công!")

    return str(dest_path)


def load_audio_waveform(filepath: str | Path, sample_rate: int = 44100) -> Tuple[np.ndarray, float]:
    """Đọc audio/video ra mảng numpy stereo float32 (2, n_samples) chuẩn 44.1kHz."""
    filepath = Path(filepath).resolve()
    if not filepath.exists():
        raise FileNotFoundError(f"Không tìm thấy file âm thanh/video: {filepath}")

    cmd = [
        get_ffmpeg_cmd(),
        "-v", "error",
        "-threads", "0",
        "-i", str(filepath),
        "-vn",
        "-ar", str(sample_rate),
        "-ac", "2",
        "-f", "f32le",
        "-"
    ]

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        raw_audio, err = proc.communicate()
    except FileNotFoundError:
        import soundfile as sf
        data, sr = sf.read(str(filepath), dtype="float32")
        if data.ndim == 1:
            data = np.stack([data, data], axis=0)
        else:
            data = data.T
        duration = data.shape[1] / sr
        return data, duration

    if proc.returncode != 0:
        err_msg = err.decode("utf-8", errors="ignore")
        raise RuntimeError(f"Lỗi khi đọc file bằng FFmpeg: {err_msg}")

    if len(raw_audio) == 0:
        raise ValueError(f"File không chứa luồng âm thanh hợp lệ: {filepath}")

    audio = np.frombuffer(raw_audio, dtype=np.float32).reshape(-1, 2).T
    duration = audio.shape[1] / sample_rate
    return audio, duration


def save_audio_waveform(
    waveform: np.ndarray,
    output_filepath: str | Path,
    sample_rate: int = 44100,
    format_type: str = "mp3",
    bitrate: str = "320k"
) -> Path:
    """Lưu waveform (2, n_samples) ra file MP3 320k hoặc WAV chuẩn phòng thu."""
    output_filepath = Path(output_filepath).resolve()
    output_filepath.parent.mkdir(parents=True, exist_ok=True)
    ext = format_type.lower().strip(".")
    final_output_path = output_filepath.with_suffix(f".{ext}")

    waveform = np.clip(waveform, -1.0, 1.0)
    interleaved = waveform.T.astype(np.float32)

    if ext == "wav":
        import soundfile as sf
        sf.write(str(final_output_path), interleaved, sample_rate, subtype="PCM_24")
        return final_output_path
    elif ext == "flac":
        import soundfile as sf
        sf.write(str(final_output_path), interleaved, sample_rate, format="FLAC")
        return final_output_path
    else:
        codec_args = []
        if ext == "mp3":
            codec_args = ["-c:a", "libmp3lame", "-b:a", bitrate]
        elif ext in ["m4a", "aac"]:
            codec_args = ["-c:a", "aac", "-b:a", bitrate]
        else:
            codec_args = ["-b:a", bitrate]

        cmd = [
            get_ffmpeg_cmd(),
            "-y",
            "-v", "error",
            "-threads", "0",
            "-f", "f32le",
            "-ar", str(sample_rate),
            "-ac", "2",
            "-i", "pipe:0",
            *codec_args,
            str(final_output_path)
        ]

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        _, err = proc.communicate(interleaved.tobytes())
        if proc.returncode != 0:
            err_msg = err.decode("utf-8", errors="ignore")
            # Fallback soundfile WAV nếu codec mp3 gặp lỗi
            import soundfile as sf
            wav_fallback = final_output_path.with_suffix(".wav")
            sf.write(str(wav_fallback), interleaved, sample_rate)
            return wav_fallback

        return final_output_path


def stft_numpy(waveform: np.ndarray, n_fft: int = 6144, hop_length: int = 1024) -> np.ndarray:
    """STFT đa luồng tăng tốc với SciPy PocketFFT C/C++."""
    pad_len = n_fft // 2
    padded = np.pad(waveform, ((0, 0), (pad_len, pad_len)), mode="reflect")
    window = np.hanning(n_fft).astype(np.float32)
    n_frames = 1 + (padded.shape[1] - n_fft) // hop_length

    frames = np.lib.stride_tricks.as_strided(
        padded,
        shape=(2, n_frames, n_fft),
        strides=(padded.strides[0], padded.strides[1] * hop_length, padded.strides[1])
    )
    windowed = frames * window
    spec = sfft.rfft(windowed, n=n_fft, axis=-1, workers=-1)
    return np.ascontiguousarray(np.transpose(spec, (0, 2, 1)), dtype=np.complex64)


def istft_numpy(
    spec: np.ndarray,
    n_fft: int = 6144,
    hop_length: int = 1024,
    length: Optional[int] = None
) -> np.ndarray:
    """Inverse STFT đa luồng tăng tốc với SciPy PocketFFT."""
    spec = np.transpose(spec, (0, 2, 1))
    window = np.hanning(n_fft).astype(np.float32)
    n_frames = spec.shape[1]

    frames = sfft.irfft(spec, n=n_fft, axis=-1, workers=-1) * window
    expected_len = (n_frames - 1) * hop_length + n_fft
    out = np.zeros((2, expected_len), dtype=np.float32)
    win_sum = np.zeros(expected_len, dtype=np.float32)
    win_sq = window ** 2

    for i in range(n_frames):
        st = i * hop_length
        out[:, st:st + n_fft] += frames[:, i, :]
        win_sum[st:st + n_fft] += win_sq

    win_sum = np.where(win_sum > 1e-8, win_sum, 1.0)
    out /= win_sum

    pad_len = n_fft // 2
    out = out[:, pad_len:]
    if length is not None:
        out = out[:, :length]
    return out


class VocalSeparatorEngine:
    """
    AI Vocal & Instrumental Separation Engine sử dụng ONNX Runtime & MDX-Net.
    Tối ưu hóa đa luồng, Zero-Copy buffer, SciPy PocketFFT và Phân đoạn Overlap-Add chống tràn RAM.
    """

    def __init__(self, models_dir: Path | str = "models", cpu_threads: Optional[int] = None):
        self.models_dir = Path(models_dir).resolve()
        self.cpu_threads = cpu_threads or max(2, os.cpu_count() or 4)
        self.current_model_key: Optional[str] = None
        self.session: Optional[ort.InferenceSession] = None
        self.model_info: Optional[Dict[str, Any]] = None

    def load_model(
        self,
        model_key: str = "UVR-MDX-NET-Inst_HQ_3",
        progress_callback: Optional[Callable[[float, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None
    ) -> None:
        """Nạp mô hình ONNX vào bộ nhớ RAM với tối ưu hóa đa luồng."""
        if self.current_model_key == model_key and self.session is not None:
            return

        model_path = download_model(
            model_key=model_key,
            models_dir=self.models_dir,
            progress_callback=progress_callback,
            cancel_check=cancel_check
        )

        if progress_callback:
            progress_callback(0.95, f"Đang nạp mô hình AI {model_key}...")

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = self.cpu_threads
        opts.inter_op_num_threads = 1
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        opts.enable_cpu_mem_arena = True
        opts.enable_mem_pattern = True

        available_providers = ort.get_available_providers()
        preferred_providers = []
        if "CUDAExecutionProvider" in available_providers:
            preferred_providers.append("CUDAExecutionProvider")
        if "DmlExecutionProvider" in available_providers:
            preferred_providers.append("DmlExecutionProvider")
        preferred_providers.append("CPUExecutionProvider")

        self.session = ort.InferenceSession(model_path, sess_options=opts, providers=preferred_providers)
        self.current_model_key = model_key
        self.model_info = MODELS_DATA[model_key]

        if progress_callback:
            progress_callback(1.0, f"Mô hình {model_key} đã sẵn sàng ({self.cpu_threads} luồng CPU)!")

    def _separate_single_segment(
        self,
        seg_mix: np.ndarray,
        overlap: float = 0.0,
        batch_size: int = 1,
        cancel_check: Optional[Callable[[], bool]] = None
    ) -> np.ndarray:
        """Tách 1 phân đoạn waveform ngắn (<= 60s) bằng mô hình ONNX."""
        dim_f = self.model_info["dim_f"]
        dim_t = self.model_info["dim_t"]
        n_fft = self.model_info["n_fft"]
        hop_length = self.model_info["hop_length"]
        compensate = self.model_info["compensate"]

        orig_len = seg_mix.shape[1]
        spec = stft_numpy(seg_mix, n_fft=n_fft, hop_length=hop_length)
        n_frames = spec.shape[2]

        if n_frames < dim_t:
            pad_frames = dim_t - n_frames
            spec = np.pad(spec, ((0, 0), (0, 0), (0, pad_frames)), mode="constant")
            n_frames = dim_t

        spec_f = spec[:, :dim_f, :]

        step = max(1, int(dim_t * (1.0 - overlap)))
        starts = list(range(0, n_frames - dim_t + 1, step))
        if len(starts) == 0 or starts[-1] + dim_t < n_frames:
            starts.append(n_frames - dim_t)

        total_chunks = len(starts)
        accum_spec = np.zeros_like(spec_f, dtype=np.complex64)
        weight = np.zeros((1, 1, n_frames), dtype=np.float32)

        chunk_win = np.ones((1, 1, dim_t), dtype=np.float32) if overlap <= 0.01 else np.hanning(dim_t).astype(np.float32)[np.newaxis, np.newaxis, :]

        b_size = max(1, int(batch_size))
        inp_batch = np.empty((b_size, 4, dim_f, dim_t), dtype=np.float32)

        for i in range(0, total_chunks, b_size):
            if cancel_check and cancel_check():
                raise RuntimeError("Quá trình tách âm AI đã bị hủy.")

            cur_starts = starts[i : i + b_size]
            cur_batch_len = len(cur_starts)

            for b_idx, st in enumerate(cur_starts):
                c = spec_f[:, :, st : st + dim_t]
                inp_batch[b_idx, 0] = c[0].real
                inp_batch[b_idx, 1] = c[0].imag
                inp_batch[b_idx, 2] = c[1].real
                inp_batch[b_idx, 3] = c[1].imag

            if cur_batch_len == b_size:
                out_batch = self.session.run(None, {"input": inp_batch})[0]
            else:
                out_batch = self.session.run(None, {"input": inp_batch[:cur_batch_len]})[0]

            for b_idx, st in enumerate(cur_starts):
                out = out_batch[b_idx]
                out_l = out[0] + 1j * out[1]
                out_r = out[2] + 1j * out[3]

                accum_spec[0, :, st : st + dim_t] += out_l * chunk_win[0, 0]
                accum_spec[1, :, st : st + dim_t] += out_r * chunk_win[0, 0]
                weight[:, :, st : st + dim_t] += chunk_win

        accum_spec /= np.where(weight > 1e-6, weight, 1.0)
        full_out_spec = np.pad(accum_spec, ((0, 0), (0, 1), (0, 0)), mode="constant")
        target_wav = istft_numpy(full_out_spec, n_fft=n_fft, hop_length=hop_length, length=orig_len) * compensate
        return target_wav

    def separate_waveform(
        self,
        mix: np.ndarray,
        overlap: float = 0.0,
        batch_size: int = 1,
        segment_duration: float = 60.0,
        crossfade_duration: float = 2.0,
        progress_callback: Optional[Callable[[float, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None
    ) -> Dict[str, np.ndarray]:
        """
        Tách waveform stereo thành dictionary {'instrumental', 'vocals'}.
        Tự động phân đoạn (Segment Chunking + Overlap-Add Crossfade) để đảm bảo không bị tràn RAM (OOM)
        dù file âm thanh dài hàng chục phút đến vài giờ.
        """
        if self.session is None or self.model_info is None:
            raise RuntimeError("Mô hình AI chưa được tải. Hãy gọi load_model() trước.")

        target = self.model_info["target"]
        orig_len = mix.shape[1]
        sample_rate = 44100
        total_duration = orig_len / sample_rate

        segment_samples = int(segment_duration * sample_rate)
        overlap_samples = int(crossfade_duration * sample_rate)
        step_samples = max(sample_rate, segment_samples - overlap_samples)

        # Nếu audio ngắn hơn hoặc bằng 1 segment -> xử lý trực tiếp đơn segment
        if orig_len <= segment_samples:
            if progress_callback:
                progress_callback(0.10, f"Đang phân tích và tách âm AI ({total_duration:.1f}s)...")

            target_wav = self._separate_single_segment(
                seg_mix=mix,
                overlap=overlap,
                batch_size=batch_size,
                cancel_check=cancel_check
            )

            if target == "instrumental":
                instrumental = target_wav
                vocals = mix - instrumental
            else:
                vocals = target_wav
                instrumental = mix - vocals

            if progress_callback:
                progress_callback(1.0, "Hoàn tất phân tách các track âm thanh!")

            return {
                "instrumental": instrumental,
                "vocals": vocals
            }

        # Nếu audio dài -> phân đoạn thông minh với Overlap-Add Crossfade chống tràn RAM
        seg_starts = []
        pos = 0
        while pos < orig_len:
            seg_starts.append(pos)
            if pos + segment_samples >= orig_len:
                break
            pos += step_samples

        total_segs = len(seg_starts)
        target_full = np.zeros_like(mix, dtype=np.float32)
        weight_full = np.zeros((1, orig_len), dtype=np.float32)

        for seg_idx, st in enumerate(seg_starts):
            if cancel_check and cancel_check():
                raise RuntimeError("Quá trình tách âm AI đã bị hủy.")

            end = min(orig_len, st + segment_samples)
            seg_len = end - st
            seg_mix = mix[:, st:end]

            if progress_callback:
                pct = 0.05 + 0.90 * (seg_idx / total_segs)
                cur_sec = min(total_duration, end / sample_rate)
                msg = f"Đang tách AI UVR... [Đoạn {seg_idx + 1}/{total_segs}] ({cur_sec:.1f}s/{total_duration:.1f}s)"
                progress_callback(pct, msg)

            seg_target = self._separate_single_segment(
                seg_mix=seg_mix,
                overlap=overlap,
                batch_size=batch_size,
                cancel_check=cancel_check
            )

            # Tạo cửa sổ trọng số crossfade mượt mà
            seg_weight = np.ones((1, seg_len), dtype=np.float32)
            if st > 0:
                fade_in_len = min(overlap_samples, seg_len)
                seg_weight[0, :fade_in_len] = np.linspace(0.0, 1.0, fade_in_len, dtype=np.float32)
            if end < orig_len:
                fade_out_len = min(overlap_samples, seg_len)
                seg_weight[0, -fade_out_len:] = np.linspace(1.0, 0.0, fade_out_len, dtype=np.float32)

            target_full[:, st:end] += seg_target * seg_weight
            weight_full[:, st:end] += seg_weight

        target_full /= np.maximum(weight_full, 1e-8)

        if target == "instrumental":
            instrumental = target_full
            vocals = mix - instrumental
        else:
            vocals = target_full
            instrumental = mix - vocals

        if progress_callback:
            progress_callback(1.0, "Hoàn tất phân tách các track âm thanh!")

        return {
            "instrumental": instrumental,
            "vocals": vocals
        }


class VocalSeparator:
    """
    Module tích hợp cho Douyin Auto Pipeline:
    - Tách AI MDX-Net: Xuất BGM nhạc nền gốc ra file MP3 320kbps.
    - Làm chậm BGM về 0.70x (bằng FFmpeg atempo), giữ nguyên 100% âm lượng gốc.
    - Làm chậm Vocals tiếng Trung về 0.70x (16kHz mono) cho Whisper STT.
    """

    def __init__(self, config: Any):
        self.config = config
        models_dir = Path(__file__).parent / "models"
        self.engine = VocalSeparatorEngine(models_dir=models_dir)

    def slowdown_audio(
        self,
        input_audio: Path,
        output_audio: Path,
        speed_factor: float = 0.70,
        sample_rate: int = 44100,
        channels: int = 2
    ) -> Path:
        """
        Làm chậm âm thanh chính xác bằng FFmpeg atempo, giữ nguyên cao độ (pitch) và âm lượng 100%.
        """
        input_audio = Path(input_audio).resolve()
        output_audio = Path(output_audio).resolve()
        output_audio.parent.mkdir(parents=True, exist_ok=True)

        if speed_factor <= 0:
            speed_factor = 0.70

        # FFmpeg atempo chỉ nhận giá trị từ 0.5 đến 2.0. Nếu ngoài dải cần ghép nhiều filter.
        if 0.5 <= speed_factor <= 2.0:
            filter_str = f"atempo={speed_factor:.4f}"
        else:
            factors = []
            cur = speed_factor
            while cur < 0.5:
                factors.append("atempo=0.5")
                cur /= 0.5
            while cur > 2.0:
                factors.append("atempo=2.0")
                cur /= 2.0
            factors.append(f"atempo={cur:.4f}")
            filter_str = ",".join(factors)

        acodec = "pcm_s16le" if output_audio.suffix.lower() == ".wav" else "libmp3lame"
        extra_args = ["-b:a", "320k"] if acodec == "libmp3lame" else []

        cmd = [
            get_ffmpeg_cmd(),
            "-y",
            "-v", "error",
            "-threads", "0",
            "-i", str(input_audio),
            "-filter:a", filter_str,
            "-ar", str(sample_rate),
            "-ac", str(channels),
            "-acodec", acodec,
            *extra_args,
            str(output_audio)
        ]

        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            logger.warning(f"Lỗi khi làm chậm audio ({res.stderr}). Tạo bản copy...")
            shutil.copyfile(input_audio, output_audio)

        return output_audio

    def process_pipeline_audio(
        self,
        raw_video_path: Path,
        session_work_dir: Path,
        video_id: str,
        speed_factor: float = 0.70,
        progress_callback: Optional[Callable[[float, str], None]] = None
    ) -> Tuple[Path, Path, Path]:
        """
        Quy trình chuẩn cho Douyin Editor:
        1. Tách nhạc nền và giọng nói từ video gốc (1.0x).
        2. Lưu track nhạc nền gốc ra MP3 320k: `[video_id]_bgm_original.mp3`.
        3. Làm chậm BGM về 0.70x (stereo 44.1kHz): `[video_id]_bgm_0.70x.wav` (Giữ nguyên 100% âm lượng gốc).
        4. Làm chậm Vocals về 0.70x (mono 16kHz): `[video_id]_vocals_0.70x_16k.wav` cho Whisper STT.

        :return: (bgm_original_mp3, bgm_slowed_audio, vocals_slowed_audio)
        """
        raw_video_path = Path(raw_video_path).resolve()
        session_work_dir = Path(session_work_dir).resolve()
        session_work_dir.mkdir(parents=True, exist_ok=True)

        bgm_original_mp3 = session_work_dir / f"{video_id}_bgm_original.mp3"
        bgm_slowed_audio = session_work_dir / f"{video_id}_bgm_slowed.wav"
        vocals_original_wav = session_work_dir / f"{video_id}_vocals_original.wav"
        vocals_slowed_audio = session_work_dir / f"{video_id}_vocals_slowed_16k.wav"

        speed_key = getattr(self.config, "separation_speed", "turbo")
        overlap = SPEED_PRESETS.get(speed_key, 0.0)
        model_name = getattr(self.config, "vocal_model_name", "UVR-MDX-NET-Inst_HQ_3")

        logger.info(f"[MDX-Net AI] Bắt đầu tách giọng & BGM từ video gốc ({model_name}, Speed: {speed_key}, Overlap: {overlap*100:.0f}%)...")

        # 1. Nạp mô hình AI
        self.engine.load_model(
            model_key=model_name,
            progress_callback=lambda p, msg: progress_callback(p * 0.20, f"[AI Model] {msg}") if progress_callback else None
        )

        # 2. Đọc waveform gốc
        if progress_callback:
            progress_callback(0.22, "Đang đọc luồng âm thanh gốc từ video...")
        mix_audio, duration = load_audio_waveform(raw_video_path, sample_rate=44100)

        # 3. Phân tách AI
        def on_sep_prog(p: float, msg: str):
            if progress_callback:
                progress_callback(0.25 + p * 0.55, f"[Tách Âm AI] {msg}")

        stems = self.engine.separate_waveform(
            mix=mix_audio,
            overlap=overlap,
            batch_size=1,
            progress_callback=on_sep_prog
        )

        # 4 & 5. Xuất file và làm chậm BGM & Vocals SONG SONG bằng ThreadPoolExecutor
        if progress_callback:
            progress_callback(0.85, "Đang xử lý & làm chậm track BGM và Vocals song song...")

        def _process_bgm_track():
            save_audio_waveform(
                stems["instrumental"],
                output_filepath=bgm_original_mp3,
                sample_rate=44100,
                format_type="mp3",
                bitrate="320k"
            )
            self.slowdown_audio(
                input_audio=bgm_original_mp3,
                output_audio=bgm_slowed_audio,
                speed_factor=speed_factor,
                sample_rate=44100,
                channels=2
            )
            logger.info(f"Đã tạo track BGM {speed_factor:.2f}x: {bgm_slowed_audio}")

        def _process_vocals_track():
            save_audio_waveform(
                stems["vocals"],
                output_filepath=vocals_original_wav,
                sample_rate=44100,
                format_type="wav"
            )
            self.slowdown_audio(
                input_audio=vocals_original_wav,
                output_audio=vocals_slowed_audio,
                speed_factor=speed_factor,
                sample_rate=16000,
                channels=1
            )
            logger.info(f"Đã tạo track Vocals {speed_factor:.2f}x cho Whisper: {vocals_slowed_audio}")

        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as executor:
            fut_bgm = executor.submit(_process_bgm_track)
            fut_voc = executor.submit(_process_vocals_track)
            fut_bgm.result()
            fut_voc.result()

        if progress_callback:
            progress_callback(1.0, "Hoàn tất tách âm thanh & làm chậm 0.70x!")

        return bgm_original_mp3, bgm_slowed_audio, vocals_slowed_audio

    def process(self, audio_path: Path, output_bgm_path: Path) -> Optional[Path]:
        """Tương thích ngược với interface cũ."""
        if not getattr(self.config, "keep_bgm", True):
            return None
        try:
            self.engine.load_model()
            mix, _ = load_audio_waveform(audio_path)
            stems = self.engine.separate_waveform(mix, overlap=0.0)
            save_audio_waveform(stems["instrumental"], output_bgm_path, format_type="wav")
            return output_bgm_path
        except Exception as e:
            logger.warning(f"Lỗi khi tách âm thanh ({e}). Bỏ qua...")
            return None
