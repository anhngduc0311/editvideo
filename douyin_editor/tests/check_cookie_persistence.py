"""Exercise actual GUI save, close, restore and forget with isolated settings."""
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app_gui
from cookie_storage import unprotect_cookies


def open_app():
    app = app_gui.DouyinEditorApp()
    app.withdraw()
    return app


def cancel_callbacks(app):
    # Several root lifetimes in one interpreter are specific to this test.
    for callback in app.tk.splitlist(app.tk.call("after", "info")):
        app.tk.call("after", "cancel", callback)


def close_app(app):
    cancel_callbacks(app)
    app.destroy()


with tempfile.TemporaryDirectory() as directory, patch.object(app_gui, "CONFIG_FILE", Path(directory) / "settings.json"):
    app = open_app()
    try:
        app.seg_provider.set("Gemini Cookie")
        app._on_provider_changed("Gemini Cookie")
        app.key_entry.insert(0, "__Secure-1PSID=private-session; __Secure-1PSIDTS=private-timestamp")
        app.btn_save_gemini_cookie.invoke()
        settings = app_gui.CONFIG_FILE.read_text(encoding="utf-8")
        assert "private-session" not in settings and "private-timestamp" not in settings
        assert unprotect_cookies(json.loads(settings)["gemini_cookie_protected"]) == ("private-session", "private-timestamp")
        assert "Đã lưu" in app.lbl_cookie_storage_status.cget("text")
    finally:
        close_app(app)

    app = open_app()
    try:
        assert app._selected_provider() == "gemini_web"
        assert app.key_entry.get() == "private-session"
        assert app.gemini_psidts_entry.get() == "private-timestamp"
        assert app.key_entry.cget("show") == "•"
        # Edits must also persist on normal window close without pressing Save.
        app.gemini_psidts_entry.delete(0, "end")
        app.gemini_psidts_entry.insert(0, "updated-timestamp")
        with patch.object(app_gui.messagebox, "showerror") as error:
            cancel_callbacks(app)
            app._on_close()
            error.assert_not_called()
    except BaseException:
        close_app(app)
        raise

    app = open_app()
    try:
        assert app.gemini_psidts_entry.get() == "updated-timestamp"
        # A failed disk write must preserve the last valid encrypted settings.
        before = app_gui.CONFIG_FILE.read_bytes()
        with patch.object(app_gui.os, "replace", side_effect=OSError("disk unavailable")):
            assert app._save_settings() is False
        assert app_gui.CONFIG_FILE.read_bytes() == before
        assert not list(Path(directory).glob("*.tmp"))
        app._forget_gemini_cookie_clicked()
        assert "gemini_cookie_protected" not in json.loads(app_gui.CONFIG_FILE.read_text(encoding="utf-8"))
        assert not app.key_entry.get() and not app.gemini_psidts_entry.get()
    finally:
        close_app(app)

    app = open_app()
    try:
        assert not app.key_entry.get() and not app.gemini_psidts_entry.get()
        print("PASS: encrypted cookie save, GUI reopen, autosave on close, atomic failure and forget")
    finally:
        close_app(app)
