import io
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import PipelineConfig, SubtitleStyle
from subtitle_burner import SubtitleBurner
from subtitle_layout import positioned_subtitles
from subtitle_positioner import SubtitlePositionDialog
from translator import parse_srt_string

SRT = "1\n00:00:00,000 --> 00:00:01,000\nHELLO\n\n2\n00:00:01,000 --> 00:00:02,000\nNEXT\n"


class SubtitlePositionTests(unittest.TestCase):
    def test_cue_boundaries_and_source_speed_mapping(self):
        items = parse_srt_string(SRT)
        for speed in (0.5, 0.7, 1.0):
            for subtitle_time, expected in ((0, "HELLO"), (0.9, "HELLO"), (1, "NEXT"), (1.9, "NEXT"), (2, "")):
                with self.subTest(speed=speed, time=subtitle_time):
                    state = SimpleNamespace(items=items, seek_time=subtitle_time * speed, speed_factor=speed)
                    active = SubtitlePositionDialog._active_cues(state)
                    self.assertEqual("\n".join(item.text for _, item in active), expected)

    def test_default_layout_keeps_original_srt(self):
        with patch("subtitle_layout.subprocess.run") as run:
            self.assertEqual(positioned_subtitles(Path("original.srt"), SubtitleStyle(), Path("new.ass")), Path("original.srt"))
            run.assert_not_called()

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required")
    def test_real_renderer_places_subtitles_and_keeps_timing(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.srt"
            source.write_text(SRT, encoding="utf-8")
            for x, y in ((0.25, 0.3), (0.75, 0.7)):
                with self.subTest(position=(x, y)):
                    style = SubtitleStyle(font_size=20, position_x=x, position_y=y)
                    ass = positioned_subtitles(source, style, Path(directory) / "positioned.ass")
                    content = ass.read_text(encoding="utf-8")
                    self.assertEqual(len(re.findall(r"^Dialogue:", content, re.MULTILINE)), 2)
                    self.assertIn("0:00:00.00,0:00:01.00", content)
                    self.assertIn("0:00:01.00,0:00:02.00", content)
                    burner = SubtitleBurner(PipelineConfig(subtitle_style=style))
                    filters = f"subtitles='{burner._escape_ffmpeg_path(ass)}':force_style='{burner.build_force_style_string()}'"
                    result = subprocess.run([
                        shutil.which("ffmpeg"), "-v", "error", "-f", "lavfi", "-i", "color=c=0x13263c:s=640x360:d=1",
                        "-vf", filters, "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "pipe:1",
                    ], capture_output=True, check=True, timeout=20)
                    with Image.open(io.BytesIO(result.stdout)) as image:
                        pixels = np.asarray(image.convert("RGB"))
                    rows, columns = np.where(np.all(pixels > 210, axis=2))
                    self.assertGreater(len(rows), 10)
                    self.assertAlmostEqual(float(columns.mean()) / 640, x, delta=0.05)
                    self.assertAlmostEqual(float(rows.mean()) / 360, y, delta=0.05)


if __name__ == "__main__":
    unittest.main()
