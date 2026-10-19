"""Exercise the actual Tk layout without network calls or rendering video."""
from pathlib import Path
import sys
import tempfile
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app_gui

with tempfile.TemporaryDirectory() as directory:
    with patch.object(app_gui, "CONFIG_FILE", Path(directory) / "settings.json"):
        app = app_gui.DouyinEditorApp()
        try:
            for size in ("1240x860", "1120x720"):
                app.geometry(size)
                app.update()
                for name in ("Nguồn video", "Hình ảnh", "Âm thanh", "Phụ đề"):
                    app.settings_tabs.set(name)
                    app.update()
                    assert app.btn_run.winfo_viewable()
                    assert app.log_textbox.winfo_height() > 60
                    assert app.btn_run.winfo_rooty() + app.btn_run.winfo_height() <= app.winfo_rooty() + app.winfo_height()
                    if "--capture" in sys.argv and size == "1240x860" and name == "Nguồn video":
                        from PIL import ImageGrab
                        app.after(200)
                        app.update()
                        x, y = app.winfo_rootx(), app.winfo_rooty()
                        ImageGrab.grab(bbox=(x, y, x + app.winfo_width(), y + app.winfo_height())).save(
                            Path(__file__).resolve().parents[2] / "state" / "gui-preview.png"
                        )
                    print(size, name.encode("ascii", "replace").decode(), "OK")
            app._update_step_status(3, 8, "Speech recognition", "Working")
            app.update()
            assert app.lbl_progress.cget("text") == "38%"
            app._update_step_status(-1, 8, "Test failure", "Details")
            app.update()
            assert "Lỗi" in app.lbl_session_status.cget("text")
            app._update_step_status(8, 8, "Done", "Export complete")
            app.update()
            assert app.lbl_progress.cget("text") == "100%"
            for preset_id in app_gui.SUBTITLE_PRESETS:
                app._select_subtitle_preset(preset_id)
                assert app.sub_preset_buttons[preset_id].cget("border_width") == 3
            mode = "Tiếng Anh → Tiếng Nhật"
            app.cmb_translation_mode.set(mode)
            app._on_translation_changed(mode)
            assert app_gui.get_tts_language(app.cmb_voice.get()) == "ja"
            assert app.cmb_font.get() == "Meiryo"
            app.url_textbox.insert("1.0", "https://youtu.be/BaW_jenozKc")
            app.chk_interactive_roi.deselect()
            app.key_entry.delete(0, "end")
            app.key_entry.insert(0, "test-key")
            with patch.object(app_gui, "DouyinAutoPipeline") as factory, patch.object(app_gui.threading, "Thread") as thread, patch.object(app_gui.messagebox, "showinfo"):
                factory.return_value.run.return_value = Path(directory) / "output_ja.mp4"
                thread.side_effect = lambda target, daemon: Mock(start=target)
                app._start_pipeline()
                app.update()
                config = factory.call_args.kwargs["config"]
                assert config.whisper_language == "en"
                assert config.target_language == "ja"
                assert app_gui.get_tts_language(config.tts_config.voice) == "ja"
                assert config.cookie_config.cookie_str is None
            app._load_saved_settings()
            assert app.saved_translation_mode == mode
            assert app_gui.get_tts_language(app.saved_voice) == "ja"
            print("PASS: layouts and progress states")
        finally:
            app.destroy()
