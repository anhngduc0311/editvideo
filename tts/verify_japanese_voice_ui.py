"""Build the real UI and check preset selection, preview and persistence."""
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "douyin_editor"))
import app_gui
from config import VOICE_PRESETS

preset = VOICE_PRESETS["japanese_minecraft_clone"]
with tempfile.TemporaryDirectory() as directory:
    with patch.object(app_gui, "CONFIG_FILE", Path(directory) / "settings.json"):
        app = app_gui.DouyinEditorApp()
        app.withdraw()
        try:
            assert preset["name"] in app.cmb_voice.cget("values")
            app.cmb_voice.set(preset["name"])
            app._on_voice_changed(preset["name"])
            assert "tiếng Nhật" in app.lbl_voice_hint.cget("text")
            app._save_settings()
            app._load_saved_settings()
            assert app.saved_voice == preset["name"]
            with patch("winsound.PlaySound") as play:
                app.after(0, app._preview_voice_clicked)
                # Let the worker post Tk callbacks while a real event loop runs.
                def check_done():
                    if app.btn_preview_voice.cget("state") == "normal":
                        app.quit()
                    else:
                        app.after(50, check_done)
                app.after(100, check_done)
                app.after(10000, app.quit)
                app.mainloop()
                assert play.called, app.log_textbox.get("1.0", "end")
            assert app.btn_preview_voice.cget("state") == "normal"
            print("PASS: GUI voice dropdown, Japanese hint, saved selection and clone preview playback")
        finally:
            app.destroy()
