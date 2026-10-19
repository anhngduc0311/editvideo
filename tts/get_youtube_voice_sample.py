from pathlib import Path
import subprocess
import json
import shutil
import yt_dlp
from static_ffmpeg import run

folder = Path(__file__).parent / "youtube_voice_reference"
folder.mkdir(exist_ok=True)
ffmpeg, ffprobe = run.get_or_fetch_platform_executables_else_raise()
tools_dir = folder / "tools"
tools_dir.mkdir(exist_ok=True)
for source_tool, tool_name in [(ffmpeg, "ffmpeg.exe"), (ffprobe, "ffprobe.exe")]:
    target_tool = tools_dir / tool_name
    if not target_tool.exists():
        shutil.copy2(source_tool, target_tool)
options = {
    "format": "bestaudio/best",
    "outtmpl": str(folder / "reference_13s_43s.%(ext)s"),
    "ffmpeg_location": str(tools_dir),
    "noplaylist": True,
    "socket_timeout": 25,
    "retries": 2,
}
with yt_dlp.YoutubeDL(options) as downloader:
    info = downloader.extract_info("https://www.youtube.com/watch?v=kYYIQStNKMs", download=True)
    source = Path(downloader.prepare_filename(info))
    (folder / "source.json").write_text(json.dumps({"title": info.get("title"), "url": info.get("webpage_url"), "start": 13, "end": 43}, ensure_ascii=False), encoding="utf-8")
target = folder / "voice_sample_13s_43s.wav"
subprocess.run([ffmpeg, "-y", "-ss", "13", "-i", str(source), "-t", "30", "-vn", "-ar", "24000", "-ac", "1", str(target)], check=True, capture_output=True)
print(f"Saved: {target} ({target.stat().st_size} bytes)")
