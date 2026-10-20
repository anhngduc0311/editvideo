"""Build a self-contained Windows app and one-file Inno Setup installer.

Run on the build PC: python build_windows.py --iscc PATH/TO/ISCC.exe
The destination PC needs neither Python nor pip.
"""
import argparse
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent


def stage_assets():
    import static_ffmpeg
    static_ffmpeg.add_paths()
    stage = ROOT / "build" / "assets"
    stage.mkdir(parents=True, exist_ok=True)
    required = {
        REPO / "tts" / "models" / "openvoice_v2" / name: Path("tts/models/openvoice_v2") / name
        for name in ("converter/config.json", "converter/checkpoint.pth", "source_speaker.pth", "reference_speaker.pth")
    }
    for name in ("cogaihoatngon.mp3", "thanhnientutin.mp3", "japanese_youtube_voice_clone.mp3"):
        required[REPO / "tts" / name] = Path("tts") / name
    for name in ("ffmpeg", "ffprobe"):
        path = shutil.which(name)
        if not path:
            raise FileNotFoundError(f"Missing {name}")
        required[Path(path)] = Path("bin") / f"{name}.exe"
    node = shutil.which("node")
    if not node:
        raise FileNotFoundError("Install Node.js 22+ on the build PC for YouTube support")
    major = int(subprocess.check_output([node, "--version"], text=True).strip().lstrip("v").split(".")[0])
    if major < 22:
        raise RuntimeError("Node.js 22+ is required for the release")
    required[Path(node)] = Path("bin/node.exe")
    required[Path.home() / ".cache" / "whisper" / "small.pt"] = Path("whisper_models/small.pt")
    required[ROOT / "models" / "UVR-MDX-NET-Inst_HQ_3.onnx"] = Path("models/UVR-MDX-NET-Inst_HQ_3.onnx")
    vendor = REPO / "tts" / "vendor" / "OpenVoice"
    required[vendor / "openvoice" / "api.py"] = Path("tts/vendor/OpenVoice/openvoice/api.py")
    for source, relative in required.items():
        if not source.is_file():
            raise FileNotFoundError(f"Missing release asset: {source}")
        target = stage / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    # Some processing modules call static_ffmpeg.add_paths() directly. Supply
    # its cache as well, so those calls never download into the installed app.
    ffmpeg_cache = stage / "static_ffmpeg" / "bin" / "win32"
    ffmpeg_cache.mkdir(parents=True, exist_ok=True)
    for name in ("ffmpeg", "ffprobe"):
        shutil.copy2(stage / "bin" / f"{name}.exe", ffmpeg_cache / f"{name}.exe")
    (ffmpeg_cache / "installed.crumb").write_text("Bundled by EditVideo Studio", encoding="utf-8")
    # Only vendor Python/data and license files; never package caches or user files.
    for source in (vendor / "openvoice").rglob("*"):
        if source.is_file() and source.suffix in (".py", ".json", ".txt") and "__pycache__" not in source.parts:
            target = stage / "tts" / "vendor" / "OpenVoice" / source.relative_to(vendor)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    licenses = stage / "licenses"
    licenses.mkdir(exist_ok=True)
    for source in vendor.glob("*LICENSE*"):
        shutil.copy2(source, licenses / ("OpenVoice-" + source.name))
    for dist in metadata.distributions():
        for file in dist.files or ():
            if any(part.lower() in ("licenses", "license", "license.txt", "license.md", "copying", "notice") for part in file.parts):
                source = Path(dist.locate_file(file))
                if source.is_file():
                    target = licenses / dist.metadata["Name"] / str(file).replace("..", "_")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    (stage / "build-versions.json").write_text(json.dumps({d.metadata['Name']: d.version for d in metadata.distributions()}, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iscc", type=Path)
    parser.add_argument("--app-only", action="store_true")
    args = parser.parse_args()
    if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
        parser.error("Build requires Windows x64 with 64-bit Python")
    stage_assets()
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(ROOT / "packaging/EditVideoStudio.spec")], cwd=ROOT, check=True)
    exe = ROOT / "dist/EditVideoStudio/EditVideoStudio.exe"
    test_home = ROOT / "build" / "release-smoke"
    smoke = test_home / "EditVideoStudio/smoke-test.json"
    smoke.unlink(missing_ok=True)
    smoke_env = dict(os.environ, LOCALAPPDATA=str(test_home),
                     HTTP_PROXY="http://127.0.0.1:9", HTTPS_PROXY="http://127.0.0.1:9",
                     ALL_PROXY="http://127.0.0.1:9", NO_PROXY="")
    smoke_env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    subprocess.run([str(exe), "--smoke-test"], cwd=ROOT.parent, env=smoke_env, check=True, timeout=240)
    if json.loads(smoke.read_text(encoding="utf-8"))["status"] != "ok":
        raise RuntimeError("Packaged smoke test failed")
    subprocess.run([str(exe.parent / "_internal/bin/node.exe"), "--version"], env=smoke_env, check=True)
    if not args.app_only:
        iscc = args.iscc or shutil.which("ISCC.exe")
        if not iscc:
            parser.error("App built. Install Inno Setup and supply --iscc to create the Setup.exe")
        subprocess.run([str(iscc), str(ROOT / "packaging/installer.iss")], check=True)
        print(ROOT / "dist/EditVideoStudio-Setup.exe")


if __name__ == "__main__":
    main()
