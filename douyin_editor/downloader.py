"""
downloader.py - Multi-Engine Douyin Downloader (yt-dlp with Cookies + Direct API Fallback)
"""

import json
import logging
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Optional
import requests
from tqdm import tqdm
import yt_dlp

from config import CookieConfig

logger = logging.getLogger(__name__)


class DouyinDownloader:
    """
    Module tải video Douyin đa tầng (Multi-Engine):
    1. yt-dlp với Cookie (tùy chỉnh chuỗi Cookie, file cookies.txt hoặc tự động đọc từ Browser).
    2. TikWM Public API (tải video không logo chất lượng gốc, không bắt buộc cookie).
    3. Douyin Official Web/IES API fallback.
    """

    def __init__(self, download_dir: Path = Path("downloads"), cookie_config: Optional[CookieConfig] = None):
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.cookie_config = cookie_config or CookieConfig()
        self.session = requests.Session()
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/128.0.0.0 Safari/537.36"
            ),
            "Referer": "https://www.douyin.com/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,vi;q=0.7",
        }
        self.session.headers.update(self.headers)
        self._apply_cookies_to_session()

    def _apply_cookies_to_session(self):
        """Gán cookie vào requests.Session"""
        if self.cookie_config.cookie_str:
            for item in self.cookie_config.cookie_str.split(";"):
                if "=" in item:
                    k, v = item.strip().split("=", 1)
                    self.session.cookies.set(k, v, domain=".douyin.com")

    def extract_url(self, raw_input: str) -> str:
        """Trích xuất URL hợp lệ từ chuỗi chia sẻ của Douyin"""
        url_pattern = re.compile(r"https?://[a-zA-Z0-9.-]+(?:/[^\s]*)?")
        match = url_pattern.search(raw_input.strip())
        if match:
            return match.group(0)
        return raw_input.strip()

    def resolve_redirect_url(self, short_url: str) -> str:
        """Theo dõi redirect của link rút gọn (v.douyin.com/xxxx) để lấy URL gốc có chứa Video ID"""
        try:
            response = self.session.get(
                short_url,
                allow_redirects=True,
                timeout=15
            )
            return response.url
        except Exception as e:
            logger.warning(f"Không thể resolve URL qua HTTP ({e}), sử dụng link gốc.")
            return short_url

    def extract_video_id(self, url: str) -> Optional[str]:
        """Bóc tách ID video từ URL (ví dụ: https://www.douyin.com/video/723456789)"""
        match = re.search(r"video/(\d+)", url)
        if match:
            return match.group(1)
        match_note = re.search(r"note/(\d+)", url)
        if match_note:
            return match_note.group(1)
        return None

    def _create_temp_cookie_file(self) -> Optional[Path]:
        """Tạo file cookie tạm thời từ chuỗi cookie người dùng dán vào"""
        if not self.cookie_config.cookie_str:
            return None
        
        cookie_text = self.cookie_config.cookie_str.strip()
        # Nếu người dùng dán định dạng Netscape (chứa # Netscape HTTP Cookie File hoặc có tab)
        if "# Netscape" in cookie_text or "\t" in cookie_text:
            tmp = Path(tempfile.gettempdir()) / f"douyin_cookie_{int(time.time())}.txt"
            tmp.write_text(cookie_text, encoding="utf-8")
            return tmp
        
        # Nếu dán header Cookie dạng "name=val; name2=val2" -> chuyển sang định dạng Netscape
        lines = ["# Netscape HTTP Cookie File", "# https://curl.haxx.se/rfc/cookie_spec.html", ""]
        for part in cookie_text.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                lines.append(f".douyin.com\tTRUE\t/\tTRUE\t2147483647\t{k}\t{v}")
        
        tmp = Path(tempfile.gettempdir()) / f"douyin_cookie_{int(time.time())}.txt"
        tmp.write_text("\n".join(lines), encoding="utf-8")
        return tmp

    def _download_via_direct_api(self, url: str, output_path: Path) -> bool:
        """
        Chiến lược 2: Tải qua Direct API (TikWM) - Không dính watermark, không bắt buộc cookie
        """
        logger.info("[Chiến lược 2] Đang thử tải video qua Direct TikWM API (Không logo)...")
        try:
            api_url = "https://tikwm.com/api/"
            resp = self.session.post(api_url, data={"url": url, "hd": 1}, timeout=15)
            if resp.status_code == 200:
                res_json = resp.json()
                if res_json.get("code") == 0:
                    data = res_json.get("data", {})
                    video_url = data.get("hdplay") or data.get("play")
                    if video_url:
                        logger.info(f"Tìm thấy luồng video trực tiếp: {data.get('title', 'Douyin Video')[:40]}...")
                        # Tiến hành tải stream
                        with self.session.get(video_url, stream=True, timeout=30) as v_resp:
                            v_resp.raise_for_status()
                            total_size = int(v_resp.headers.get("content-length", 0))
                            with open(output_path, "wb") as f, tqdm(
                                total=total_size,
                                unit="B",
                                unit_scale=True,
                                desc="[Bước 1] Đang tải qua Direct API",
                                leave=False
                            ) as pbar:
                                for chunk in v_resp.iter_content(chunk_size=64 * 1024):
                                    if chunk:
                                        f.write(chunk)
                                        pbar.update(len(chunk))
                        
                        if output_path.exists() and output_path.stat().st_size > 1000:
                            logger.info(f"Tải video thành công qua Direct API: {output_path.name}")
                            return True
        except Exception as e:
            logger.warning(f"Tải qua Direct API không thành công: {e}")
        return False

    def _download_via_ytdlp(self, url: str, out_template: str) -> Optional[Path]:
        """
        Chiến lược 1: Tải bằng yt-dlp kèm Cookie
        """
        temp_cookie_file = None
        ydl_opts = {
            "outtmpl": out_template,
            "format": "bestvideo+bestaudio/best",
            "merge_output_format": "mp4",
            "http_headers": self.headers,
            "quiet": True,
            "no_warnings": True,
        }

        # 1. Nếu có file cookie chỉ định
        if self.cookie_config.cookie_file and Path(self.cookie_config.cookie_file).exists():
            ydl_opts["cookiefile"] = str(self.cookie_config.cookie_file)
            logger.info(f"Sử dụng file cookie: {self.cookie_config.cookie_file}")
        # 2. Nếu có chuỗi cookie text
        elif self.cookie_config.cookie_str:
            temp_cookie_file = self._create_temp_cookie_file()
            if temp_cookie_file and temp_cookie_file.exists():
                ydl_opts["cookiefile"] = str(temp_cookie_file)
                logger.info("Đã nạp chuỗi cookie tùy chỉnh vào yt-dlp.")
        # 3. Nếu chọn đọc cookie từ trình duyệt
        elif self.cookie_config.browser_name:
            b_name = self.cookie_config.browser_name.lower().strip()
            ydl_opts["cookiesfrombrowser"] = (b_name, None, None, None)
            logger.info(f"Đang đọc cookie trực tiếp từ trình duyệt: {b_name.upper()}...")

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                downloaded_file = Path(ydl.prepare_filename(info))
                
                if not downloaded_file.exists():
                    mp4_candidate = downloaded_file.with_suffix(".mp4")
                    if mp4_candidate.exists():
                        downloaded_file = mp4_candidate

                if downloaded_file.exists() and downloaded_file.stat().st_size > 1000:
                    return downloaded_file.resolve()
        finally:
            if temp_cookie_file and temp_cookie_file.exists():
                try:
                    temp_cookie_file.unlink()
                except Exception:
                    pass
        return None

    def download(self, url_or_text: str, custom_filename: Optional[str] = None) -> Path:
        """
        Thực hiện tải video bằng cơ chế tự động chuyển đổi thông minh (Auto-Fallback).
        """
        clean_url = self.extract_url(url_or_text)
        if not clean_url.startswith("http"):
            raise ValueError(f"URL không hợp lệ: {url_or_text}")

        resolved_url = self.resolve_redirect_url(clean_url)
        video_id = self.extract_video_id(resolved_url) or str(int(time.time()))
        
        file_base_name = custom_filename or f"douyin_{video_id}"
        target_output_file = self.download_dir / f"{file_base_name}.mp4"

        logger.info(f"Bắt đầu tải video từ URL: {resolved_url}")

        # Bước 1: Thử tải qua Direct API trước (Tốc độ cực nhanh, không cần cookie)
        if self._download_via_direct_api(clean_url, target_output_file):
            return target_output_file.resolve()

        if resolved_url != clean_url:
            if self._download_via_direct_api(resolved_url, target_output_file):
                return target_output_file.resolve()

        # Bước 2: Thử tải qua yt-dlp (với cookies đã cấu hình)
        logger.info("[Chiến lược 1] Đang thử tải qua yt-dlp...")
        out_template = str(self.download_dir / f"{file_base_name}.%(ext)s")
        try:
            downloaded = self._download_via_ytdlp(resolved_url, out_template)
            if downloaded and downloaded.exists():
                logger.info(f"Tải thành công qua yt-dlp: {downloaded.name}")
                return downloaded
        except Exception as e:
            logger.warning(f"yt-dlp gặp lỗi ({e}).")

        raise RuntimeError(
            "Không thể tải video từ Douyin!\n\n"
            "Nguyên nhân: Douyin chặn truy cập tự động và yêu cầu Cookie.\n"
            "👉 Giải pháp: Vui lòng dán Cookie từ trình duyệt vào ô 'Cookie Douyin' trong giao diện và thử lại!"
        )
