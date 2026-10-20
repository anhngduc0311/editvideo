"""Recover truncated YouTube streams without retrying access failures."""
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from downloader import DouyinDownloader
from job_state import JobCancelled
from yt_dlp.utils import DownloadError


class YouTubeRetryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.downloader = DouyinDownloader(Path(self.directory.name))
        self.url = "https://www.youtube.com/watch?v=BaW_jenozKc"

    def test_short_reads_refresh_url_then_restart_partial_on_last_attempt(self):
        output = Path(self.directory.name) / "youtube_BaW_jenozKc.mp4"
        progress, options = Mock(), []
        with patch("downloader.yt_dlp.YoutubeDL") as factory, patch("downloader.time.sleep"):
            client = factory.return_value.__enter__.return_value
            client.prepare_filename.return_value = str(output)
            def extract(url, download):
                options.append(factory.call_args.args[0])
                if len(options) < 3:
                    raise DownloadError("ERROR: [download] Got error: 2000 bytes read, 2875956 more expected")
                output.write_bytes(b"v" * 2048)
                return {"id": "BaW_jenozKc"}
            client.extract_info.side_effect = extract
            result = self.downloader.download(self.url, progress_callback=progress)
        self.assertEqual(result, output.resolve())
        self.assertEqual(client.extract_info.call_count, 3)
        self.assertEqual([o["continuedl"] for o in options], [True, True, False])
        self.assertEqual([o["http_chunk_size"] for o in options], [1048576, 1048576, 262144])
        self.assertTrue(all(o["retries"] == 5 and o["fragment_retries"] == 5 for o in options))
        self.assertTrue(all(not o["skip_unavailable_fragments"] for o in options))
        # The installed SDK invokes these callbacks with the keyword `n`.
        for settings in options:
            for callback in settings["retry_sleep_functions"].values():
                self.assertEqual(callback(n=0), 1)
                self.assertEqual(callback(n=10), 3)
        self.assertEqual(progress.call_args.args[0], 1.0)
        self.assertEqual(sum("/3" in call.args[1] for call in progress.call_args_list), 2)

    def test_retry_exhaustion_keeps_partial_and_reports_network_not_cookies(self):
        partial = Path(self.directory.name) / "youtube_BaW_jenozKc.mp4.part"
        partial.write_bytes(b"partial-data")
        with patch("downloader.yt_dlp.YoutubeDL") as factory, patch("downloader.time.sleep"):
            client = factory.return_value.__enter__.return_value
            client.extract_info.side_effect = DownloadError("\x1b[0;31mERROR\x1b[0m: 2000 bytes read, 3000 more expected")
            with self.assertRaises(RuntimeError) as caught:
                self.downloader.download(self.url)
        self.assertEqual(factory.call_count, 3)
        self.assertNotIn("\x1b", str(caught.exception))
        self.assertNotIn("cookie", str(caught.exception))
        self.assertIn("3", str(caught.exception))
        self.assertEqual(partial.read_bytes(), b"partial-data")

    def test_private_video_does_not_retry_as_network_failure(self):
        with patch("downloader.yt_dlp.YoutubeDL") as factory:
            factory.return_value.__enter__.return_value.extract_info.side_effect = DownloadError("Private video. Sign in")
            with self.assertRaisesRegex(RuntimeError, "cookie"):
                self.downloader.download(self.url)
        self.assertEqual(factory.call_count, 1)

    def test_cancel_during_retry_wait_prevents_next_attempt(self):
        event = threading.Event()
        self.downloader.cancel_event = event
        def report(fraction, message):
            if "/3" in message:
                event.set()
        with patch("downloader.yt_dlp.YoutubeDL") as factory:
            factory.return_value.__enter__.return_value.extract_info.side_effect = DownloadError("Read timed out")
            with self.assertRaises(JobCancelled):
                self.downloader.download(self.url, progress_callback=report)
        self.assertEqual(factory.call_count, 1)


if __name__ == "__main__":
    unittest.main()
