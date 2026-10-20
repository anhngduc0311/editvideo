"""Sequential queue behavior without downloads or provider calls."""
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import PipelineConfig
from job_state import JobCancelled
from video_queue import extract_video_urls, run_video_queue


class VideoQueueTests(unittest.TestCase):
    def setUp(self):
        self.urls = ["https://www.youtube.com/watch?v=first&list=PLtest&index=4",
                     "https://youtu.be/second", "https://v.douyin.com/third/"]
        self.config = PipelineConfig()

    def test_paste_extracts_all_links_in_order_preserving_queries(self):
        pasted = "Video 1: " + self.urls[0] + "\n" + self.urls[1] + "\n" + self.urls[2]
        self.assertEqual(extract_video_urls(pasted), self.urls)
        self.assertEqual(extract_video_urls(pasted + "\n" + self.urls[0]), self.urls)
        self.assertEqual(extract_video_urls("(" + self.urls[1] + ")."), [self.urls[1]])

    def test_invalid_and_lookalike_hosts_do_not_start_queue(self):
        for text in ("", "no link", "https://youtube.com.evil.test/video", "https://example.com/video"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                extract_video_urls(text)

    def test_jobs_finish_sequentially_with_isolated_settings_and_progress(self):
        events, progress, bound_callbacks = [], Mock(), []
        started, completed = Mock(), Mock()
        original_width = self.config.blur_region.width
        def factory(config):
            self.assertEqual(config.blur_region.width, original_width)
            config.blur_region.width = 12345
            def run(**kwargs):
                url = kwargs["douyin_url_or_text"]
                events.append(("start", url))
                bound_callbacks.append(kwargs["progress_callback"])
                kwargs["progress_callback"](1, 8, "Download", "Working")
                events.append(("end", url))
                return Path(f"output/{len(events)}.mp4")
            return Mock(run=run)
        result = run_video_queue(self.urls, self.config, factory, progress_callback=progress,
                                 on_start=started, on_complete=completed)
        self.assertEqual(events, [event for url in self.urls for event in (("start", url), ("end", url))])
        self.assertEqual([url for url, _ in result.completed], self.urls)
        self.assertFalse(result.failed)
        self.assertEqual(self.config.blur_region.width, original_width)
        self.assertEqual(started.call_count, 3)
        self.assertEqual(completed.call_count, 3)
        self.assertEqual([call.args[:2] for call in progress.call_args_list], [(1, 3), (2, 3), (3, 3)])
        bound_callbacks[0](8, 8, "Done", "Finished")
        self.assertEqual(progress.call_args.args[:2], (1, 3))

    def test_failed_video_is_reported_and_next_video_runs(self):
        called, error = [], Mock()
        def run(**kwargs):
            url = kwargs["douyin_url_or_text"]
            called.append(url)
            if url == self.urls[1]:
                raise RuntimeError("Video unavailable")
            return Path("output/video.mp4")
        result = run_video_queue(self.urls, self.config, lambda **_: Mock(run=run), on_error=error)
        self.assertEqual(called, self.urls)
        self.assertEqual([url for url, _ in result.completed], [self.urls[0], self.urls[2]])
        self.assertEqual(result.failed, [(self.urls[1], "Video unavailable")])
        error.assert_called_once_with(2, 3, self.urls[1], "Video unavailable")

    def test_cancel_before_start_does_not_create_pipeline(self):
        event, factory = threading.Event(), Mock()
        event.set()
        with self.assertRaises(JobCancelled):
            run_video_queue(self.urls, self.config, factory, cancel_event=event)
        factory.assert_not_called()

    def test_cancel_during_video_never_starts_next_link(self):
        event, complete, error = threading.Event(), Mock(), Mock()
        def run(**kwargs):
            event.set()
            raise JobCancelled("Cancelled")
        factory = Mock(return_value=Mock(run=run))
        with self.assertRaises(JobCancelled):
            run_video_queue(self.urls, self.config, factory, cancel_event=event,
                            on_complete=complete, on_error=error)
        factory.assert_called_once()
        complete.assert_not_called()
        error.assert_not_called()

    def test_cancel_between_videos_keeps_completed_output(self):
        event, completed = threading.Event(), []
        def done(number, total, url, output):
            completed.append((url, output))
            event.set()
        factory = Mock(return_value=Mock(run=Mock(return_value=Path("output/first.mp4"))))
        with self.assertRaises(JobCancelled):
            run_video_queue(self.urls, self.config, factory, cancel_event=event, on_complete=done)
        factory.assert_called_once()
        self.assertEqual(completed, [(self.urls[0], Path("output/first.mp4"))])


if __name__ == "__main__":
    unittest.main()
