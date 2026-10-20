"""Entry point for the standalone Windows application."""
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import subprocess
import sys
import traceback

from app_paths import data_dir, resource_root


def main():
    multiprocessing.freeze_support()
    home = data_dir()
    home.mkdir(parents=True, exist_ok=True)
    os.chdir(home)
    os.environ["PATH"] = str(resource_root() / "bin") + os.pathsep + os.environ.get("PATH", "")
    # Libraries such as Torch/OpenVoice print even in a windowed application.
    log = (home / "desktop.log").open("a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = log
    if sys.stderr is None:
        sys.stderr = log
    try:
        import app_gui
        if "--smoke-test" in sys.argv:
            report = {"data_dir": str(home), "frozen": bool(getattr(sys, "frozen", False))}
            for name in ("ffmpeg", "ffprobe"):
                path = shutil.which(name)
                if not path:
                    raise RuntimeError(f"Missing {name}")
                subprocess.run([path, "-version"], check=True, capture_output=True, timeout=30)
                report[name] = path
            import whisper
            import onnxruntime
            from capcut_tts_api import CapCutClient
            from voice_clone import JapaneseCloneTTSEngine
            JapaneseCloneTTSEngine._load_model()
            app = app_gui.DouyinEditorApp()
            app.update()
            app.destroy()
            report["status"] = "ok"
            (home / "smoke-test.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        else:
            app_gui.main()
    except Exception:
        details = traceback.format_exc()
        (home / "startup-error.log").write_text(details, encoding="utf-8")
        if "--smoke-test" not in sys.argv:
            import tkinter.messagebox
            tkinter.messagebox.showerror("EditVideo Studio", f"Không thể mở ứng dụng. Chi tiết:\n{home / 'startup-error.log'}")
        raise


if __name__ == "__main__":
    main()
