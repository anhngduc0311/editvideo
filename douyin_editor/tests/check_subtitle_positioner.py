"""Exercise the real preview dialog using a synthetic video and subtitle file."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import customtkinter as ctk
from config import SubtitleStyle
from subtitle_positioner import SubtitlePositionDialog

with tempfile.TemporaryDirectory() as directory:
    root_path = Path(directory)
    video, subtitles = root_path / "video.mp4", root_path / "subtitles.srt"
    subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-f", "lavfi", "-i", "color=c=0x13263c:s=640x360:d=2",
                    "-c:v", "libx264", "-preset", "ultrafast", str(video)], check=True, timeout=20)
    subtitles.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello everyone!\n", encoding="utf-8")
    root = ctk.CTk()
    root.withdraw()
    try:
        original = SubtitleStyle()
        applied, skipped = Mock(), Mock()
        dialog = SubtitlePositionDialog(root, video, subtitles, original, on_apply=applied, on_skip=skipped)
        assert dialog._preview is not None and dialog.btn_apply.cget("state") == "normal"
        dialog._bounds = (0, 0, 1000, 500)
        event = SimpleNamespace(x=250, y=150)
        dialog._mouse_down(event)
        dialog._mouse_up(event)
        assert dialog.style.position_x == 0.25 and dialog.style.position_y == 0.3
        dialog._change_size("24")
        assert original.position_x is None
        temporary = dialog.directory
        dialog._apply()
        assert applied.call_args.args[0].position_x == 0.25
        assert applied.call_args.args[0].font_size == 24
        assert not temporary.exists()
        skipped.assert_not_called()
        dialog = SubtitlePositionDialog(root, video, subtitles, original, on_apply=applied, on_skip=skipped)
        dialog._preset(0.5)
        dialog._skip()
        skipped.assert_called_once()
        assert original.position_y is None
        assert applied.call_count == 1
        print("PASS: real FFmpeg preview, drag, font size, apply, skip and cleanup")
    finally:
        root.destroy()
