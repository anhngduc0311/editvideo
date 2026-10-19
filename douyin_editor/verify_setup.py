"""Check installed requirements and local runtime without calling paid APIs."""
import importlib.metadata as metadata
from pathlib import Path
import shutil
import subprocess
import sys
from packaging.requirements import Requirement


def main():
    failures = []
    for line in Path(__file__).with_name("requirements.txt").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        requirement = Requirement(line)
        if requirement.marker and not requirement.marker.evaluate():
            continue
        try:
            version = metadata.version(requirement.name)
            if version not in requirement.specifier:
                failures.append(f"{requirement.name}: {version} does not satisfy {requirement.specifier}")
        except metadata.PackageNotFoundError:
            failures.append(f"Missing: {requirement.name}")
    # Load the same FFmpeg path configuration as the app.
    import config
    for command in ("ffmpeg", "ffprobe"):
        if not shutil.which(command):
            failures.append(f"Missing: {command}")
        else:
            result = subprocess.run([command, "-version"], capture_output=True, timeout=15)
            if result.returncode:
                failures.append(f"Cannot start: {command}")
    try:
        import app_gui
    except Exception as error:
        failures.append(f"Cannot import GUI: {type(error).__name__}: {error}")
    if failures:
        print("\n".join(failures))
        return 1
    print(f"PASS: requirements, FFmpeg, ffprobe and GUI imports (Python {sys.version.split()[0]})")
    print("Japanese clone additionally needs the local models/vendor assets described in ../tts/README_JAPANESE.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
