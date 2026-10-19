"""Regression checks for incomplete speech, timeline safety, resume and credentials."""
from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import PipelineConfig, TTSConfig
from pydub import AudioSegment
from pydub.generators import Sine
from credential_store import seal_secrets, open_secrets
from job_state import JobState, JobCancelled, check_cancelled
from pipeline import DouyinAutoPipeline
from subtitle_review import validate_translation
from transcriber import SubtitleItem
from translator import parse_srt_string
from tts_synchronizer import VietnameseTTSSynchronizer, TTSTimingError, format_timestamp
from preprocessor import run_ffmpeg_with_progress
from compositor import VideoCompositor


def phrase(index, start, end, text):
    return SubtitleItem(index, start, end, format_timestamp(start), format_timestamp(end), text)


def audio_bytes(duration=400, frequency=440):
    buffer = io.BytesIO()
    Sine(frequency).to_audio_segment(duration=duration).export(buffer, format="wav")
    return buffer.getvalue()


class SpeechReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.engine = Mock()
        with patch("tts_synchronizer.create_tts_engine", return_value=self.engine):
            self.sync = VietnameseTTSSynchronizer(PipelineConfig(deepseek_api_key="test"))
        self.items = [phrase(1, 0, 1, "First."), phrase(2, 1, 2, "Second.")]

    def run_sync(self, items=None, duration=2):
        return self.sync.generate_and_sync(items or self.items, duration,
                                            self.directory / "audio.wav", self.directory / "speech.srt")

    def test_missing_phrase_retries_only_that_phrase_and_cache_survives(self):
        data = audio_bytes()
        self.engine.synthesize_phrases.side_effect = [
            [("First.", data, 400)], [("Second.", None, 0)], [("Second.", data, 400)]]
        path, items = self.run_sync()
        self.assertEqual([s.text for s in items], ["First.", "Second."])
        calls = self.engine.synthesize_phrases.call_args_list
        self.assertEqual([c.kwargs["texts"] for c in calls],
                         [["First.", "Second."], ["Second."], ["Second."]])
        self.engine.synthesize_phrases.reset_mock()
        self.run_sync()
        self.engine.synthesize_phrases.assert_not_called()
        self.assertEqual(len(AudioSegment.from_file(io.BytesIO(path.read_bytes()), format="wav")), 2000)

    def test_reordered_response_uses_text_identity(self):
        self.engine.synthesize_phrases.return_value = [
            ("Second.", audio_bytes(600), 600), ("First.", audio_bytes(300), 300)]
        _, items = self.run_sync()
        self.assertAlmostEqual(items[0].end_seconds, 0.3)
        self.assertAlmostEqual(items[1].end_seconds, 1.6)

    def test_permanent_failure_does_not_export_partial_speech(self):
        self.engine.synthesize_phrases.return_value = [("First.", audio_bytes(), 400)]
        with self.assertRaisesRegex(RuntimeError, "2"):
            self.run_sync()
        self.assertFalse((self.directory / "audio.wav").exists())
        self.assertFalse((self.directory / "speech.srt").exists())

    def test_corrupt_audio_is_retried(self):
        self.engine.synthesize_phrases.side_effect = [
            [("First.", b"broken", 400)], [("First.", audio_bytes(), 400)]]
        _, items = self.run_sync([self.items[0]])
        self.assertEqual(len(items), 1)
        self.assertEqual(self.engine.synthesize_phrases.call_count, 2)

    def test_overflow_stops_instead_of_drifting_or_cutting(self):
        self.engine.synthesize_phrases.return_value = [("First.", audio_bytes(1900), 1900),
                                                       ("Second.", audio_bytes(), 400)]
        with self.assertRaises(TTSTimingError):
            self.run_sync()
        self.assertFalse((self.directory / "audio.wav").exists())

    def test_last_phrase_cannot_extend_past_video(self):
        self.engine.synthesize_phrases.return_value = [("Second.", audio_bytes(1900), 1900)]
        with self.assertRaises(TTSTimingError):
            self.run_sync([self.items[1]])

    def test_small_overflow_fits_without_moving_next_phrase(self):
        self.engine.synthesize_phrases.return_value = [("First.", audio_bytes(1100), 1100),
                                                       ("Second.", audio_bytes(), 400)]
        path, items = self.run_sync()
        self.assertLessEqual(items[0].end_seconds, 1)
        self.assertEqual(items[1].start_seconds, 1)
        self.assertEqual(len(AudioSegment.from_file(io.BytesIO(path.read_bytes()), format="wav")), 2000)

    def test_cancellation_stops_before_provider_request(self):
        self.sync.cancel_event = threading.Event()
        self.sync.cancel_event.set()
        with self.assertRaises(JobCancelled):
            self.run_sync()
        self.engine.synthesize_phrases.assert_not_called()


