from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import BlurRegion, PipelineConfig
from pipeline import DouyinAutoPipeline
from roi_selector import VisualROISelectorDialog


class BlurDisabledTests(unittest.TestCase):
    def test_pipeline_skips_roi_callback_when_blur_disabled(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled), tempfile.TemporaryDirectory() as directory, patch("pipeline.console"), patch("pipeline.tqdm"):
                root = Path(directory)
                config = PipelineConfig(work_dir=root / "work", blur_region=BlurRegion(enabled=enabled),
                                        output_dir=root / "output", download_dir=root / "downloads", models_dir=root / "models")
                config.setup_directories()
                final = root / "output" / "final.mp4"
                final.write_bytes(b"fake video")
                pipeline = DouyinAutoPipeline.__new__(DouyinAutoPipeline)
                pipeline.config = config
                pipeline.print_pipeline_banner = Mock()
                pipeline.downloader = Mock()
                pipeline.downloader.detect_source.return_value = "youtube"
                pipeline.downloader.download.return_value = root / "raw.mp4"
                pipeline.preprocessor = Mock()
                pipeline.preprocessor.get_video_info.return_value = {"width": 1280, "height": 720}
                pipeline.preprocessor.extract_audio_for_stt.return_value = 10
                pipeline.transcriber = Mock()
                pipeline.translator = Mock(model_name="test")
                pipeline.translator.translate_srt.return_value = ["translated"]
                pipeline.separator = Mock()
                pipeline.separator.process.return_value = None
                pipeline.tts_syncer = Mock()
                pipeline.tts_syncer.generate_and_sync.return_value = (root / "tts.wav", ["synced"])
                pipeline.compositor = Mock()
                pipeline.compositor.render_single_pass_master.return_value = final
                callback = Mock(return_value=BlurRegion(enabled=True))
                result = pipeline.run("https://youtu.be/jNQXAC9IVRw", interactive_roi_callback=callback)
                self.assertEqual(result, final)
                self.assertEqual(callback.call_count, int(enabled))
                self.assertEqual(config.blur_region.enabled, enabled)

    def test_saving_region_does_not_enable_disabled_blur(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                dialog = SimpleNamespace(
                    orig_image=SimpleNamespace(size=(1280, 720)),
                    roi_x=0, roi_y=500, roi_w=1280, roi_h=150,
                    blur_region=BlurRegion(enabled=enabled), on_save_callback=Mock(), destroy=Mock(),
                )
                VisualROISelectorDialog._save_and_close(dialog)
                self.assertEqual(dialog.on_save_callback.call_args.args[0].enabled, enabled)
                dialog.destroy.assert_called_once()


if __name__ == "__main__":
    unittest.main()
