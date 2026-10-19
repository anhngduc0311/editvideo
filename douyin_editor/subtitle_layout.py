"""Apply an explicit subtitle center without changing SRT cue timing or text."""
from pathlib import Path
import re
import shutil
import subprocess

from config import SubtitleStyle


def positioned_subtitles(srt_path: Path, style: SubtitleStyle, output_path: Path) -> Path:
    if style.position_x is None or style.position_y is None:
        return Path(srt_path)
    result = subprocess.run(
        [shutil.which("ffmpeg") or "ffmpeg", "-v", "error", "-i", str(srt_path), "-f", "ass", "pipe:1"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True, timeout=30,
    )
    content = result.stdout
    width = re.search(r"^PlayResX:\s*(\d+)", content, re.MULTILINE)
    height = re.search(r"^PlayResY:\s*(\d+)", content, re.MULTILINE)
    if not width or not height:
        raise RuntimeError("Không đọc được độ phân giải bố cục phụ đề từ FFmpeg.")
    x = min(1.0, max(0.0, style.position_x)) * int(width.group(1))
    y = min(1.0, max(0.0, style.position_y)) * int(height.group(1))
    lines = []
    for line in content.splitlines():
        if line.startswith("Dialogue:"):
            fields = line.split(",", 9)
            if len(fields) == 10:
                fields[9] = f"{{\\an5\\pos({x:.3f},{y:.3f})}}" + fields[9]
                line = ",".join(fields)
        lines.append(line)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path
