"""Check Japanese voice routing, translation retries and real synchronized speech."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "douyin_editor"))
from config import PipelineConfig, TTSConfig, VOICE_PRESETS, get_voice_preset, get_tts_language
from transcriber import SubtitleItem
from translator import build_translation_system_instruction, translate_batch_resilient
from tts_synchronizer import VietnameseTTSSynchronizer, create_tts_engine
from voice_clone import JapaneseCloneTTSEngine

PRESET = VOICE_PRESETS["japanese_minecraft_clone"]

def item(index, text):
    return SubtitleItem(index, index, index + 4, f"00:00:0{index},000", f"00:00:0{index+4},000", text)

class JapaneseVoiceTests(unittest.TestCase):
    def test_voice_routes_to_local_clone(self):
        for identity in ("japanese_minecraft_clone", PRESET["voice"], PRESET["name"]):
            self.assertIs(get_voice_preset(identity), PRESET)
            self.assertIsInstance(create_tts_engine(identity), JapaneseCloneTTSEngine)
        self.assertEqual(get_tts_language("BV074_streaming"), "vi")
        self.assertTrue((ROOT / "tts" / PRESET["preview_file"]).is_file())
        self.assertEqual(len(JapaneseCloneTTSEngine._model_signature()), 4)

    def test_translation_retries_remain_japanese_and_keep_timing(self):
        subtitles = [item(1, "第一天"), item(2, "第二天")]
        prompts = []
        responses = iter(["[1] 一日目。", "", "[2] 二日目！"])
        def ai(prompt):
            prompts.append(prompt)
            return next(responses)
        result = translate_batch_resilient(ai, subtitles, 1, 1,
                                          max_batch_retries=1, target_language="ja")
        self.assertEqual([s.text for s in result], ["一日目。", "二日目！"])
        self.assertEqual([(s.index,s.start_seconds,s.end_seconds) for s in result],
                         [(s.index,s.start_seconds,s.end_seconds) for s in subtitles])
        self.assertEqual(len(prompts), 3)
        self.assertTrue(all("Tiếng Nhật" in p and "Tiếng Việt" not in p for p in prompts))
        config = PipelineConfig(tts_config=TTSConfig(voice=PRESET["voice"]))
        self.assertIn("tiếng Nhật", build_translation_system_instruction(config))
        self.assertIn("Tiếng Việt", build_translation_system_instruction(PipelineConfig()))

    def test_japanese_sentence_boundaries_and_punctuation(self):
        text = "こんにちは。冒険しよう！準備はいい？"
        split = VietnameseTTSSynchronizer.split_subtitles_into_short_sentences([item(1,text)])
        self.assertEqual([s.text for s in split], ["こんにちは。", "冒険しよう！", "準備はいい？"])
        self.assertEqual(VietnameseTTSSynchronizer._clean_text(text), text)
        self.assertEqual(split[0].start_seconds, 1)
        self.assertAlmostEqual(split[-1].end_seconds, 5)

if __name__ == "__main__":
    if "--synthesize" in sys.argv:
        import numpy as np
        import soundfile as sf
        config = PipelineConfig(tts_config=TTSConfig(voice=PRESET["voice"]))
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "voice.wav"
            srt = Path(directory) / "voice.srt"
            _, subs = VietnameseTTSSynchronizer(config).generate_and_sync(
                [item(1, "みんな、冒険しよう！")], 10, audio, srt)
            data, sr = sf.read(audio)
            assert len(data) / sr >= 10
            assert np.isfinite(data).all() and np.max(np.abs(data)) > 0.01
            assert np.max(np.abs(data[:int(sr*0.9)])) < 0.001
            assert subs and subs[0].text == "みんな、冒険しよう！"
            assert "冒険しよう" in srt.read_text(encoding="utf-8")
            print("PASS: real Japanese clone speech, timeline and SRT")
    else:
        unittest.main()
