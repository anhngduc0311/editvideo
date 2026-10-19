from pathlib import Path
import sys, tempfile, json
from unittest.mock import patch
sys.path.insert(0, "D:/edit1/edit2/editvideo/douyin_editor")
import app_gui
from config import TRANSLATION_MODES, VOICE_PRESETS
with tempfile.TemporaryDirectory() as directory:
    with patch.object(app_gui, "CONFIG_FILE", Path(directory) / "settings.json"):
        app = app_gui.DouyinEditorApp()
        app.withdraw()
        try:
            assert "Tiếng Anh → Tiếng Nhật" in app.cmb_translation_mode.cget("values")
            app.cmb_translation_mode.set("Tiếng Anh → Tiếng Nhật")
            app._on_translation_mode_changed("Tiếng Anh → Tiếng Nhật")
            assert app.cmb_voice.get() == VOICE_PRESETS["japanese_minecraft_clone"]["name"]
            app._load_saved_settings()
            assert app.saved_translation_mode == "Tiếng Anh → Tiếng Nhật"
            assert app.saved_voice == app.cmb_voice.get()
            app.cmb_voice.set(VOICE_PRESETS["co_gai_hoat_ngon"]["name"])
            app._on_voice_changed(app.cmb_voice.get())
            assert app.cmb_translation_mode.get() == "Tiếng Anh → Tiếng Việt"
            assert "Tiếng Anh → Tiếng Việt" in app.cmb_translation_mode.cget("values")
            app._load_saved_settings()
            assert app.saved_translation_mode == "Tiếng Anh → Tiếng Việt"
            app.cmb_voice.set(VOICE_PRESETS["japanese_minecraft_clone"]["name"])
            app._on_voice_changed(app.cmb_voice.get())
            assert app.cmb_translation_mode.get() == "Tiếng Anh → Tiếng Nhật"
            app.cmb_translation_mode.set("Tiếng Anh → Tiếng Việt")
            app._on_translation_mode_changed("Tiếng Anh → Tiếng Việt")
            assert app.cmb_voice.get() == VOICE_PRESETS["co_gai_hoat_ngon"]["name"]
            app.url_textbox.insert("1.0", "https://youtu.be/BaW_jenozKc")
            with patch("app_gui.threading.Thread") as thread, patch("app_gui.DouyinAutoPipeline") as pipeline:
                app._start_pipeline()
                thread.call_args.kwargs["target"]()
                config = pipeline.call_args.kwargs["config"]
                assert config.whisper_language == "en"
                assert config.target_language == "vi"
                assert config.tts_config.voice == VOICE_PRESETS["co_gai_hoat_ngon"]["voice"]
            print("PASS: real GUI language selection, voice, saved settings and pipeline config")
        finally:
            app.destroy()
