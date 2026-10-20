"""Exercise the installed CapCut SDK and signer with mocked HTTP transport."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import PipelineConfig
from pydub import AudioSegment
from transcriber import SubtitleItem
from tts_synchronizer import CapCutTTSEngine, VietnameseTTSSynchronizer, TTSServiceError, TTSTaskError


def response(data, status=200):
    return Mock(status_code=status, json=Mock(return_value=data))


class CapCutSDKContractTests(unittest.TestCase):
    def engine_with_transport(self):
        engine = CapCutTTSEngine()
        self.addCleanup(engine.session.close)
        transport = Mock()
        engine.session = transport
        engine.client.session = transport
        return engine, transport

    def test_real_sdk_creates_and_queries_tts_for_all_success_statuses(self):
        buffer = io.BytesIO()
        AudioSegment.silent(duration=400).export(buffer, format="wav")
        for status in ("success", "succeed", "succeeded", "completed", "done"):
            with self.subTest(status=status):
                engine, transport = self.engine_with_transport()
                payload = {"audio_subtitles": [{"text": "Xin chào.", "audio_url": "https://audio.test/1", "duration": 400}]}
                calls = []
                def post(url, **kwargs):
                    body = json.loads(kwargs["data"])
                    calls.append(body)
                    self.assertEqual(body["tasks"][0]["req_key"], "sami_text_to_speech")
                    if urlparse(url).path.endswith("/new"):
                        return response({"ret": 0, "data": {"bind_id": "bind-test", "tasks": [{"id": "task-test", "token": "test-token"}]}})
                    self.assertIn("bind-test", json.dumps(body))
                    return response({"ret": 0, "data": {"tasks": [{"status": status,
                        "payload": json.dumps(payload) if status == "success" else payload}]}})
                transport.post.side_effect = post
                transport.get.return_value = Mock(status_code=200, content=buffer.getvalue())
                with patch("tts_synchronizer.time.sleep"):
                    results = engine.synthesize_phrases(["Xin chào."], rate="1.0", max_retries=1)
                self.assertEqual(results[0][0], "Xin chào.")
                self.assertTrue(results[0][1])
                self.assertEqual(len(calls), 2)
                transport.get.assert_called_once_with("https://audio.test/1", timeout=(5, 25))

    def test_authentication_error_is_not_retried_per_sentence(self):
        engine, transport = self.engine_with_transport()
        transport.post.return_value = response({"ret": 1001, "errmsg": "Login required"}, 401)
        with self.assertRaisesRegex(TTSServiceError, "HTTP 401"):
            engine.synthesize_phrases(["Xin chào."], max_retries=3)
        self.assertEqual(transport.post.call_count, 1)
        transport.get.assert_not_called()

    def test_sdk_application_error_surfaces_its_reason(self):
        engine, transport = self.engine_with_transport()
        transport.post.return_value = response({"ret": 1014, "errmsg": "System busy"})
        with self.assertRaisesRegex(TTSServiceError, "System busy"):
            engine.synthesize_phrases(["Xin chào."], max_retries=1)
        self.assertEqual(transport.post.call_count, 1)

    def test_whole_service_failure_aborts_instead_of_retrying_every_cue(self):
        provider = Mock()
        provider.synthesize_phrases.side_effect = TTSServiceError("CapCut TTS: System busy")
        with patch("tts_synchronizer.create_tts_engine", return_value=provider):
            synchronizer = VietnameseTTSSynchronizer(PipelineConfig())
        with tempfile.TemporaryDirectory() as directory:
            cue = SubtitleItem(1, 0, 2, "00:00:00,000", "00:00:02,000", "Xin chào.")
            with self.assertRaisesRegex(TTSServiceError, "System busy"):
                synchronizer.generate_and_sync([cue], 2, Path(directory) / "audio.wav")
        provider.synthesize_phrases.assert_called_once()

    def test_failed_task_is_recoverable_and_includes_server_reason(self):
        engine, transport = self.engine_with_transport()
        transport.post.side_effect = [
            response({"ret": 0, "data": {"tasks": [{"id": "task", "token": "private-token"}]}}),
            response({"ret": 0, "data": {"tasks": [{"status": "failed", "token": "private-token",
                "payload": json.dumps({"error_code": 1234, "message": "Text too long"})}]}}),
        ]
        with patch("tts_synchronizer.time.sleep"):
            with self.assertRaises(TTSTaskError) as caught:
                engine.synthesize_phrases(["Xin chào."], max_retries=1)
        self.assertIn("1234", str(caught.exception))
        self.assertIn("Text too long", str(caught.exception))
        self.assertNotIn("private-token", str(caught.exception))

    def test_rejected_batch_splits_and_caches_successful_phrases(self):
        buffer = io.BytesIO()
        AudioSegment.silent(duration=100).export(buffer, format="wav")
        provider = Mock()
        calls = []
        def synthesize(**kwargs):
            texts = kwargs["texts"]
            calls.append(texts)
            if len(texts) > 1:
                raise TTSTaskError("Task failed")
            return [(texts[0], buffer.getvalue(), 100)]
        provider.synthesize_phrases.side_effect = synthesize
        with patch("tts_synchronizer.create_tts_engine", return_value=provider):
            synchronizer = VietnameseTTSSynchronizer(PipelineConfig())
        cues = [SubtitleItem(i, i - 1, i, "", "", f"Câu {i}.") for i in range(1, 5)]
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "audio.wav"
            _, result = synchronizer.generate_and_sync(cues, 4, target)
            self.assertEqual([cue.text for cue in result], [cue.text for cue in cues])
            self.assertEqual(len(list((target.parent / "tts_phrases").glob("*.wav"))), 4)
            self.assertEqual(sum(len(texts) == 1 for texts in calls), 4)
            provider.synthesize_phrases.reset_mock()
            synchronizer.generate_and_sync(cues, 4, target)
            provider.synthesize_phrases.assert_not_called()

    def test_service_error_after_split_keeps_completed_half_for_resume(self):
        buffer = io.BytesIO()
        AudioSegment.silent(duration=100).export(buffer, format="wav")
        provider = Mock()
        def synthesize(**kwargs):
            texts = kwargs["texts"]
            if len(texts) > 1:
                raise TTSTaskError("Task failed")
            if texts == ["Câu 2."]:
                raise TTSServiceError("HTTP 403")
            return [(texts[0], buffer.getvalue(), 100)]
        provider.synthesize_phrases.side_effect = synthesize
        with patch("tts_synchronizer.create_tts_engine", return_value=provider):
            synchronizer = VietnameseTTSSynchronizer(PipelineConfig())
        cues = [SubtitleItem(i, i - 1, i, "", "", f"Câu {i}.") for i in range(1, 10)]
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "audio.wav"
            with self.assertRaisesRegex(TTSServiceError, "403"):
                synchronizer.generate_and_sync(cues, 9, target)
            self.assertFalse(target.exists())
            self.assertEqual(len(list((target.parent / "tts_phrases").glob("*.wav"))), 1)
            self.assertFalse(any("Câu 9." in call.kwargs["texts"]
                                 for call in provider.synthesize_phrases.call_args_list))


if __name__ == "__main__":
    unittest.main()
