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
                assert config.whisper_model_size == "base"
                assert config.stt_engine == "auto"
                assert app_gui.get_tts_language(config.tts_config.voice) == "ja"
                assert config.cookie_config.cookie_str is None
            app._load_saved_settings()
            assert app.saved_translation_mode == mode
            assert app.saved_stt_mode == "Nhanh · Faster Whisper base"
            assert app_gui.get_tts_language(app.saved_voice) == "ja"
            app.seg_provider.set("Gemini Cookie")
            app._on_provider_changed("Gemini Cookie")
            app.update()
            assert app.cookie_ts_row.winfo_manager() == "pack"
            assert app.key_entry.cget("show") == "•"
            app.key_entry.delete(0, "end")
            app.key_entry.insert(0, "__Secure-1PSID=private-psid; __Secure-1PSIDTS=private-psidts")
            app._save_settings()
            saved = app_gui.CONFIG_FILE.read_text(encoding="utf-8")
            assert '"llm_provider": "gemini_web"' in saved
            assert "private-psid" not in saved
            app.seg_provider.set("Gemini API")
            app._on_provider_changed("Gemini API")
            assert app.cookie_ts_row.winfo_manager() == ""
            assert "private-psid" not in app.key_entry.get()
            app.seg_provider.set("Gemini Cookie")
            app._on_provider_changed("Gemini Cookie")
            assert "private-psid" in app.key_entry.get()
            with patch.object(app_gui, "DouyinAutoPipeline") as factory, patch.object(app_gui.threading, "Thread") as thread, patch.object(app_gui.messagebox, "showinfo"):
                factory.return_value.run.return_value = Path(directory) / "output_cookie_ja.mp4"
                thread.side_effect = lambda target, daemon: Mock(start=target)
                app._start_pipeline()
                app.update()
                config = factory.call_args.kwargs["config"]
                assert config.llm_provider == "gemini_web"
                assert config.gemini_web_psid == "private-psid"
                assert config.gemini_web_psidts == "private-psidts"
                assert config.whisper_language == "en" and config.target_language == "ja"
                assert "private-psid" not in app.log_textbox.get("1.0", "end")
            with patch("gemini_cookie.GeminiCookieTranslator.check_status", return_value={"status": "ERROR", "message": "Session expired"}), patch.object(app_gui.threading, "Thread") as thread:
                thread.side_effect = lambda target, daemon: Mock(start=target)
                app._check_api_key_clicked()
                app.update()
                assert app.lbl_api_status.cget("text") == "Session expired"
                assert app.btn_check_key.cget("state") == "normal"
            app.chk_blur.deselect()
            app._on_blur_toggled()
            assert app.chk_interactive_roi.get() == 0
            assert app.chk_interactive_roi.cget("state") == "disabled"
            assert app.btn_open_roi_selector.cget("state") == "disabled"
            with patch.object(app_gui, "VisualROISelectorDialog") as dialog:
                app._open_visual_roi_selector()
                dialog.assert_not_called()
            # A stale/programmatic checkbox value must not open the dialog either.
            app.chk_interactive_roi.select()
            with patch.object(app_gui, "DouyinAutoPipeline") as factory, patch.object(app_gui.threading, "Thread") as thread, patch.object(app_gui.messagebox, "showinfo"):
                factory.return_value.run.return_value = Path(directory) / "no_blur.mp4"
                thread.side_effect = lambda target, daemon: Mock(start=target)
                app._start_pipeline()
                app.update()
                config = factory.call_args.kwargs["config"]
                assert config.blur_region.enabled is False
                assert config.blur_region is not app.current_blur_region
                assert factory.return_value.run.call_args.kwargs["interactive_roi_callback"] is None
            app.chk_blur.select()
            app._on_blur_toggled()
            assert app.chk_interactive_roi.cget("state") == "normal"
            assert app.btn_open_roi_selector.cget("state") == "normal"
            print("PASS: layouts and progress states")
        finally:
            app.destroy()
