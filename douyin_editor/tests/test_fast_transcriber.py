from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import PipelineConfig
from transcriber import SubtitleItem, WhisperTranscriber


class FastTranscriberTests(unittest.TestCase):
    def test_int8_english_model_and_timestamps_after_silence(self):
        transcriber = WhisperTranscriber(PipelineConfig(whisper_language="en", whisper_model_size="base"))
        model = Mock()
        model.transcribe.return_value = (iter([
            Mock(start=0.0, end=1.0, text="  "),
            Mock(start=12.5, end=14.0, text=" Hello! "),
            Mock(start=14.0, end=14.0, text="invalid"),
        ]), Mock(duration=20.0))
        with patch("faster_whisper.WhisperModel", return_value=model) as factory, patch.object(transcriber, "_load_stt_audio", return_value=np.zeros(16000, dtype=np.float32)):
            items = transcriber._transcribe_with_faster_whisper(Path("audio.wav"))
        self.assertEqual(factory.call_args.args[0], "base.en")
        self.assertEqual(factory.call_args.kwargs["compute_type"], "int8")
        self.assertEqual(factory.call_args.kwargs["device"], "cpu")
        self.assertEqual(len(items), 1)
        self.assertEqual((items[0].index, items[0].start_str, items[0].text), (1, "00:00:12,500", "Hello!"))
        options = model.transcribe.call_args.kwargs
        self.assertTrue(options["vad_filter"])
        self.assertEqual(options["language"], "en")
        self.assertEqual(options["beam_size"], 1)
        self.assertEqual(options["task"], "transcribe")

    def test_chinese_uses_multilingual_model(self):
        model = Mock()
        model.transcribe.return_value = (iter([]), Mock(duration=1.0))
        with patch("faster_whisper.WhisperModel", return_value=model) as factory, patch.object(WhisperTranscriber, "_load_stt_audio", return_value=np.zeros(16000, dtype=np.float32)):
            WhisperTranscriber(PipelineConfig(whisper_language="zh", whisper_model_size="small"))._transcribe_with_faster_whisper(Path("audio.wav"))
        self.assertEqual(factory.call_args.args[0], "small")

    def test_audio_normalization_for_decoder_compatibility(self):
        with patch("transcriber.subprocess.run", return_value=Mock(stdout=np.array([0.0, 0.5, -0.5], dtype="<f4").tobytes())) as run:
            audio = WhisperTranscriber._load_stt_audio(Path("input.wav"))
        np.testing.assert_array_equal(audio, [0, 0.5, -0.5])
        self.assertIn("16000", run.call_args.args[0])
        self.assertIn("f32le", run.call_args.args[0])

    def test_auto_fallback_and_explicit_original_route(self):
        item = SubtitleItem(1, 0, 1, "00:00:00,000", "00:00:01,000", "Hello!")
        with tempfile.TemporaryDirectory() as directory:
            audio, output = Path(directory) / "audio.wav", Path(directory) / "out.srt"
            audio.touch()
            for engine in ("auto", "whisper"):
                with self.subTest(engine=engine):
                    transcriber = WhisperTranscriber(PipelineConfig(stt_engine=engine))
                    with patch.object(transcriber, "_transcribe_with_faster_whisper", side_effect=ImportError("unavailable")) as fast, patch.object(transcriber, "_is_local_whisper_available", return_value=True), patch.object(transcriber, "_transcribe_with_local_whisper", return_value=[item]):
                        self.assertEqual(transcriber.transcribe(audio, output), [item])
                        self.assertEqual(fast.call_count, 1 if engine == "auto" else 0)
                        self.assertIn("Hello!", output.read_text(encoding="utf-8"))

    def test_fast_success_does_not_load_original_and_empty_audio_fails(self):
        item = SubtitleItem(1, 0, 1, "00:00:00,000", "00:00:01,000", "Hello!")
        with tempfile.TemporaryDirectory() as directory:
            audio, output = Path(directory) / "audio.wav", Path(directory) / "out.srt"
            audio.touch()
            transcriber = WhisperTranscriber(PipelineConfig())
            with patch.object(transcriber, "_transcribe_with_faster_whisper", return_value=[item]), patch.object(transcriber, "_is_local_whisper_available") as original:
                transcriber.transcribe(audio, output)
                original.assert_not_called()
            with patch.object(transcriber, "_transcribe_with_faster_whisper", return_value=[]), self.assertRaisesRegex(RuntimeError, "Không nhận diện"):
                transcriber.transcribe(audio, output)


if __name__ == "__main__":
    unittest.main()
