"""ChatGPT request budgets and subtitle preservation, without network calls."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import PipelineConfig
from translator import (
    CHATGPT_WEB_MAX_WORDS, ChatGPTWebTranslator, build_batch_prompt,
    build_chatgpt_batches, build_chatgpt_system_instruction,
    fit_chatgpt_story_context, parse_srt_string, translate_batch_resilient,
)


class ChatGPTWordLimitTests(unittest.TestCase):
    def setUp(self):
        self.config = PipelineConfig(whisper_language="en", target_language="vi",
                                     chatgpt_cookie="test-cookie")

    def items(self, count=10, words=700):
        return parse_srt_string("\n".join(
            f"{i}\n00:00:{i:02d},000 --> 00:00:{i+1:02d},000\n"
            + "story " * words + "\n" for i in range(1, count + 1)
        ))

    def test_long_video_splits_without_losing_subtitles_and_retries_fit(self):
        items = self.items()
        batches = build_chatgpt_batches(items, self.config)
        self.assertGreater(len(batches), 1)
        self.assertEqual([item for batch in batches for item in batch], items)
        system = build_chatgpt_system_instruction(self.config)
        story = "opening " * 10000 + "ending " * 10000
        for number, batch in enumerate(batches, 1):
            context = fit_chatgpt_story_context(batch, story, self.config)
            prompts = []
            def ai(prompt):
                prompts.append(prompt)
                if len(prompts) == 1:
                    return ""
                return "\n".join(f"[{item.index}] Bản dịch." for item in batch)
            result = translate_batch_resilient(ai, batch, number, len(batches),
                                              full_story_context=context, source_language="en")
            self.assertEqual(len(prompts), 2)
            for prompt in prompts:
                self.assertLessEqual(len((system + "\n\n" + prompt).split()), CHATGPT_WEB_MAX_WORDS)
            self.assertEqual([i.index for i in result], [i.index for i in batch])
            self.assertEqual([(i.start_seconds, i.end_seconds) for i in result],
                             [(i.start_seconds, i.end_seconds) for i in batch])

    def test_large_context_keeps_opening_and_ending(self):
        batch = self.items(count=1, words=10)
        story = "opening " + "middle " * 20000 + "ending"
        context = fit_chatgpt_story_context(batch, story, self.config)
        self.assertTrue(context.startswith("opening"))
        self.assertTrue(context.endswith("ending"))
        self.assertIn("…", context)
        prompt = build_batch_prompt(batch, context, source_language="en")
        self.assertLessEqual(len((build_chatgpt_system_instruction(self.config) + prompt).split()),
                             CHATGPT_WEB_MAX_WORDS)

    def test_oversized_subtitle_and_custom_instruction_fail_before_sending(self):
        with self.assertRaises(ValueError):
            build_chatgpt_batches(self.items(count=1, words=5001), self.config)
        self.config.custom_translation_prompt = "instruction " * 5001
        with self.assertRaises(ValueError):
            build_chatgpt_batches(self.items(count=1, words=1), self.config)
        with patch.object(ChatGPTWebTranslator, "_refresh_access_token"):
            translator = ChatGPTWebTranslator(self.config)
        with patch.object(translator, "_refresh_access_token") as refresh:
            with self.assertRaises(ValueError):
                translator._call_chatgpt_web("translate")
            refresh.assert_not_called()

    def test_file_translation_preserves_all_indexes_and_timestamps_across_batches(self):
        items = self.items(count=4, words=1500)
        with patch.object(ChatGPTWebTranslator, "_refresh_access_token"):
            translator = ChatGPTWebTranslator(self.config)
        batches = build_chatgpt_batches(items, self.config)
        responses = ["\n".join(f"[{i.index}] Câu chuyện hấp dẫn." for i in batch) for batch in batches]
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / "source.srt", Path(directory) / "target.srt"
            source.write_text("\n".join(i.to_srt_block() for i in items), encoding="utf-8")
            with patch.object(translator, "_call_chatgpt_web", side_effect=responses) as call:
                result = translator.translate_srt(source, target)
            self.assertEqual(call.call_count, len(batches))
            self.assertGreater(call.call_count, 1)
            exported = parse_srt_string(target.read_text(encoding="utf-8"))
            self.assertEqual(len(result), len(items))
            self.assertEqual([(i.index, i.start_seconds, i.end_seconds) for i in exported],
                             [(i.index, i.start_seconds, i.end_seconds) for i in items])
            self.assertTrue(all(i.text == "Câu chuyện hấp dẫn." for i in exported))


if __name__ == "__main__":
    unittest.main()
