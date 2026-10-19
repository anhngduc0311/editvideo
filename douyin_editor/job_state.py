"""Atomic checkpoints and cooperative cancellation for a video job."""
from dataclasses import asdict, is_dataclass
import hashlib
import json
from pathlib import Path


class JobCancelled(RuntimeError):
    pass


def check_cancelled(event):
    if event is not None and event.is_set():
        raise JobCancelled("Đã hủy xử lý. Các bước hoàn tất được giữ lại để tiếp tục.")


def signature(value):
    if is_dataclass(value):
        value = asdict(value)
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    default=str).encode("utf-8")).hexdigest()


def file_stamp(path):
    path = Path(path).resolve()
    stat = path.stat()
    return [str(path), stat.st_size, stat.st_mtime_ns]


class JobState:
    """A stage is reusable only with the same inputs and unmodified outputs."""
    VERSION = 1

    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "job_state.json"
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(self.data, dict) or self.data.get("version") != self.VERSION:
                self.data = {}
        except (OSError, ValueError, TypeError):
            self.data = {}
        if not isinstance(self.data, dict):
            self.data = {}
        self.data["version"] = self.VERSION

    def outputs(self, stage, key):
        entry = self.data.get(stage, {})
        if not isinstance(entry, dict) or entry.get("key") != signature(key):
            return None
        try:
            stamps = entry["outputs"]
            if stamps and all(file_stamp(s[0]) == s and s[1] > 0 for s in stamps):
                return [Path(s[0]) for s in stamps]
        except (OSError, KeyError, TypeError, IndexError):
            pass
        return None

    def complete(self, stage, key, paths):
        stamps = [file_stamp(p) for p in paths]
        if not stamps or any(s[1] <= 0 for s in stamps):
            raise RuntimeError(f"Bước {stage} chưa tạo đủ dữ liệu hợp lệ.")
        self.data[stage] = {"key": signature(key), "outputs": stamps}
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)
