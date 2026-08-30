"""
Audio Source Separation Engine using UVR MDX-Net ONNX Models.
Supports high-quality vocal & instrumental extraction for audio & video files.
Optimized with Multi-threading, Batch Chunk Processing, and Hardware Acceleration.
"""

import os
import sys
import time
import urllib.request
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional, Dict, Any, Tuple, List
import numpy as np
import onnxruntime as ort

# Fix UTF-8 encoding on Windows console
if sys.platform == "win32":
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Ensure static_ffmpeg is loaded if available
try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
except Exception:
    pass


# Default models dictionary
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
        "name_vi": "MDX-Net Kim Vocal 2 (Tối ưu lọc sạch Giọng Nói / Lời Hát)",
        "description": "Chuyên bóc tách giọng nói, loại bỏ tạp âm và nhạc nền."
    },
    "UVR-MDX-NET-Voc_FT": {
        "filename": "UVR-MDX-NET-Voc_FT.onnx",
        "url": "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/UVR-MDX-NET-Voc_FT.onnx",
        "dim_f": 3072,
        "dim_t": 256,
        "n_fft": 6144,
        "hop_length": 1024,
        "sample_rate": 44100,
        "compensate": 1.035,
        "target": "vocals",
        "name_vi": "MDX-Net Voc FT (Tinh chỉnh Giọng Hát)",
        "description": "Mô hình tinh chỉnh bóc tách lời hát mượt mà."
    }
}

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".m4v"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".wma", ".opus"}


def get_ffmpeg_cmd() -> str:
    """Returns ffmpeg executable path."""
    return "ffmpeg"


def is_video_file(filepath: str) -> bool:
    """Checks if file is a video by extension."""
    ext = os.path.splitext(filepath)[1].lower()
    return ext in VIDEO_EXTENSIONS


def download_model(
    model_key: str,
    models_dir: str = "models",
    progress_callback: Optional[Callable[[float, str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None
) -> str:
    """
    Downloads the ONNX model file if not already present locally.
    Returns path to downloaded model file.
    """
    if model_key not in MODELS_DATA:
        raise ValueError(f"Mô hình không hợp lệ: {model_key}")

    os.makedirs(models_dir, exist_ok=True)
    info = MODELS_DATA[model_key]
    dest_path = os.path.join(models_dir, info["filename"])

    # Check local availability
    if os.path.exists(info["filename"]) and os.path.getsize(info["filename"]) > 10_000_000:
        return info["filename"]

    if os.path.exists(dest_path) and os.path.getsize(dest_path) > 10_000_000:
        return dest_path

    temp_path = dest_path + ".tmp"
    url = info["url"]
    
    if progress_callback:
        progress_callback(0.0, f"Đang kết nối tải mô hình AI ({info['filename']})...")

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
                    raise RuntimeError("Quá trình tải mô hình đã bị hủy.")

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

    if os.path.exists(dest_path):
        os.remove(dest_path)
    os.rename(temp_path, dest_path)

    if progress_callback:
        progress_callback(1.0, "Tải mô hình AI thành công!")

    return dest_path


def load_audio_waveform(filepath: str, sample_rate: int = 44100) -> Tuple[np.ndarray, float]:
    """
    Loads audio or video file as stereo float32 waveform (2, n_samples) at target sample rate.
    Uses multi-threaded FFmpeg for universal format support and high performance.
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Không tìm thấy file: {filepath}")

    cmd = [
        get_ffmpeg_cmd(),
        "-v", "error",
        "-threads", "0",
        "-i", filepath,
        "-vn",
        "-ar", str(sample_rate),
        "-ac", "2",
        "-f", "f32le",
        "-"
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        raw_audio, err = proc.communicate()
    except FileNotFoundError:
        # Fallback using soundfile if ffmpeg command is somehow not in PATH
        import soundfile as sf
        data, sr = sf.read(filepath, dtype="float32")
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
    output_filepath: str,
    sample_rate: int = 44100,
    format_type: str = "mp3",
    bitrate: str = "320k"
) -> str:
    """
    Saves waveform (2, n_samples) to target format (mp3, wav, flac, m4a).
    Uses multi-threaded FFmpeg for maximum encoding speed.
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_filepath)), exist_ok=True)
    ext = format_type.lower().strip(".")
    
    # Ensure correct extension in output path
    base_no_ext = os.path.splitext(output_filepath)[0]
    final_output_path = f"{base_no_ext}.{ext}"

    # Clip audio safely between -1.0 and 1.0 to prevent distortion
    waveform = np.clip(waveform, -1.0, 1.0)
    interleaved = waveform.T.astype(np.float32)

    if ext == "wav":
        import soundfile as sf
        sf.write(final_output_path, interleaved, sample_rate, subtype="PCM_24")
        return final_output_path
    elif ext == "flac":
        import soundfile as sf
        sf.write(final_output_path, interleaved, sample_rate, format="FLAC")
        return final_output_path
    else:
        # For MP3, M4A, AAC, OGG: use FFmpeg pipe with multi-threading
        codec_args = []
        if ext == "mp3":
            codec_args = ["-c:a", "libmp3lame", "-b:a", bitrate]
        elif ext in ["m4a", "aac"]:
            codec_args = ["-c:a", "aac", "-b:a", bitrate]
        elif ext == "ogg":
            codec_args = ["-c:a", "libvorbis", "-q:a", "6"]
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
            final_output_path
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
            # Fallback to soundfile WAV if codec failed
            import soundfile as sf
            wav_fallback = f"{base_no_ext}.wav"
            sf.write(wav_fallback, interleaved, sample_rate)
            return wav_fallback

        return final_output_path


