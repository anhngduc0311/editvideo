"""YouTube routing and English-to-Japanese requests, without external services."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import CookieConfig, PipelineConfig, TTSConfig, VOICE_PRESETS
from downloader import DouyinDownloader
from transcriber import WhisperTranscriber
from translator import DeepSeekTranslator, ChatGPTWebTranslator, translate_batch_resilient, parse_srt_string

VIDEO_ID = "BaW_jenozKc"
ENGLISH = "1\n00:00:01,000 --> 00:00:03,000\nHello everyone!\n"
JAPANESE = "1\n00:00:00,000 --> 00:00:05,000\nみなさん、こんにちは！\n"


class YouTubeTests(unittest.TestCase):
    def test_youtube_variants_skip_all_douyin_network_paths(self):
        urls = [f"https://www.youtube.com/watch?v={VIDEO_ID}&list=PLtest",
                f"https://youtu.be/{VIDEO_ID}?t=3", f"https://youtube.com/shorts/{VIDEO_ID}",
                f"https://m.youtube.com/watch?v={VIDEO_ID}"]
        with tempfile.TemporaryDirectory() as directory:
            downloader = DouyinDownloader(Path(directory), CookieConfig(cookie_str="DOUYIN_ONLY=secret"))
            output = Path(directory) / f"youtube_{VIDEO_ID}.mp4"
            for url in urls:
                with self.subTest(url=url), patch("downloader.yt_dlp.YoutubeDL") as factory, patch.object(downloader, "resolve_redirect_url") as redirect, patch.object(downloader, "_fetch_fresh_ttwid_cookie") as fresh, patch.object(downloader, "_download_via_direct_api") as api:
                    ydl = factory.return_value.__enter__.return_value
                    ydl.prepare_filename.return_value = str(output.with_suffix(".webm"))
                    def extract(url, download):
                        options = factory.call_args.args[0]
                        options["progress_hooks"][0]({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100})
                        output.write_bytes(b"v" * 2048)
                        options["post_hooks"][0](str(output))
                        return {"id": VIDEO_ID, "ext": "webm"}
                    ydl.extract_info.side_effect = extract
                    progress = Mock()
                    self.assertEqual(downloader.download("Video: " + url, progress_callback=progress), output.resolve())
                    options = factory.call_args.args[0]
                    self.assertTrue(options["noplaylist"])
                    self.assertNotIn("http_headers", options)
                    self.assertNotIn("cookiefile", options)
                    self.assertNotIn("cookiesfrombrowser", options)
                    ydl.extract_info.assert_called_once_with(f"https://www.youtube.com/watch?v={VIDEO_ID}", download=True)
                    redirect.assert_not_called()
                    fresh.assert_not_called()
                    api.assert_not_called()
                    self.assertEqual(progress.call_args.args[0], 1.0)

    def test_authentication_uses_explicit_file_or_browser(self):
        with tempfile.TemporaryDirectory() as directory:
            cookie = Path(directory) / "cookies.txt"
            cookie.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
            output = Path(directory) / "download.mp4"
            output.write_bytes(b"x" * 2048)
            for config, key, value in [(CookieConfig(cookie_file=cookie), "cookiefile", str(cookie)),
                                       (CookieConfig(browser_name="Edge"), "cookiesfrombrowser", ("edge", None, None, None))]:
                with patch("downloader.yt_dlp.YoutubeDL") as factory:
                    ydl = factory.return_value.__enter__.return_value
                    ydl.extract_info.return_value = {"id": VIDEO_ID}
                    ydl.prepare_filename.return_value = str(output)
                    DouyinDownloader(Path(directory), config).download(f"https://youtu.be/{VIDEO_ID}")
                    self.assertEqual(factory.call_args.args[0][key], value)

    def test_invalid_links_do_not_start_download(self):
        with tempfile.TemporaryDirectory() as directory, patch("downloader.yt_dlp.YoutubeDL") as factory:
            downloader = DouyinDownloader(Path(directory))
            for url in ["https://youtube.com/playlist?list=abc", "https://youtube.com/@channel",
                        "https://youtube.com.evil.test/watch?v=" + VIDEO_ID]:
                with self.subTest(url=url), self.assertRaises(ValueError):
                    downloader.download(url)
            factory.assert_not_called()

    def test_douyin_still_uses_existing_download_path(self):
        with tempfile.TemporaryDirectory() as directory:
            downloader = DouyinDownloader(Path(directory))
            with patch.object(downloader, "resolve_redirect_url", return_value="https://douyin.com/video/123"), patch.object(downloader, "_download_via_official_api", return_value=True) as api, patch.object(downloader, "_download_youtube") as youtube:
                downloader.download("https://v.douyin.com/example/")
                api.assert_called_once()
                youtube.assert_not_called()


class EnglishJapaneseTests(unittest.TestCase):
    def setUp(self):
        self.config = PipelineConfig(whisper_language="en", target_language="ja",
                                     deepseek_api_key="test-key", gemini_api_key="test-key",
                                     tts_config=TTSConfig(voice=VOICE_PRESETS["japanese_minecraft_clone"]["voice"]))

    def test_missing_translation_retries_keep_english_source_and_japanese_target(self):
        batch = parse_srt_string(ENGLISH)
        responses = iter(["", "", "[1] みなさん、こんにちは！"])
        prompts = []
        def ai(prompt):
            prompts.append(prompt)
            return next(responses)
        result = translate_batch_resilient(ai, batch, 1, 1, max_batch_retries=1,
                                          source_language="en", target_language="ja")
        self.assertEqual(result[0].text, "みなさん、こんにちは！")
        self.assertEqual(len(prompts), 3)
        self.assertTrue(all("Tiếng Nhật" in p and "Tiếng Việt" not in p for p in prompts))
        self.assertIn("Tiếng Anh", prompts[-1])
        self.assertEqual((result[0].start_seconds, result[0].end_seconds), (1, 3))

    def test_local_whisper_transcribes_english_without_translating(self):
        transcriber = WhisperTranscriber(self.config)
        transcriber._model = Mock()
        transcriber._model.transcribe.return_value = {"segments": [{"start": 1, "end": 3, "text": "Hello everyone!"}]}
        items = transcriber._transcribe_with_local_whisper(Path("audio.wav"))
        self.assertEqual(transcriber._model.transcribe.call_args.kwargs["language"], "en")
        self.assertEqual(transcriber._model.transcribe.call_args.kwargs["task"], "transcribe")
        self.assertEqual(items[0].text, "Hello everyone!")

    def test_both_translation_providers_use_english_and_japanese_and_keep_timing(self):
        response = Mock(status_code=200)
        response.json.return_value = {"choices": [{"message": {"content": JAPANESE}}]}
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "en.srt"
            source.write_text(ENGLISH, encoding="utf-8")
            target = Path(directory) / "ja.srt"
            deepseek = DeepSeekTranslator(self.config)
            with patch("translator.requests.post", return_value=response) as post:
                items = deepseek.translate_srt(source, target)
            messages = post.call_args.kwargs["json"]["messages"]
            self.assertIn("Tiếng Anh sang tiếng Nhật", messages[0]["content"])
            self.assertIn("TIẾNG ANH", messages[1]["content"])
            self.assertNotIn("tiếng Việt", messages[0]["content"])
            self.assertEqual((items[0].start_seconds, items[0].end_seconds), (1, 3))
            with patch.object(ChatGPTWebTranslator, "_refresh_access_token"):
                self.config.chatgpt_cookie = "test-cookie"
                chatgpt = ChatGPTWebTranslator(self.config)
            with patch.object(chatgpt, "_call_chatgpt_web", return_value=JAPANESE) as call:
                items = chatgpt.translate_srt(source, target)
            prompt = call.call_args.args[0]
            self.assertIn("TIẾNG ANH", prompt)
            self.assertIn("Tiếng Nhật", prompt)
            self.assertNotIn("TIẾNG TRUNG", prompt)
            self.assertEqual((items[0].start_seconds, items[0].end_seconds), (1, 3))
            self.assertIn("みなさん", target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
