"""Exercise the actual GUI preset, engine and subtitle/audio synchronization."""
from pathlib import Path
import sys
import tempfile
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "douyin_editor"))
from config import PipelineConfig, TTSConfig, VOICE_PRESETS
from transcriber import SubtitleItem
from tts_synchronizer import VietnameseTTSSynchronizer

preset = VOICE_PRESETS["japanese_minecraft_clone"]
config = PipelineConfig(tts_config=TTSConfig(voice=preset["voice"], preset_name=preset["name"]))
with tempfile.TemporaryDirectory() as directory:
    output = Path(directory) / "synced.wav"
    srt = Path(directory) / "synced.srt"
    subtitles = [SubtitleItem(index=1, start_seconds=1, end_seconds=7,
        start_str="00:00:01,000", end_str="00:00:07,000",
        text="みんな、マインクラフトで冒険しよう！")]
    _, synced = VietnameseTTSSynchronizer(config).generate_and_sync(subtitles, 10, output, srt)
    audio, sr = sf.read(output)
    assert abs(len(audio) / sr - 10) < 0.01
    assert np.isfinite(audio).all()
    assert np.max(np.abs(audio[:int(sr * 0.9)])) < 0.001
    assert np.sqrt(np.mean(audio[sr:] ** 2)) > 0.005
    assert synced and synced[0].start_seconds == 1
    assert "".join(item.text for item in synced) == subtitles[0].text
    assert "マインクラフト" in srt.read_text(encoding="utf-8")
    print(f"PASS: actual clone synthesis, {len(synced)} Japanese subtitle phrases, 10-second synchronized audio")