def replace_video_audio(
    video_input_path: str,
    new_audio_path: str,
    video_output_path: str,
    bitrate: str = "320k"
) -> str:
    """
    Creates a new video file with the original video stream and replaced audio track.
    Video stream is copied without re-encoding (-c:v copy) for 100% original quality.
    """
    os.makedirs(os.path.dirname(os.path.abspath(video_output_path)), exist_ok=True)
    cmd = [
        get_ffmpeg_cmd(),
        "-y",
        "-v", "error",
        "-threads", "0",
        "-i", video_input_path,
        "-i", new_audio_path,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", bitrate,
        "-shortest",
        video_output_path
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _, err = proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"Lỗi ghép video: {err.decode('utf-8', errors='ignore')}")

    return video_output_path


import scipy.fft as sfft


def get_optimal_cpu_threads(workers: int = 1) -> int:
    """
    Calculates optimal CPU thread allocation for ONNX inference to avoid context thrashing.
    """
    total_cores = os.cpu_count() or 4
    if workers <= 1:
        if total_cores >= 8:
            return 8
        elif total_cores >= 6:
            return 6
        elif total_cores >= 4:
            return 4
        else:
            return max(1, total_cores)
    else:
        threads_per_worker = max(2, total_cores // workers)
        return min(6, threads_per_worker)


def stft_numpy(waveform: np.ndarray, n_fft: int = 6144, hop_length: int = 1024) -> np.ndarray:
    """
    Computes Short-Time Fourier Transform (STFT) matching PyTorch center=True reflect padding.
    Accelerated with multi-threaded SciPy PocketFFT (workers=-1).
    waveform: shape (2, n_samples)
    returns: shape (2, n_fft // 2 + 1, n_frames) complex64
    """
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
    return np.transpose(spec, (0, 2, 1)).astype(np.complex64)


def istft_numpy(
    spec: np.ndarray,
    n_fft: int = 6144,
    hop_length: int = 1024,
    length: Optional[int] = None
) -> np.ndarray:
    """
    Computes Inverse Short-Time Fourier Transform (iSTFT).
    Accelerated with multi-threaded SciPy PocketFFT (workers=-1).
    spec: shape (2, n_fft // 2 + 1, n_frames) complex64
    returns: shape (2, length) float32
    """
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
    High-Performance AI Vocal & Instrumental Separator using MDX-Net ONNX.
    Supports multi-threaded inference and customizable batch size.
    """

    def __init__(self, models_dir: str = "models", cpu_threads: Optional[int] = None):
        self.models_dir = models_dir
        self.cpu_threads = cpu_threads
        self.current_model_key: Optional[str] = None
        self.session: Optional[ort.InferenceSession] = None
        self.model_info: Optional[Dict[str, Any]] = None

    def load_model(
        self,
        model_key: str,
        cpu_threads: Optional[int] = None,
        inter_op_threads: Optional[int] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None
    ) -> None:
        """Loads or downloads the ONNX model into memory with optimized thread settings."""
        if cpu_threads is not None:
            self.cpu_threads = cpu_threads

        if self.current_model_key == model_key and self.session is not None:
            return  # Already loaded

        model_path = download_model(
            model_key=model_key,
            models_dir=self.models_dir,
            progress_callback=progress_callback,
            cancel_check=cancel_check
        )

        if progress_callback:
            progress_callback(0.95, f"Đang nạp mô hình {model_key} vào bộ nhớ...")

        opts = ort.SessionOptions()
        effective_threads = self.cpu_threads if (self.cpu_threads and self.cpu_threads > 0) else get_optimal_cpu_threads(workers=1)
        opts.intra_op_num_threads = effective_threads
        opts.inter_op_num_threads = inter_op_threads if (inter_op_threads and inter_op_threads > 0) else 1

        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        opts.enable_cpu_mem_arena = True
        opts.enable_mem_pattern = True

        # Available execution providers
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
            progress_callback(1.0, f"Mô hình {model_key} đã sẵn sàng ({effective_threads} luồng CPU)!")

    def separate_waveform(
        self,
        mix: np.ndarray,
        overlap: float = 0.0,
        batch_size: int = 1,
        progress_callback: Optional[Callable[[float, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None
    ) -> Dict[str, np.ndarray]:
        """
        Performs AI separation on stereo float32 waveform (2, n_samples).
        Returns a dict containing 'instrumental' and 'vocals' waveforms.
        Uses optimized in-place chunk inference with configurable overlap.
        """
        if self.session is None or self.model_info is None:
            raise RuntimeError("Mô hình AI chưa được tải. Hãy gọi load_model() trước.")

        dim_f = self.model_info["dim_f"]
        dim_t = self.model_info["dim_t"]
        n_fft = self.model_info["n_fft"]
        hop_length = self.model_info["hop_length"]
        compensate = self.model_info["compensate"]
        target = self.model_info["target"]

        orig_len = mix.shape[1]
        total_duration = orig_len / 44100.0

        if progress_callback:
            progress_callback(0.05, "Đang tính toán ma trận phổ tần số (STFT Siêu Tốc)...")

        # 1. Full STFT
        spec = stft_numpy(mix, n_fft=n_fft, hop_length=hop_length)  # shape: (2, 3073, n_frames)
        n_frames = spec.shape[2]

        # Pad frames if audio is shorter than model chunk size
        if n_frames < dim_t:
            pad_frames = dim_t - n_frames
            spec = np.pad(spec, ((0, 0), (0, 0), (0, pad_frames)), mode="constant")
            n_frames = dim_t

        spec_f = spec[:, :dim_f, :]  # shape: (2, 3072, n_frames)

        # 2. Setup Overlap-Add Chunks
        step = max(1, int(dim_t * (1.0 - overlap)))
        starts = list(range(0, n_frames - dim_t + 1, step))
        if len(starts) == 0 or starts[-1] + dim_t < n_frames:
            starts.append(n_frames - dim_t)

        total_chunks = len(starts)
        accum_spec = np.zeros_like(spec_f, dtype=np.complex64)
        weight = np.zeros((1, 1, n_frames), dtype=np.float32)

        # Select window according to overlap
        if overlap <= 0.01:
            chunk_win = np.ones((1, 1, dim_t), dtype=np.float32)
        else:
            chunk_win = np.hanning(dim_t).astype(np.float32)[np.newaxis, np.newaxis, :]

        start_time = time.time()
        b_size = max(1, int(batch_size))
        inp_batch = np.empty((b_size, 4, dim_f, dim_t), dtype=np.float32)

        # 3. Process chunks in batches through ONNX model
        for i in range(0, total_chunks, b_size):
            if cancel_check and cancel_check():
                raise RuntimeError("Quá trình tách âm đã bị dừng bởi người dùng.")

            cur_starts = starts[i : i + b_size]
            cur_batch_len = len(cur_starts)

            # Direct buffer population (Zero extra allocations)
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

            if progress_callback:
                processed_count = min(total_chunks, i + cur_batch_len)
                pct = 0.10 + 0.75 * (processed_count / total_chunks)
                elapsed = time.time() - start_time
                last_st = cur_starts[-1]
                processed_sec = min(total_duration, (last_st + dim_t) * hop_length / 44100.0)
                msg = f"Đang tách âm AI... ({processed_count}/{total_chunks} đoạn | {processed_sec:.1f}s/{total_duration:.1f}s)"
                progress_callback(pct, msg)

        # 4. Normalize overlapping regions
        accum_spec /= np.where(weight > 1e-6, weight, 1.0)

        # 5. Restore Nyquist frequency bin
        full_out_spec = np.pad(accum_spec, ((0, 0), (0, 1), (0, 0)), mode="constant")

        if progress_callback:
            progress_callback(0.88, "Đang tái tạo dạng sóng âm thanh (iSTFT Siêu Tốc)...")

        # 6. Inverse STFT
        target_wav = istft_numpy(full_out_spec, n_fft=n_fft, hop_length=hop_length, length=orig_len) * compensate

        # 7. Deduce stems
        if target == "instrumental":
            instrumental = target_wav
            vocals = mix - instrumental
        else:  # target == "vocals"
            vocals = target_wav
            instrumental = mix - vocals

        if progress_callback:
            progress_callback(0.95, "Hoàn tất giải mã các track âm thanh!")

        return {
            "instrumental": instrumental,
            "vocals": vocals
        }

    def process_file(
        self,
        input_file: str,
        output_dir: str,
        mode: str = "both",  # "instrumental", "vocals", "both", "video_replace"
        model_key: str = "UVR-MDX-NET-Inst_HQ_3",
        audio_format: str = "mp3",
        bitrate: str = "320k",
        overlap: float = 0.5,
        batch_size: int = 1,
        cpu_threads: Optional[int] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None
    ) -> Dict[str, str]:
        """
        Full end-to-end file processing workflow.
        Returns a dict of created output file paths.
        """
        os.makedirs(output_dir, exist_ok=True)
        base_name = os.path.splitext(os.path.basename(input_file))[0]
        is_video = is_video_file(input_file)

        if progress_callback:
            progress_callback(0.0, f"Bắt đầu xử lý: {os.path.basename(input_file)}")

        # 1. Load model
        self.load_model(
            model_key=model_key,
            cpu_threads=cpu_threads,
            progress_callback=progress_callback,
            cancel_check=cancel_check
        )

        # 2. Load audio
        if progress_callback:
            progress_callback(0.05, "Đang đọc dữ liệu âm thanh từ file nguồn...")
        mix_audio, duration = load_audio_waveform(input_file, sample_rate=44100)

        # 3. AI Separation
        stems = self.separate_waveform(
            mix_audio,
            overlap=overlap,
            batch_size=batch_size,
            progress_callback=progress_callback,
            cancel_check=cancel_check
        )

        output_files: Dict[str, str] = {}

        # 4. Save Audio Stems based on Mode
        if mode in ["instrumental", "both", "video_replace"]:
            if progress_callback:
                progress_callback(0.92, "Đang xuất file Nhạc Nền (Instrumental)...")
            inst_path = os.path.join(output_dir, f"{base_name}_instrumental.{audio_format}")
            saved_inst = save_audio_waveform(
                stems["instrumental"],
                inst_path,
                sample_rate=44100,
                format_type=audio_format,
                bitrate=bitrate
            )
            output_files["instrumental"] = saved_inst

        if mode in ["vocals", "both"]:
            if progress_callback:
                progress_callback(0.94, "Đang xuất file Giọng Nói (Vocals)...")
            voc_path = os.path.join(output_dir, f"{base_name}_vocals.{audio_format}")
            saved_voc = save_audio_waveform(
                stems["vocals"],
                voc_path,
                sample_rate=44100,
                format_type=audio_format,
                bitrate=bitrate
            )
            output_files["vocals"] = saved_voc

        # 5. Handle Video Replacement if input is a video
        if is_video and (mode == "video_replace" or mode == "both"):
            if progress_callback:
                progress_callback(0.97, "Đang tạo file Video mới với nhạc nền đã xóa giọng nói...")
            ext = os.path.splitext(input_file)[1]
            video_out = os.path.join(output_dir, f"{base_name}_no_vocals{ext}")
            
            # Use instrumental track as audio
            inst_audio_file = output_files.get("instrumental")
            if not inst_audio_file:
                inst_audio_file = os.path.join(output_dir, f"{base_name}_temp_inst.wav")
                save_audio_waveform(stems["instrumental"], inst_audio_file, format_type="wav")

            replace_video_audio(input_file, inst_audio_file, video_out, bitrate=bitrate)
            output_files["video_no_vocals"] = video_out

        if progress_callback:
            progress_callback(1.0, f"Đã hoàn thành xuất sắc: {os.path.basename(input_file)}")

        return output_files


def process_files_concurrent(
    files: List[str],
    output_dir: str,
    mode: str = "both",
    model_key: str = "UVR-MDX-NET-Inst_HQ_3",
    audio_format: str = "mp3",
    bitrate: str = "320k",
    overlap: float = 0.5,
    batch_size: int = 1,
    max_workers: int = 2,
    cpu_threads_per_worker: Optional[int] = None,
    models_dir: str = "models",
    file_progress_callback: Optional[Callable[[str, float, str], None]] = None,
    total_progress_callback: Optional[Callable[[float, int, int, str], None]] = None,
    log_callback: Optional[Callable[[str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None
) -> Tuple[int, Dict[str, Dict[str, str]], List[Tuple[str, str]]]:
    """
    Processes multiple audio/video files concurrently across worker threads.
    Returns (success_count, results_dict, errors_list).
    """
    total_files = len(files)
    if total_files == 0:
        return 0, {}, []

    workers = max(1, min(max_workers, total_files))
    completed_count = 0
    success_count = 0
    results: Dict[str, Dict[str, str]] = {}
    errors: List[Tuple[str, str]] = []
    lock = threading.Lock()

    # Pre-download model to avoid race condition during download
    download_model(model_key=model_key, models_dir=models_dir)

    def worker_task(fpath: str, worker_id: int):
        nonlocal completed_count, success_count
        if cancel_check and cancel_check():
            return fpath, None, "Đã hủy bởi người dùng"

        fname = os.path.basename(fpath)
        if log_callback:
            log_callback(f"[Luồng {worker_id}] ▶ Bắt đầu: {fname}")

        # Each worker thread initializes its own engine instance with calculated threads
        eng = VocalSeparatorEngine(models_dir=models_dir, cpu_threads=cpu_threads_per_worker)

        def on_prog(p: float, msg: str):
            if file_progress_callback:
                file_progress_callback(fpath, p, msg)
            if total_progress_callback:
                with lock:
                    overall_p = (completed_count + p) / total_files
                    total_progress_callback(overall_p, completed_count, total_files, f"[{worker_id}] {fname}: {msg}")

        try:
            res = eng.process_file(
                input_file=fpath,
                output_dir=output_dir,
                mode=mode,
                model_key=model_key,
                audio_format=audio_format,
                bitrate=bitrate,
                overlap=overlap,
                batch_size=batch_size,
                cpu_threads=cpu_threads_per_worker,
                progress_callback=on_prog,
                cancel_check=cancel_check
            )
            with lock:
                completed_count += 1
                success_count += 1
                results[fpath] = res
                if total_progress_callback:
                    total_progress_callback(completed_count / total_files, completed_count, total_files, f"Hoàn thành: {fname}")
            if log_callback:
                log_callback(f"[Luồng {worker_id}] ✅ Hoàn thành: {fname}")
            return fpath, res, None
        except Exception as e:
            with lock:
                completed_count += 1
                errors.append((fpath, str(e)))
                if total_progress_callback:
                    total_progress_callback(completed_count / total_files, completed_count, total_files, f"Lỗi: {fname}")
            if log_callback:
                log_callback(f"[Luồng {worker_id}] ❌ Lỗi khi xử lý {fname}: {e}")
            return fpath, None, str(e)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = []
        for idx, f in enumerate(files):
            w_id = (idx % workers) + 1
            futures.append(executor.submit(worker_task, f, w_id))

        for fut in as_completed(futures):
            if cancel_check and cancel_check():
                break
            fut.result()

    return success_count, results, errors