class CheckpointTests(unittest.TestCase):
    def test_changed_input_or_output_invalidates_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            state = JobState(directory)
            output = Path(directory) / "output.txt"
            output.write_text("complete")
            state.complete("stage", ["voice1"], [output])
            self.assertEqual(JobState(directory).outputs("stage", ["voice1"]), [output])
            self.assertIsNone(state.outputs("stage", ["voice2"]))
            output.write_text("modified output")
            self.assertIsNone(state.outputs("stage", ["voice1"]))

    def test_corrupt_manifest_recovers(self):
        with tempfile.TemporaryDirectory() as directory:
            for content in ("broken", "[]", "null"):
                (Path(directory) / "job_state.json").write_text(content)
                self.assertIsNone(JobState(directory).outputs("stage", []))


class PipelineResumeTests(unittest.TestCase):
    def test_render_failure_resumes_and_review_edits_reach_tts(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            config = PipelineConfig(deepseek_api_key="test", speed_factor=1,
                                    work_dir=root / "work", download_dir=root / "downloads",
                                    output_dir=root / "output")
            for name in ("DouyinDownloader", "VideoPreprocessor", "WhisperTranscriber",
                         "create_translator", "SubtitleBurner", "VocalSeparator",
                         "VietnameseTTSSynchronizer", "VideoCompositor"):
                stack.enter_context(patch("pipeline." + name))
            stack.enter_context(patch("pipeline.console"))
            pipeline = DouyinAutoPipeline(config)
            pipeline.translator.model_name = "test-model"
            pipeline.tts_syncer.engine = object()
            raw = root / "video.mp4"
            raw.write_bytes(b"video")
            pipeline.downloader.download.return_value = raw
            pipeline.preprocessor.get_video_info.return_value = {"width": 640, "height": 360, "duration": 3}
            def extract(**kwargs):
                kwargs["output_audio"].write_bytes(b"audio")
            pipeline.preprocessor.extract_slowed_original_audio.side_effect = extract
            original = phrase(1, 0, 2, "Hello.").to_srt_block()
            translated = phrase(1, 0, 2, "Xin chào.").to_srt_block()
            def transcribe(**kwargs):
                kwargs["output_srt"].write_text(original, encoding="utf-8")
            pipeline.transcriber.transcribe.side_effect = transcribe
            def translate(**kwargs):
                kwargs["output_srt_path"].write_text(translated, encoding="utf-8")
            pipeline.translator.translate_srt.side_effect = translate
            def review(directory, path):
                path.write_text(translated.replace("Xin chào.", "Chào bạn."), encoding="utf-8")
            def synthesize(**kwargs):
                self.assertEqual(kwargs["subtitles"][0].text, "Chào bạn.")
                kwargs["output_audio_path"].write_bytes(b"speech")
                kwargs["output_srt_path"].write_text(translated, encoding="utf-8")
            pipeline.tts_syncer.generate_and_sync.side_effect = synthesize
            pipeline.compositor.render_single_pass_master.side_effect = RuntimeError("render failed")
            with self.assertRaisesRegex(RuntimeError, "render failed"):
                pipeline.run("https://youtu.be/BaW_jenozKc", review_subtitles_callback=review)
            def render(**kwargs):
                kwargs["output_path"].write_bytes(b"finished video")
                return kwargs["output_path"]
            pipeline.compositor.render_single_pass_master.side_effect = render
            final = pipeline.run("https://youtu.be/BaW_jenozKc", review_subtitles_callback=review)
            self.assertTrue(final.exists())
            for action in (pipeline.downloader.download, pipeline.transcriber.transcribe,
                           pipeline.translator.translate_srt, pipeline.tts_syncer.generate_and_sync):
                self.assertEqual(action.call_count, 1)
            self.assertEqual(pipeline.compositor.render_single_pass_master.call_count, 2)
            config.final_speed = 1.4
            pipeline.run("https://youtu.be/BaW_jenozKc", review_subtitles_callback=review)
            self.assertEqual(pipeline.compositor.render_single_pass_master.call_count, 3)
            self.assertEqual(pipeline.translator.translate_srt.call_count, 1)
            self.assertEqual(pipeline.tts_syncer.generate_and_sync.call_count, 1)


class SecurityAndReviewTests(unittest.TestCase):
    def test_credentials_default_empty_and_are_not_in_config_repr(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(PipelineConfig().deepseek_api_key, "")
        self.assertNotIn("secret-value", repr(PipelineConfig(deepseek_api_key="secret-value")))

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI")
    def test_credentials_roundtrip_without_plaintext(self):
        secrets = {"deepseek_api_key": "test-only-secret", "chatgpt_cookie": "test-cookie"}
        sealed = seal_secrets(secrets)
        self.assertTrue(sealed)
        self.assertNotIn("test-only-secret", sealed)
        self.assertEqual(open_secrets(sealed), secrets)
        self.assertEqual(open_secrets("corrupt-token"), {})

    def test_review_rejects_missing_or_retimed_subtitles(self):
        original = phrase(1, 0, 2, "Hello.").to_srt_block()
        self.assertEqual(validate_translation(original, original)[0].text, "Hello.")
        for invalid in ("", phrase(1, 0, 3, "Hello.").to_srt_block()):
            with self.assertRaises(ValueError):
                validate_translation(original, invalid)

    def test_cancelled_ffmpeg_exits_without_hanging(self):
        event = threading.Event()
        timer = threading.Timer(0.3, event.set)
        timer.start()
        try:
            with self.assertRaises(JobCancelled):
                run_ffmpeg_with_progress(
                    ["ffmpeg", "-y", "-re", "-f", "lavfi", "-i", "sine=frequency=440",
                     "-t", "30", "-f", "null", "-"], 30, cancel_event=event)
        finally:
            timer.cancel()


class RenderIntegrationTests(unittest.TestCase):
    def test_empty_synced_srt_falls_back_to_translated_captions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            synced, translated = root / "synced.srt", root / "translated.srt"
            translated.write_text(phrase(1, 0, 1, "Xin chào!").to_srt_block(), encoding="utf-8")
            for content in ("\r\n", "", "invalid SRT", "\ufeff\n"):
                synced.write_text(content, encoding="utf-8")
                self.assertEqual(DouyinAutoPipeline._select_render_subtitles(synced, translated), translated)
            synced.write_text(translated.read_text(encoding="utf-8"), encoding="utf-8")
            self.assertEqual(DouyinAutoPipeline._select_render_subtitles(synced, translated), synced)
            translated.write_text("\n")
            synced.write_text("\n")
            with self.assertRaises(RuntimeError):
                DouyinAutoPipeline._select_render_subtitles(synced, translated)

    def test_enabled_but_empty_captions_fail_before_render(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw, speech, srt = root / "raw.mp4", root / "speech.wav", root / "subs.srt"
            raw.write_bytes(b"source")
            speech.write_bytes(b"audio")
            srt.write_text("\r\n")
            for blur in (True, False):
                config = PipelineConfig()
                config.blur_region.enabled = blur
                with patch("compositor.run_ffmpeg_with_progress") as render:
                    with self.assertRaises(RuntimeError):
                        VideoCompositor(config).render_single_pass_master(raw, srt, speech, None,
                                                                          root / "out.mp4", 1)
                    render.assert_not_called()

    def test_caption_pixels_are_visible_with_blur_on_and_off(self):
        from PIL import Image, ImageChops
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw, speech, srt = root / "raw.mp4", root / "speech.wav", root / "subs.srt"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                            "color=c=blue:s=640x360:r=25", "-t", "1", "-c:v", "libx264",
                            str(raw)], capture_output=True, check=True, timeout=15)
            with speech.open("wb") as stream:
                AudioSegment.silent(duration=1000).export(stream, format="wav")
            srt.write_text(phrase(1, 0, 1, "Phụ đề tiếng Việt").to_srt_block(), encoding="utf-8")
            for blur in (True, False):
                frames = []
                for captions in (False, True):
                    config = PipelineConfig(speed_factor=1, final_speed=1, export_resolution="original",
                                            enable_subtitles=captions)
                    config.blur_region.enabled = blur
                    config.blur_region.smart_blur = False
                    config.blur_region.x, config.blur_region.y = 10, 10
                    config.blur_region.width, config.blur_region.height = 100, 40
                    output = root / f"out_{blur}_{captions}.mp4"
                    VideoCompositor(config).render_single_pass_master(raw, srt, speech, None,
                                                                      output, 1, 640, 360)
                    result = subprocess.run(["ffmpeg", "-v", "error", "-ss", "0.5", "-i", str(output),
                                             "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "pipe:1"],
                                            capture_output=True, check=True, timeout=15)
                    frames.append(Image.open(io.BytesIO(result.stdout)).convert("RGB"))
                difference = ImageChops.difference(frames[0], frames[1]).crop((0, 190, 640, 360))
                self.assertIsNotNone(difference.getbbox(), f"Captions invisible with blur={blur}")

    def test_real_render_keeps_final_spoken_audio_and_subtitle_timing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw, speech, srt, output = [root / name for name in ("raw.mp4", "speech.wav", "speech.srt", "final.mp4")]
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                            "color=c=blue:s=160x90:r=25", "-t", "2", "-c:v", "libx264",
                            "-pix_fmt", "yuv420p", str(raw)], check=True, capture_output=True, timeout=20)
            track = AudioSegment.silent(duration=2000, frame_rate=44100).overlay(
                Sine(440).to_audio_segment(duration=350), position=1600)
            with speech.open("wb") as stream:
                track.export(stream, format="wav")
            srt.write_text(phrase(1, 1.6, 1.95, "Hello.").to_srt_block(), encoding="utf-8")
            config = PipelineConfig(deepseek_api_key="test", speed_factor=1, final_speed=1.2,
                                    export_resolution="original")
            config.blur_region.enabled = False
            compositor = VideoCompositor(config)
            compositor.render_single_pass_master(raw, srt, speech, None, output, 2, 160, 90)
            probe = subprocess.run(["ffprobe", "-v", "quiet", "-show_format", "-show_streams",
                                    "-of", "json", str(output)], capture_output=True, check=True, timeout=15)
            info = json.loads(probe.stdout)
            self.assertGreaterEqual(float(info["format"]["duration"]), 1.6)
            self.assertEqual({s["codec_type"] for s in info["streams"]}, {"video", "audio"})
            decoded = subprocess.run(["ffmpeg", "-v", "error", "-i", str(output), "-vn",
                                      "-f", "wav", "pipe:1"], capture_output=True, check=True, timeout=15)
            audio = AudioSegment.from_file(io.BytesIO(decoded.stdout), format="wav")
            self.assertGreater(audio[-250:].rms, 100)
            scaled = parse_srt_string((root / "final_scaled_1.2x.srt").read_text(encoding="utf-8"))
            self.assertAlmostEqual(scaled[0].start_seconds, 1.6 / 1.2, places=2)


if __name__ == "__main__":
    unittest.main()
