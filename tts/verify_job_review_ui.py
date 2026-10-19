"""Check the actual review dialog, cancel control and encrypted settings offline."""
from pathlib import Path
import json
import sys
import tempfile
import threading
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "douyin_editor"))
import app_gui
from subtitle_review import SubtitleReviewDialog


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    with patch.object(app_gui, "CONFIG_FILE", root / "settings.json"):
        app = app_gui.DouyinEditorApp()
        app.withdraw()
        try:
            assert app.chk_review_translation.get()
            assert app.chk_resume.get()
            assert app.btn_cancel.cget("state") == "disabled"
            app.chk_enable_subtitles.select()
            app._on_enable_subtitles_toggled()
            app.chk_blur.deselect()
            app._on_blur_toggled()
            assert not app.current_blur_region.enabled
            assert app.chk_enable_subtitles.get()
            assert app.btn_open_roi_selector.cget("state") == "normal"
            assert app.chk_interactive_roi.cget("state") == "normal"
            app._load_saved_settings()
            assert not app.saved_blur_enabled
            assert app.saved_enable_subtitles
            app.chk_blur.select()
            app._on_blur_toggled()
            assert app.chk_enable_subtitles.get()
            app.key_entry.delete(0, "end")
            app.key_entry.insert(0, "test-secret-only")
            app._save_settings()
            settings = json.loads((root / "settings.json").read_text(encoding="utf-8"))
            assert "deepseek_api_key" not in settings
            assert "test-secret-only" not in json.dumps(settings)
            app._load_saved_settings()
            assert app.saved_deepseek_key == "test-secret-only"
            original = root / "original_subtitles.srt"
            translated = root / "translated.srt"
            original.write_text("1\n00:00:00,000 --> 00:00:02,000\nHello!\n", encoding="utf-8")
            translated.write_text("1\n00:00:00,000 --> 00:00:02,000\nXin chào!\n", encoding="utf-8")
            done = threading.Event()
            event = threading.Event()
            dialog = SubtitleReviewDialog(app, original, translated, event, done)
            dialog.withdraw()
            dialog.editor.delete("1.0", "end")
            dialog.editor.insert("1.0", "1\n00:00:00,000 --> 00:00:02,000\nChào bạn!\n")
            dialog.approve()
            assert done.is_set() and not event.is_set()
            assert "Chào bạn!" in translated.read_text(encoding="utf-8")
            done.clear()
            dialog = SubtitleReviewDialog(app, original, translated, event, done)
            dialog.withdraw()
            dialog.cancel()
            assert done.is_set() and event.is_set()
            app.is_running = True
            app.cancel_event.clear()
            app._cancel_pipeline()
            assert app.cancel_event.is_set()
            app.is_running = False
            print("PASS: review edit/save, cancel and encrypted settings in real GUI")
        finally:
            app.destroy()
