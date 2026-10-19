"""Opt-in real download smoke check: py check_youtube_download.py VIDEO_URL."""
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import static_ffmpeg
from downloader import DouyinDownloader

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: py check_youtube_download.py YOUTUBE_VIDEO_URL")
    static_ffmpeg.add_paths()
    with tempfile.TemporaryDirectory() as directory:
        output = DouyinDownloader(Path(directory)).download(sys.argv[1])
        print("PASS:", output.name, output.stat().st_size, "bytes")
