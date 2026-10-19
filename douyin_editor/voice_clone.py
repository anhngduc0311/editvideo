"""Japanese TTS with the local OpenVoice reference used in the voice preview."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import threading
import wave

logger = logging.getLogger(__name__)
ASSET_DIR = Path(__file__).resolve().parent.parent / "tts"


class JapaneseCloneTTSEngine:
    # Model inference is serialized: preview and export may share a process.
    _lock = threading.RLock()
    _converter = None
    _source_se = None
    _target_se = None

    def __init__(self, cache_dir=None):
        local_data = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".cache")))
        self.cache_dir = Path(cache_dir) if cache_dir is not None else local_data / "EditVideo" / "tts_cache" / "japanese_clone"

    @staticmethod
    def _model_signature():
        # Replacing the reference or model must invalidate previously cloned audio.
        model_dir = ASSET_DIR / "models" / "openvoice_v2"
        identity = []
        for name in ("converter/config.json", "converter/checkpoint.pth",
                     "source_speaker.pth", "reference_speaker.pth"):
            path = model_dir / name
            stat = path.stat()
            identity.append((str(path.resolve()), stat.st_size, stat.st_mtime_ns))
        return identity

    @staticmethod
    def _wav_result(text, data):
        with wave.open(io.BytesIO(data), "rb") as wav:
            frames = wav.getnframes()
            if frames <= 0 or len(wav.readframes(frames)) != frames * wav.getnchannels() * wav.getsampwidth():
                raise ValueError("Tệp TTS lưu tạm không đầy đủ")
            duration = round(frames * 1000 / wav.getframerate())
        return text, data, duration

    def _read_cache(self, text, key):
        try:
            return self._wav_result(text, (self.cache_dir / f"{key}.wav").read_bytes())
        except (OSError, ValueError, EOFError, wave.Error):
            return None

    def _save_cache(self, key, data):
        temporary = None
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self.cache_dir, suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(data)
            os.replace(temporary, self.cache_dir / f"{key}.wav")
        except OSError:
            logger.warning("Không ghi được bộ nhớ đệm TTS; vẫn tiếp tục tạo giọng.")
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def _convert_source(self, text, source, key):
        import numpy as np
        import soundfile as sf

        with self._lock:
            self._load_model()
            audio = self._converter.convert(str(source), self._source_se, self._target_se)
            if len(audio) == 0 or not np.isfinite(audio).all():
                raise RuntimeError(f"Không tạo được giọng clone cho câu: {text}")
            sample_rate = self._converter.hps.data.sampling_rate
            buffer = io.BytesIO()
            sf.write(buffer, audio, sample_rate, format="WAV", subtype="PCM_16")
        result = self._wav_result(text, buffer.getvalue())
        self._save_cache(key, result[1])
        return result

    async def _synthesize_pending(self, pending, work, edge_rate, max_retries):
        import edge_tts

        downloads = asyncio.Semaphore(4)
        loop = asyncio.get_running_loop()
        # A single CPU converter avoids competing Torch threads, while up to four
        # network requests prepare subsequent phrases during inference.
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="clone_tts") as converter:
            async def synthesize_one(index, text, key):
                source = Path(work) / f"source_{index}.mp3"
                for attempt in range(max(1, max_retries)):
                    try:
                        async with downloads:
                            await asyncio.wait_for(edge_tts.Communicate(
                                text, "ja-JP-KeitaNeural", rate=edge_rate,
                                pitch="+18Hz", volume="+5%",
                            ).save(str(source)), timeout=60)
                        break
                    except Exception:
                        if attempt + 1 >= max(1, max_retries):
                            raise
                        await asyncio.sleep(min(2, 0.5 * (2 ** attempt)))
                return await loop.run_in_executor(converter, self._convert_source, text, source, key)

            # Wait for all writers before removing the temporary directory, even
            # when one phrase fails. Completed phrases remain cached for retry.
            results = await asyncio.gather(*(synthesize_one(i, text, key)
                                             for i, (text, key) in enumerate(pending)),
                                           return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                raise result
        return results

    @classmethod
    def _load_model(cls):
        if cls._converter is not None:
            return
        vendor = ASSET_DIR / "vendor" / "OpenVoice"
        model_dir = ASSET_DIR / "models" / "openvoice_v2"
        required = [
            vendor / "openvoice" / "api.py",
            model_dir / "converter" / "config.json",
            model_dir / "converter" / "checkpoint.pth",
            model_dir / "source_speaker.pth",
            model_dir / "reference_speaker.pth",
        ]
        for path in required:
            if not path.is_file():
                raise FileNotFoundError(f"Thiếu tài nguyên giọng Nam Nhật Minecraft: {path}")
        if str(vendor) not in sys.path:
            sys.path.insert(0, str(vendor))
        import torch
        from openvoice.api import ToneColorConverter

        torch.set_num_threads(4)
        logger.info("Đang nạp giọng Nam Nhật Minecraft (OpenVoice CPU)...")
        converter = ToneColorConverter(
            str(model_dir / "converter" / "config.json"),
            device="cpu", enable_watermark=False,
        )
        converter.load_ckpt(str(model_dir / "converter" / "checkpoint.pth"))
        source_se = torch.load(model_dir / "source_speaker.pth", map_location="cpu", weights_only=True)
        target_se = torch.load(model_dir / "reference_speaker.pth", map_location="cpu", weights_only=True)
        cls._source_se, cls._target_se = source_se, target_se
        cls._converter = converter

    def synthesize_phrases(self, texts, voice="openvoice_japanese_minecraft",
                           resource_id="", rate="1.0", max_retries=3):
        if not texts:
            return []
        speed = float(rate)
        if not 0.5 <= speed <= 2.0:
            raise ValueError("Tốc độ đọc phải trong khoảng 0.5–2.0.")
        edge_rate = f"{round((1.18 * speed - 1) * 100):+d}%"
        signature = self._model_signature()
        keys = {}
        ready = {}
        pending = []
        for text in texts:
            if not text.strip() or text in keys:
                continue
            payload = ["clone-v1", signature, text, voice, edge_rate, "+18Hz", "+5%"]
            key = hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode("utf-8")).hexdigest()
            keys[text] = key
            cached = self._read_cache(text, key)
            if cached is not None:
                ready[text] = cached
            else:
                pending.append((text, key))
        if pending:
            with tempfile.TemporaryDirectory(prefix="japanese_clone_") as work:
                generated = asyncio.run(self._synthesize_pending(pending, work, edge_rate, max_retries))
            ready.update((result[0], result) for result in generated)
        logger.info("TTS Nhật: %d câu mới, %d câu dùng lại từ bộ nhớ đệm/lặp lại.",
                    len(pending), sum(bool(text.strip()) for text in texts) - len(pending))
        return [ready[text] if text.strip() else (text, None, 0) for text in texts]
