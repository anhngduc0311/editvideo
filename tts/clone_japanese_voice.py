"""Read Japanese narration using the YouTube reference's voice characteristics."""
from pathlib import Path
import os
import sys
import subprocess
import requests

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "vendor" / "OpenVoice"))
MODEL = ROOT / "models" / "openvoice_v2" / "converter"
MODEL.mkdir(parents=True, exist_ok=True)

for name in ["config.json", "checkpoint.pth"]:
    destination = MODEL / name
    if not destination.exists():
        url = f"https://huggingface.co/myshell-ai/OpenVoiceV2/resolve/main/converter/{name}"
        print(f"Downloading {name}", flush=True)
        with requests.get(url, stream=True, timeout=90) as response:
            response.raise_for_status()
            with destination.with_suffix(destination.suffix + ".part").open("wb") as output:
                for chunk in response.iter_content(1024 * 1024):
                    output.write(chunk)
        destination.with_suffix(destination.suffix + ".part").replace(destination)

import torch
import soundfile as sf
import numpy as np
from openvoice.api import ToneColorConverter

torch.set_num_threads(min(4, os.cpu_count() or 1))
print("Loading voice conversion model on CPU", flush=True)
converter = ToneColorConverter(str(MODEL / "config.json"), device="cpu", enable_watermark=False)
converter.load_ckpt(str(MODEL / "checkpoint.pth"))
source = ROOT / "japanese_male_minecraft_energetic.mp3"
reference = ROOT / "youtube_voice_reference" / "voice_sample_13s_43s.wav"
print("Extracting source and reference speaker embeddings", flush=True)
source_se = converter.extract_se(str(source), str(MODEL.parent / "source_speaker.pth"))
target_se = converter.extract_se(str(reference), str(MODEL.parent / "reference_speaker.pth"))
output_wav = ROOT / "japanese_youtube_voice_clone.wav"
print("Converting the Japanese narration", flush=True)
converter.convert(str(source), source_se, target_se, output_path=str(output_wav))
samples, sample_rate = sf.read(output_wav)
if len(samples) == 0 or not np.isfinite(samples).all() or np.max(np.abs(samples)) < 0.001:
    raise RuntimeError("Generated audio is empty or invalid")
ffmpeg = ROOT / "youtube_voice_reference" / "tools" / "ffmpeg.exe"
output_mp3 = output_wav.with_suffix(".mp3")
subprocess.run([str(ffmpeg), "-y", "-i", str(output_wav), "-codec:a", "libmp3lame", "-b:a", "192k", str(output_mp3)], check=True, capture_output=True)
print(f"DONE: {output_mp3}; duration={len(samples)/sample_rate:.2f}s; peak={np.max(np.abs(samples)):.3f}", flush=True)
