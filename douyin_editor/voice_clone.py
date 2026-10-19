"""Japanese TTS with the local OpenVoice reference used in the voice preview."""
from __future__ import annotations

import asyncio
import io
import logging
from pathlib import Path
import sys
import tempfile
import threading

logger = logging.getLogger(__name__)
ASSET_DIR = Path(__file__).resolve().parent.parent / "tts"


class JapaneseCloneTTSEngine:
    # Model inference is serialized: preview and export may share a process.
    _lock = threading.RLock()
    _converter = None
    _source_se = None
    _target_se = None

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
        import edge_tts
        import numpy as np
        import soundfile as sf

        speed = float(rate)
        if not 0.5 <= speed <= 2.0:
            raise ValueError("Tốc độ đọc phải trong khoảng 0.5–2.0.")
        edge_rate = f"{round((1.18 * speed - 1) * 100):+d}%"
        results = []
        with self._lock, tempfile.TemporaryDirectory(prefix="japanese_clone_") as work:
            self._load_model()
            for index, text in enumerate(texts):
                if not text.strip():
                    results.append((text, None, 0))
                    continue
                source = Path(work) / f"source_{index}.mp3"

                async def synthesize_source():
                    await edge_tts.Communicate(
                        text, "ja-JP-KeitaNeural", rate=edge_rate,
                        pitch="+18Hz", volume="+5%",
                    ).save(str(source))

                # Edge creates the Japanese pronunciation; OpenVoice applies
                # the exact same speaker embedding as the user's chosen sample.
                asyncio.run(synthesize_source())
                audio = self._converter.convert(
                    str(source), self._source_se, self._target_se,
                )
                if len(audio) == 0 or not np.isfinite(audio).all():
                    raise RuntimeError(f"Không tạo được giọng clone cho câu: {text}")
                sample_rate = self._converter.hps.data.sampling_rate
                buffer = io.BytesIO()
                sf.write(buffer, audio, sample_rate, format="WAV", subtype="PCM_16")
                results.append((text, buffer.getvalue(), round(len(audio) * 1000 / sample_rate)))
        return results
