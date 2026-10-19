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
    subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=640x360:d=1",
                    "-f", "lavfi", "-i", "color=c=blue:s=640x360:d=1", "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0",
                    "-c:v", "libx264", "-preset", "ultrafast", str(video)], check=True, timeout=20)
    subtitles.write_text("1\n00:00:00,000 --> 00:00:01,000\nXin chào!\n\n2\n00:00:02,000 --> 00:00:04,000\nCâu dịch thứ hai.\n", encoding="utf-8")
    root = ctk.CTk()
    root.withdraw()
    try:
        original = SubtitleStyle()
        applied, skipped = Mock(), Mock()
        dialog = SubtitlePositionDialog(root, video, subtitles, original, speed_factor=0.5, on_apply=applied, on_skip=skipped)
        assert dialog._preview is not None and dialog.btn_apply.cget("state") == "normal"
        assert abs(dialog.duration - 2.0) < 0.1
        assert dialog._preview.getpixel((10, 10))[0] > 200  # first red scene
        assert dialog.current_subtitle_text == "Xin chào!"
        position = (dialog.style.position_x, dialog.style.position_y)
        dialog._seek_to(1.3)
        assert dialog._preview.getpixel((10, 10))[2] > 200  # later blue scene
        assert dialog.current_subtitle_text == "Câu dịch thứ hai."
        assert dialog.cue.get() == dialog.cue_values[1]
        assert (dialog.style.position_x, dialog.style.position_y) == position
        dialog._seek_to(0.5)
        assert dialog.current_subtitle_text == ""  # first cue ends; don't repeat it into the gap
        assert dialog.btn_apply.cget("state") == "normal"
        dialog._seek_to(0.75)
        assert dialog.current_subtitle_text == ""
        dialog._on_cue_selected(dialog.cue_values[1])
        assert dialog.seek_time == 1.0  # translated timeline 2s -> source timeline 1s
        assert dialog.current_subtitle_text == "Câu dịch thứ hai."
        dialog._seek_to(-5)
        assert dialog.seek_time == 0
        assert dialog._preview.getpixel((10, 10))[0] > 200
        assert dialog.current_subtitle_text == "Xin chào!"
        dialog._seek_to(999)
        assert 0 <= dialog.seek_time < dialog.duration
        assert dialog._preview.getpixel((10, 10))[2] > 200
        dialog._on_seek(0.2)
        previous = dialog._seek_after
        dialog._on_seek(1.2)
        assert previous not in root.tk.splitlist(root.tk.call("after", "info"))
        root.after(800, root.quit)
        root.mainloop()
        assert dialog._seek_after is None
        assert dialog._preview.getpixel((10, 10))[2] > 200
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
        dialog._on_seek(0.5)
        pending = dialog._seek_after
        dialog._skip()
        assert pending not in root.tk.splitlist(root.tk.call("after", "info"))
        skipped.assert_called_once()
        assert original.position_y is None
        assert applied.call_count == 1
        print("PASS: real translated cues follow seeking, silent gaps, speed mapping, cue jumps, position and cleanup")
    finally:
        root.destroy()
