import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import PipelineConfig, TTSConfig, VOICE_PRESETS
from translator import DeepSeekTranslator, GeminiTranslator
from tts_synchronizer import CapCutTTSEngine, VietnameseTTSSynchronizer, create_tts_engine
from voice_clone import JapaneseCloneTTSEngine

PRESET = VOICE_PRESETS["japanese_minecraft_clone"]
SRT = "1\n00:00:00,000 --> 00:00:03,000\nこんにちは、みんな！\n"


class JapaneseVoiceTests(unittest.TestCase):
    def setUp(self):
        self.config = PipelineConfig(
            deepseek_api_key="test-key", gemini_api_key="test-key",
            tts_config=TTSConfig(voice=PRESET["voice"]),
        )

    def test_engine_routing_and_existing_capcut(self):
        for identity in ["japanese_minecraft_clone", PRESET["voice"], PRESET["name"]]:
            self.assertIsInstance(create_tts_engine(identity), JapaneseCloneTTSEngine)
        self.assertIsInstance(create_tts_engine("BV074_streaming"), CapCutTTSEngine)

    def test_japanese_phrase_split_preserves_text(self):
        text = "みんな、こんにちは！今日はマインクラフトの世界でダイヤモンドを探しながら新しい家を建てていくよ。"
        phrases = VietnameseTTSSynchronizer.split_text_into_short_phrases(text, max_chars=12)
        self.assertEqual("".join(phrases), text)
        self.assertTrue(all(len(phrase) <= 12 for phrase in phrases))
        self.assertGreater(len(phrases), 1)
        self.assertEqual(VietnameseTTSSynchronizer.split_text_into_short_phrases("Xin chào các bạn!"), ["Xin chào các bạn!"])

    def test_deepseek_requests_japanese_and_preserves_vietnamese_default(self):
        response = Mock(status_code=200)
        response.json.return_value = {"choices": [{"message": {"content": SRT}}]}
        for voice, expected in [(PRESET["voice"], "tiếng Nhật"), ("BV074_streaming", "tiếng Việt")]:
            self.config.tts_config.voice = voice
            translator = DeepSeekTranslator(self.config)
            with patch("translator.requests.post", return_value=response) as post:
                translator._call_deepseek_api("subtitle input")
            instruction = post.call_args.kwargs["json"]["messages"][0]["content"]
            self.assertIn(expected, instruction)
            self.assertIn("GIỮ NGUYÊN TUYỆT ĐỐI timeline", instruction)

    def test_gemini_requests_japanese_and_keeps_srt_timing(self):
        translator = GeminiTranslator.__new__(GeminiTranslator)
        translator.config = self.config
        translator.model_name = "test-model"
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.srt"
            target = Path(directory) / "translated.srt"
            source.write_text("1\n00:00:00,000 --> 00:00:03,000\n你好\n", encoding="utf-8")
            with patch.object(translator, "_call_gemini_api", return_value=SRT) as call:
                items = translator.translate_srt(source, target)
            self.assertIn("tiếng Nhật", call.call_args.args[0])
            self.assertNotIn("tiếng Việt", call.call_args.args[0])
            self.assertEqual(items[0].text, "こんにちは、みんな！")
            self.assertEqual((items[0].start_seconds, items[0].end_seconds), (0, 3))


if __name__ == "__main__":
    unittest.main()
