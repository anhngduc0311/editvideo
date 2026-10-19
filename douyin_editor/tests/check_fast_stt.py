"""Opt-in Windows inference smoke test using synthetic English speech only."""
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import PipelineConfig
from transcriber import WhisperTranscriber

if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as directory:
        audio = Path(directory) / "english.wav"
        script = Path(directory) / "speech.vbs"
        script.write_text(
            'Set voice = CreateObject("SAPI.SpVoice")\n'
            'Set stream = CreateObject("SAPI.SpFileStream")\n'
            f'stream.Open "{audio}", 3, False\n'
            'Set voice.AudioOutputStream = stream\n'
            'voice.Speak "Hello everyone. Today we are testing fast speech recognition. The video is in English."\n'
            'stream.Close\n', encoding="utf-8",
        )
        subprocess.run(["cscript", "//nologo", str(script)], check=True, timeout=30)
        transcriber = WhisperTranscriber(PipelineConfig(stt_engine="faster", whisper_language="en", whisper_model_size="base"))
        started = time.perf_counter()
        result = transcriber.transcribe(audio, Path(directory) / "en.srt")
        recognized = " ".join(item.text for item in result)
        assert "hello" in recognized.lower() and "english" in recognized.lower(), recognized
        print("PASS: real Faster Whisper base.en inference,", len(result), "segments,", round(time.perf_counter() - started, 2), "seconds including model load")
        print(recognized.encode("ascii", "replace").decode())
