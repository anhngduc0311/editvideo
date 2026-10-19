import asyncio
from collections import Counter
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from voice_clone import JapaneseCloneTTSEngine


class CloneTTSSpeedTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.engine = JapaneseCloneTTSEngine(cache_dir=self.directory.name)
        self.requests = Counter()
        self.active_downloads = self.peak_downloads = 0
        self.conversions = []
        self.overlapped = False
        self.failed_once = set()
        self.fail = set()

        test = self

        class Communicate:
            def __init__(self, text, *args, **kwargs):
                self.text = text

            async def save(self, path):
                test.requests[self.text] += 1
                test.active_downloads += 1
                test.peak_downloads = max(test.peak_downloads, test.active_downloads)
                try:
                    await asyncio.sleep(0.02 if self.text == "first" else 0.08)
                    if self.text in test.fail:
                        raise ConnectionError("temporary network failure")
                    if self.text in test.failed_once:
                        test.failed_once.remove(self.text)
                        raise ConnectionError("retry this phrase")
                    Path(path).write_text(self.text, encoding="utf-8")
                finally:
                    test.active_downloads -= 1

        def convert(path, *args):
            self.overlapped |= self.active_downloads > 0
            self.conversions.append((Path(path).read_text(encoding="utf-8"), threading.get_ident()))
            time.sleep(0.01)
            return np.ones(240, dtype=np.float32) * 0.1

        converter = SimpleNamespace(convert=convert, hps=SimpleNamespace(data=SimpleNamespace(sampling_rate=24000)))
        for replacement in (
            patch("edge_tts.Communicate", Communicate),
            patch.object(JapaneseCloneTTSEngine, "_load_model"),
            patch.object(JapaneseCloneTTSEngine, "_converter", converter),
            patch.object(JapaneseCloneTTSEngine, "_model_signature", return_value=["reference-v1"]),
        ):
            replacement.start()
            self.addCleanup(replacement.stop)

    def test_downloads_overlap_inference_but_results_keep_original_order(self):
        texts = ["first"] + [f"phrase-{i}" for i in range(8)] + ["first", " "]
        results = self.engine.synthesize_phrases(texts)
        self.assertEqual([r[0] for r in results], texts)
        self.assertTrue(all(r[2] == 10 and r[1].startswith(b"RIFF") for r in results[:-1]))
        self.assertEqual(results[-1], (" ", None, 0))
        self.assertEqual(len(self.conversions), 9)
        self.assertEqual(len({thread for _, thread in self.conversions}), 1)
        self.assertGreater(self.peak_downloads, 1)
        self.assertLessEqual(self.peak_downloads, 4)
        self.assertTrue(self.overlapped)

    def test_cache_survives_new_engine_and_changes_with_rate_or_reference(self):
        original = self.engine.synthesize_phrases(["first"])
        restarted = JapaneseCloneTTSEngine(cache_dir=self.directory.name)
        self.assertEqual(restarted.synthesize_phrases(["first"]), original)
        self.assertEqual(self.requests["first"], 1)
        restarted.synthesize_phrases(["first"], rate="1.1")
        with patch.object(JapaneseCloneTTSEngine, "_model_signature", return_value=["reference-v2"]):
            restarted.synthesize_phrases(["first"])
        self.assertEqual(self.requests["first"], 3)

    def test_corrupt_cache_is_regenerated(self):
        self.engine.synthesize_phrases(["first"])
        next(Path(self.directory.name).glob("*.wav")).write_bytes(b"broken")
        self.engine.synthesize_phrases(["first"])
        self.assertEqual(self.requests["first"], 2)

    def test_retry_only_failed_phrase_and_keep_successful_cache_after_failure(self):
        self.failed_once.add("retry")
        self.engine.synthesize_phrases(["first", "retry"])
        self.assertEqual(self.requests, Counter(first=1, retry=2))
        self.fail.add("bad")
        with self.assertRaises(ConnectionError):
            self.engine.synthesize_phrases(["saved", "bad"], max_retries=1)
        self.fail.clear()
        self.engine.synthesize_phrases(["saved", "bad"], max_retries=1)
        self.assertEqual(self.requests["saved"], 1)
        self.assertEqual(self.requests["bad"], 2)


if __name__ == "__main__":
    unittest.main()
