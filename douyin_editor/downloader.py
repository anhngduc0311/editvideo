"""
downloader.py - Multi-Engine Douyin Downloader (Official API + Auto Fresh Cookie + yt-dlp + TikWM)
"""

import json
import logging
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Callable, Optional
import requests
from tqdm import tqdm
import yt_dlp

from config import CookieConfig

logger = logging.getLogger(__name__)


class DouyinDownloader:
    """
    Module tải video Douyin đa tầng thông minh (Multi-Engine Smart Fallback):
    1. Douyin Official Web API với Auto TTWID Registration (HD 100% gốc không logo, không cần đăng nhập).
    2. yt-dlp với Auto-Generated Fresh Netscape Cookie (Tự động bypass lỗi 'Fresh cookies needed').
    3. TikWM & Tiklydown Public APIs (dự phòng khi IP bị chặn).
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

    def _fetch_fresh_ttwid_cookie(self) -> Optional[str]:
        """Tự động đăng ký và lấy cookie ttwid chính thức từ ByteDance để vượt rào cản Fresh Cookies"""
        try:
            reg_headers = {
                "User-Agent": self.headers["User-Agent"],
                "Content-Type": "application/json"
            }
            data = {
                "region": "cn",
                "aid": 1768,
                "needFid": "0",
                "service": "www.ixigua.com",
                "migrate_info": {"ticket": "", "source": "node"},
                "cbUrlProtocol": "https",
                "union": True
            }
            r = requests.post("https://ttwid.bytedance.com/ttwid/union/register/", json=data, headers=reg_headers, timeout=8)
            ttwid = r.cookies.get("ttwid")
            if ttwid:
                logger.info("Đã tự động lấy Fresh TTWID Cookie từ ByteDance thành công!")
                return ttwid
        except Exception as e:
            logger.warning(f"Không thể lấy ttwid tự động: {e}")
        return None

    def _create_auto_fresh_cookie_file(self) -> Optional[Path]:
        """Tạo file cookie Netscape tự động chứa fresh ttwid và csrf token cho yt-dlp"""
        try:
            ttwid = self._fetch_fresh_ttwid_cookie() or "1%7Ctemp"
            lines = [
                "# Netscape HTTP Cookie File",
                "# https://curl.haxx.se/rfc/cookie_spec.html",
                "",
                f".douyin.com\tTRUE\t/\tTRUE\t2147483647\tttwid\t{ttwid}",
                ".douyin.com\tTRUE\t/\tTRUE\t2147483647\tpassport_csrf_token\td8a2f3a9e18b4e72a8847b2c0e86b4d3",
                ".douyin.com\tTRUE\t/\tTRUE\t2147483647\t__ac_nonce\t06a92ffa10040f4f84c2a",
                ".douyin.com\tTRUE\t/\tTRUE\t2147483647\ts_v_web_id\tverify_abc123"
            ]
            tmp = Path(tempfile.gettempdir()) / f"douyin_autocookie_{int(time.time()*1000)}.txt"
            tmp.write_text("\n".join(lines), encoding="utf-8")
            return tmp
        except Exception as e:
            logger.warning(f"Không thể tạo auto cookie file: {e}")
            return None

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
        match_modal = re.search(r"modal_id=(\d+)", url)
        if match_modal:
            return match_modal.group(1)
        return None

    def _create_temp_cookie_file(self) -> Optional[Path]:
        """Tạo file cookie tạm thời từ chuỗi cookie người dùng dán vào"""
        if not self.cookie_config.cookie_str:
            return None
        
        cookie_text = self.cookie_config.cookie_str.strip()
        # Nếu người dùng dán định dạng Netscape (chứa # Netscape HTTP Cookie File hoặc có tab)
        if "# Netscape" in cookie_text or "\t" in cookie_text:
            tmp = Path(tempfile.gettempdir()) / f"douyin_cookie_{int(time.time()*1000)}.txt"
            tmp.write_text(cookie_text, encoding="utf-8")
            return tmp
        
        # Nếu dán header Cookie dạng "name=val; name2=val2" -> chuyển sang định dạng Netscape
        lines = ["# Netscape HTTP Cookie File", "# https://curl.haxx.se/rfc/cookie_spec.html", ""]
        for part in cookie_text.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                lines.append(f".douyin.com\tTRUE\t/\tTRUE\t2147483647\t{k}\t{v}")
        
        tmp = Path(tempfile.gettempdir()) / f"douyin_cookie_{int(time.time()*1000)}.txt"
        tmp.write_text("\n".join(lines), encoding="utf-8")
        return tmp

    def _download_via_official_api(
        self,
        video_id: str,
        output_path: Path,
        progress_callback: Optional[Callable[[float, str], None]] = None
    ) -> bool:
        """
        Chiến lược 1: Tải trực tiếp qua Official Douyin Web Detail API (HD 100% gốc không logo, siêu tốc)
        """
        logger.info(f"[Chiến lược 1] Đang tải video ID {video_id} qua Official Douyin Detail API...")
        try:
            ttwid = self.session.cookies.get("ttwid") or self._fetch_fresh_ttwid_cookie()
            
            headers = dict(self.headers)
            cookie_parts = []
            if ttwid:
                cookie_parts.append(f"ttwid={ttwid}")
            cookie_parts.append("passport_csrf_token=d8a2f3a9e18b4e72a8847b2c0e86b4d3")
            if self.cookie_config.cookie_str:
                cookie_parts.append(self.cookie_config.cookie_str)
            
            headers["Cookie"] = "; ".join(cookie_parts)
            headers["Referer"] = f"https://www.douyin.com/video/{video_id}"

            api_url = f"https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id={video_id}"
            resp = self.session.get(api_url, headers=headers, timeout=12)
            if resp.status_code == 200:
                res_data = resp.json()
                detail = res_data.get("aweme_detail") or {}
                video_obj = detail.get("video") or {}
                
                # Quét và xếp hạng toàn bộ các luồng video để chọn luồng chất lượng Full HD / Bitrate cao nhất
                candidates = []
                
                # 1. Quét danh sách bit_rate (chứa các profile 1080p, 720p, 540p kèm bitrate chi tiết)
                for b in video_obj.get("bit_rate", []):
                    pa = b.get("play_addr") or {}
                    urls = pa.get("url_list") or []
                    if urls:
                        w = pa.get("width") or b.get("width") or 0
                        h = pa.get("height") or b.get("height") or 0
                        br = b.get("bit_rate") or 0
                        gear = b.get("gear_name") or ""
                        candidates.append((w * h, br, urls[0].replace("playwm", "play"), f"{w}x{h} ({gear}, {br//1000}kbps)"))
                
                # 2. Quét các trường địa chỉ phụ khác
                for key in ["play_addr_265", "play_addr_h264", "download_addr", "play_addr"]:
                    addr = video_obj.get(key) or {}
                    urls = addr.get("url_list") or []
                    if urls:
                        w = addr.get("width") or 0
                        h = addr.get("height") or 0
                        candidates.append((w * h, 0, urls[0].replace("playwm", "play"), f"{w}x{h} ({key})"))
                
                # Sắp xếp ưu tiên: Kích thước pixel (w*h) lớn nhất -> Bitrate cao nhất
                candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
                
                if candidates:
                    best_candidate = candidates[0]
                    stream_url = best_candidate[2]
                    quality_info = best_candidate[3]
                    title = detail.get("desc", f"douyin_{video_id}")
                    logger.info(f"Tìm thấy luồng video Douyin chất lượng cao nhất [{quality_info}]: {title[:40]}...")
                    
                    stream_headers = {
                        "User-Agent": self.headers["User-Agent"],
                        "Referer": "https://www.douyin.com/"
                    }
                    
                    with requests.get(stream_url, headers=stream_headers, stream=True, timeout=30) as v_resp:
                        v_resp.raise_for_status()
                        total_size = int(v_resp.headers.get("content-length", 0))
                        downloaded_size = 0
                        with open(output_path, "wb") as f, tqdm(
                            total=total_size,
                            unit="B",
                            unit_scale=True,
                            desc=f"[Bước 1] Đang tải Douyin HD ({quality_info})",
                            leave=False
                        ) as pbar:
                            for chunk in v_resp.iter_content(chunk_size=128 * 1024):
                                if chunk:
                                    f.write(chunk)
                                    downloaded_size += len(chunk)
                                    pbar.update(len(chunk))
                                    if progress_callback and total_size > 0:
                                        frac = min(downloaded_size / total_size, 1.0)
                                        progress_callback(frac, f"Đang tải {quality_info} ({downloaded_size//1024}/{total_size//1024} KB)")

                    if output_path.exists() and output_path.stat().st_size > 1000:
                        logger.info(f"Tải video thành công qua Official Douyin API [{quality_info}]: {output_path.name} ({output_path.stat().st_size//1024} KB)")
                        return True
        except Exception as e:
            logger.warning(f"Tải qua Official Douyin API không thành công: {e}")
        return False

    def _download_via_direct_api(self, url: str, output_path: Path, progress_callback: Optional[Callable[[float, str], None]] = None) -> bool:
        """
        Chiến lược 3: Tải qua Direct Public API (TikWM) - Không dính watermark
        """
        logger.info("[Chiến lược 3] Đang thử tải video qua Direct TikWM API...")
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
                        with self.session.get(video_url, stream=True, timeout=30) as v_resp:
                            v_resp.raise_for_status()
                            total_size = int(v_resp.headers.get("content-length", 0))
                            downloaded_size = 0
                            with open(output_path, "wb") as f, tqdm(
                                total=total_size,
                                unit="B",
                                unit_scale=True,
                                desc="[Bước 1] Đang tải qua TikWM API",
                                leave=False
                            ) as pbar:
                                for chunk in v_resp.iter_content(chunk_size=128 * 1024):
                                    if chunk:
                                        f.write(chunk)
                                        downloaded_size += len(chunk)
                                        pbar.update(len(chunk))
                                        if progress_callback and total_size > 0:
                                            frac = min(downloaded_size / total_size, 1.0)
                                            progress_callback(frac, f"Đang tải {downloaded_size//1024}/{total_size//1024} KB ({int(frac*100)}%)")
                        
                        if output_path.exists() and output_path.stat().st_size > 1000:
                            logger.info(f"Tải video thành công qua Direct API: {output_path.name}")
                            return True
        except Exception as e:
            logger.warning(f"Tải qua Direct API không thành công: {e}")
        return False

    def _download_via_ytdlp(self, url: str, out_template: str) -> Optional[Path]:
        """
        Chiến lược 2: Tải bằng yt-dlp kèm Cookie (Tự động nạp Fresh Cookie nếu người dùng chưa cài đặt)
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
        else:
            # 4. Tự động cấp phát Fresh Cookie Netscape để yt-dlp không bị chặn
            temp_cookie_file = self._create_auto_fresh_cookie_file()
            if temp_cookie_file and temp_cookie_file.exists():
                ydl_opts["cookiefile"] = str(temp_cookie_file)
                logger.info("Đã tự động tạo Fresh Netscape Cookie nạp vào yt-dlp.")

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

    def download(
        self,
        url_or_text: str,
        custom_filename: Optional[str] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None
    ) -> Path:
        """
        Thực hiện tải video bằng cơ chế tự động chuyển đổi thông minh (Auto-Fallback).
        Hoàn toàn tự động giải quyết lỗi 'Fresh cookies needed' của Douyin.
        """
        clean_url = self.extract_url(url_or_text)
        if not clean_url.startswith("http"):
            raise ValueError(f"URL không hợp lệ: {url_or_text}")

        resolved_url = self.resolve_redirect_url(clean_url)
        video_id = self.extract_video_id(resolved_url) or self.extract_video_id(clean_url)
        
        file_base_name = custom_filename or f"douyin_{video_id or str(int(time.time()))}"
        target_output_file = self.download_dir / f"{file_base_name}.mp4"

        logger.info(f"Bắt đầu tải video Douyin từ URL: {resolved_url} (ID: {video_id})")

        # Bước 1: Nếu có Video ID -> Thử tải trực tiếp qua Official Douyin API (Siêu tốc, HD gốc 100%)
        if video_id:
            if self._download_via_official_api(video_id, target_output_file, progress_callback):
                return target_output_file.resolve()

        # Bước 2: Thử tải qua yt-dlp với Auto Fresh Cookie Netscape
        logger.info("[Chiến lược 2] Đang tải qua yt-dlp (Kèm Fresh Cookies)...")
        out_template = str(self.download_dir / f"{file_base_name}.%(ext)s")
        try:
            downloaded = self._download_via_ytdlp(resolved_url, out_template)
            if downloaded and downloaded.exists():
                logger.info(f"Tải thành công qua yt-dlp: {downloaded.name}")
                return downloaded
        except Exception as e:
            logger.warning(f"yt-dlp gặp lỗi ({e}).")

        # Bước 3: Thử tải qua Direct TikWM Public API
        if self._download_via_direct_api(clean_url, target_output_file, progress_callback):
            return target_output_file.resolve()

        if resolved_url != clean_url:
            if self._download_via_direct_api(resolved_url, target_output_file, progress_callback):
                return target_output_file.resolve()

        raise RuntimeError(
            "Không thể tải video từ Douyin sau khi đã thử tất cả 3 phương thức!\n"
            "Vui lòng kiểm tra lại link video hoặc thử dán Cookie từ trình duyệt vào ô 'Cookie Douyin'."
        )

