"""Sequential video jobs with isolated settings and per-video error reporting."""
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import List, Tuple
from urllib.parse import urlparse

from job_state import JobCancelled, check_cancelled


def extract_video_urls(text: str) -> List[str]:
    urls = []
    for match in re.finditer(r'https?://[^\s<>"\']+', text):
        url = match.group().rstrip(".,;!)]}，。；！）】")
        host = (urlparse(url).hostname or "").lower()
        if not any(host == domain or host.endswith("." + domain) for domain in
                   ("youtube.com", "youtu.be", "youtube-nocookie.com", "douyin.com")):
            raise ValueError(f"Liên kết không được hỗ trợ: {url}")
        if url not in urls:
            urls.append(url)
    if not urls:
        raise ValueError("Vui lòng nhập đường link video YouTube hoặc Douyin, mỗi dòng một link.")
    return urls


@dataclass
class VideoQueueResult:
    completed: List[Tuple[str, Path]] = field(default_factory=list)
    failed: List[Tuple[str, str]] = field(default_factory=list)


def run_video_queue(urls, config, pipeline_factory, *, cancel_event=None,
                    progress_callback=None, interactive_roi_callback=None,
                    on_start=None, on_complete=None, on_error=None):
    result = VideoQueueResult()
    total = len(urls)
    for number, url in enumerate(urls, 1):
        check_cancelled(cancel_event)
        if on_start:
            on_start(number, total, url)
        try:
            pipeline = pipeline_factory(config=deepcopy(config))
            check_cancelled(cancel_event)
            def progress(*args, _number=number):
                if progress_callback:
                    progress_callback(_number, total, *args)
            output = pipeline.run(douyin_url_or_text=url, progress_callback=progress,
                                  interactive_roi_callback=interactive_roi_callback,
                                  cancel_event=cancel_event)
            result.completed.append((url, output))
            if on_complete:
                on_complete(number, total, url, output)
        except JobCancelled:
            raise
        except Exception as error:
            check_cancelled(cancel_event)
            result.failed.append((url, str(error)))
            if on_error:
                on_error(number, total, url, str(error))
    check_cancelled(cancel_event)
    return result
