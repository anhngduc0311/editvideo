from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import PipelineConfig, TTSConfig, VOICE_PRESETS
from gemini_cookie import GeminiCookieError, GeminiCookieTranslator, parse_gemini_cookies
from translator import create_translator, parse_srt_string
from gemini_webapi.exceptions import AuthError, TemporarilyBlockedError, UsageLimitExceededError


def subtitles(first=1, count=1, text="Hello everyone!"):
    return "\n".join(f"{i}\n00:00:{i:02},000 --> 00:00:{i + 1:02},000\n{text}\n" for i in range(first, first + count))


class GeminiCookieTests(unittest.TestCase):
    def setUp(self):
        self.config = PipelineConfig(
            llm_provider="gemini_web", deepseek_api_key="", gemini_api_key="",
            gemini_web_psid="private-psid", gemini_web_psidts="private-psidts",
            gemini_web_request_interval=0, whisper_language="en", target_language="ja",
            tts_config=TTSConfig(voice=VOICE_PRESETS["japanese_minecraft_clone"]["voice"]),
        )
        self.client = Mock(init=AsyncMock(), close=AsyncMock(), generate_content=AsyncMock())

    def test_individual_values_or_header_and_optional_timestamp(self):
        self.assertEqual(parse_gemini_cookies(" psid "), ("psid", ""))
        self.assertEqual(parse_gemini_cookies("Cookie: __Secure-1PSID=one; __Secure-1PSIDTS=two; other=ignored"), ("one", "two"))
        for value in ("", "invalid cookie value", "invalid;value"):
            with self.assertRaises(GeminiCookieError):
                parse_gemini_cookies(value)
        self.assertNotIn("private-psid", repr(self.config))

    def test_factory_does_not_require_api_key(self):
        self.assertIsInstance(create_translator(self.config), GeminiCookieTranslator)

    def test_one_session_for_multiple_batches_and_preserved_english_japanese_timeline(self):
        self.client.generate_content.side_effect = [Mock(text=subtitles(1, 15, "こんにちは！")), Mock(text=subtitles(16, 1, "こんにちは！"))]
        with tempfile.TemporaryDirectory() as directory, patch("gemini_webapi.GeminiClient", return_value=self.client) as factory:
            source, target = Path(directory) / "en.srt", Path(directory) / "ja.srt"
            source.write_text(subtitles(count=16), encoding="utf-8")
            original = parse_srt_string(source.read_text(encoding="utf-8"))
            translated = create_translator(self.config).translate_srt(source, target)
            self.assertEqual(len(translated), 16)
            self.assertEqual([item.start_str for item in translated], [item.start_str for item in original])
            self.assertTrue(all(item.text == "こんにちは！" for item in translated))
            factory.assert_called_once_with("private-psid", "private-psidts")
            self.client.init.assert_awaited_once()
            self.client.close.assert_awaited_once()
            self.assertEqual(self.client.generate_content.await_count, 2)
            prompt = self.client.generate_content.call_args_list[0].args[0]
            self.assertIn("Tiếng Anh sang Tiếng Nhật", prompt)
            self.assertIn("GIỮ NGUYÊN TUYỆT ĐỐI timeline", prompt)
            self.assertNotIn("tiếng Việt", prompt)

    def test_auth_or_quota_errors_stop_without_retries_and_close(self):
        for exception in (AuthError, TemporarilyBlockedError, UsageLimitExceededError):
            with self.subTest(exception=exception.__name__), tempfile.TemporaryDirectory() as directory, patch("gemini_webapi.GeminiClient", return_value=self.client):
                self.client.generate_content.reset_mock()
                self.client.close.reset_mock()
                self.client.generate_content.side_effect = exception("sensitive private-psid headers")
                source, target = Path(directory) / "en.srt", Path(directory) / "ja.srt"
                source.write_text(subtitles(), encoding="utf-8")
                with self.assertRaises(GeminiCookieError) as raised:
                    create_translator(self.config).translate_srt(source, target)
                self.assertNotIn("private-psid", str(raised.exception))
                self.assertFalse(target.exists())
                self.client.generate_content.assert_awaited_once()
                self.client.close.assert_awaited_once()

    def test_timeout_retries_once(self):
        self.client.generate_content.side_effect = [TimeoutError("private-psid"), Mock(text="OK")]
        with patch("gemini_webapi.GeminiClient", return_value=self.client), patch("gemini_cookie.asyncio.sleep", new_callable=AsyncMock) as sleep:
            result = create_translator(self.config).check_status()
        self.assertEqual(result["status"], "OK")
        self.assertEqual(self.client.generate_content.await_count, 2)
        sleep.assert_awaited_once_with(5)

    def test_partial_or_duplicate_response_is_not_published(self):
        for response in ("I cannot translate this", subtitles(count=1), subtitles(1, 1) + "\n" + subtitles(1, 1)):
            with self.subTest(response=response), tempfile.TemporaryDirectory() as directory, patch("gemini_webapi.GeminiClient", return_value=self.client):
                self.client.generate_content.return_value = Mock(text=response)
                source, target = Path(directory) / "en.srt", Path(directory) / "ja.srt"
                source.write_text(subtitles(count=2), encoding="utf-8")
                with self.assertRaises(GeminiCookieError):
                    create_translator(self.config).translate_srt(source, target)
                self.assertFalse(target.exists())

    def test_timeouts_stop_after_two_attempts(self):
        self.client.generate_content.side_effect = TimeoutError("private-psid")
        with patch("gemini_webapi.GeminiClient", return_value=self.client), patch("gemini_cookie.asyncio.sleep", new_callable=AsyncMock):
            result = create_translator(self.config).check_status()
        self.assertEqual(result["status"], "ERROR")
        self.assertNotIn("private-psid", result["message"])
        self.assertEqual(self.client.generate_content.await_count, 2)
        self.client.close.assert_awaited_once()

    def test_spacing_and_status_errors_are_safe(self):
        self.config.gemini_web_request_interval = 4
        self.client.generate_content.return_value = Mock(text="OK")
        with patch("gemini_webapi.GeminiClient", return_value=self.client), patch("gemini_cookie.asyncio.sleep", new_callable=AsyncMock) as sleep:
            translator = create_translator(self.config)
            with translator._session():
                translator._call_gemini_api("Check")
                translator._call_gemini_api("Check")
            self.assertEqual(sleep.await_count, 1)
            self.assertGreater(sleep.call_args.args[0], 0)
            self.assertLessEqual(sleep.call_args.args[0], 4)
        self.client.init.side_effect = AuthError("private-psid")
        with patch("gemini_webapi.GeminiClient", return_value=self.client):
            result = create_translator(self.config).check_status()
        self.assertEqual(result["status"], "ERROR")
        self.assertNotIn("private-psid", result["message"])


if __name__ == "__main__":
    unittest.main()
