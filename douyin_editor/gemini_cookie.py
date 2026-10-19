"""Gemini web-session translation with one sequential, short-lived async client."""
from __future__ import annotations

import asyncio
import copy
from contextlib import contextmanager, suppress
import hashlib
from http.cookies import CookieError, SimpleCookie
import json
import logging
import os
from pathlib import Path
import re
import tempfile
import time
from tqdm import tqdm

from config import PipelineConfig, get_target_language
from translator import GeminiTranslator, clean_markdown_response, parse_srt_string, translation_instruction_for_voice

logger = logging.getLogger(__name__)


class GeminiCookieError(RuntimeError):
    """A user-facing error which never includes session credentials."""


class GeminiSubtitleFormatError(GeminiCookieError):
    """Malformed model output, eligible for a smaller translation batch."""


def parse_gemini_cookies(psid: str, psidts: str = "") -> tuple[str, str]:
    """Accept individual values or a Cookie header pasted into the PSID field."""
    psid, psidts = psid.strip(), psidts.strip()
    if psid.lower().startswith("cookie:"):
        psid = psid.split(":", 1)[1].strip()
    if "__Secure-1PSID=" in psid:
        try:
            cookies = SimpleCookie()
            cookies.load(psid)
            psid = cookies["__Secure-1PSID"].value
            if not psidts and "__Secure-1PSIDTS" in cookies:
                psidts = cookies["__Secure-1PSIDTS"].value
        except (CookieError, KeyError):
            raise GeminiCookieError("Không đọc được cookie Gemini. Hãy dán giá trị __Secure-1PSID.") from None
    if not psid or any(char.isspace() or char == ";" for char in psid + psidts):
        raise GeminiCookieError("Cần __Secure-1PSID hợp lệ. Ô thứ hai chỉ nhập giá trị __Secure-1PSIDTS nếu có.")
    return psid, psidts


def session_error(exc: Exception) -> GeminiCookieError:
    """Do not echo library exceptions: they can contain headers or tokens."""
    if isinstance(exc, GeminiCookieError):
        return exc
    name = type(exc).__name__
    if name == "AuthError":
        message = "Cookie Gemini hết hạn hoặc không hợp lệ. Mở Gemini, đăng nhập và cập nhật cookie."
    elif name in ("UsageLimitExceededError", "TemporarilyBlockedError"):
        message = "Gemini đang giới hạn tài khoản hoặc kết nối. Đã dừng gửi yêu cầu; hãy chờ rồi thử lại."
    elif name in ("TimeoutError", "ReadTimeout", "ConnectTimeout", "ConnectionError"):
        message = "Kết nối Gemini bị gián đoạn hoặc quá thời gian chờ. Kiểm tra mạng và thử lại."
    else:
        message = "Không thể kết nối hoặc đọc phản hồi Gemini Web. Kiểm tra phiên đăng nhập hoặc cập nhật gemini-webapi."
    return GeminiCookieError(message)


class GeminiCookieTranslator(GeminiTranslator):
    """Translate through one web session with bounded recovery and saved progress."""

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.psid, self.psidts = parse_gemini_cookies(config.gemini_web_psid, config.gemini_web_psidts)
        self.model_name = "Gemini Web (tự động)"
        self._runner = None
        self._client = None
        self._last_request = None
        self._on_valid_batch = None

    @contextmanager
    def _session(self):
        # Import only for the cookie provider so API-only installs still work.
        try:
            from gemini_webapi import GeminiClient
        except ImportError:
            raise GeminiCookieError("Thiếu gemini-webapi. Chạy: py -m pip install -r requirements.txt") from None
        with asyncio.Runner() as runner:
            self._runner = runner
            self._last_request = None
            try:
                self._client = GeminiClient(self.psid, self.psidts or None)
                runner.run(asyncio.wait_for(self._client.init(
                    timeout=120, auto_close=False, auto_refresh=True, verbose=False,
                ), timeout=60))
                yield
            except Exception as exc:
                raise session_error(exc) from None
            finally:
                if self._client is not None:
                    with suppress(Exception):
                        runner.run(asyncio.wait_for(self._client.close(), timeout=10))
                self._client = None
                self._runner = None

    async def _generate(self, prompt: str, timeout: int) -> str:
        interval = max(0.0, self.config.gemini_web_request_interval)
        if self._last_request is not None:
            remaining = interval - (time.monotonic() - self._last_request)
            if remaining > 0:
                await asyncio.sleep(remaining)
        try:
            response = await asyncio.wait_for(self._client.generate_content(prompt), timeout=timeout)
            text = response.text
            if not isinstance(text, str) or not text.strip():
                raise GeminiSubtitleFormatError("Gemini trả phản hồi rỗng.")
            return text
        finally:
            self._last_request = time.monotonic()

    def _request(self, prompt: str, timeout: int = 120, max_retries: int = 2) -> str:
        if self._runner is None:
            raise GeminiCookieError("Phiên Gemini chưa được khởi tạo.")
        attempts = max(1, min(max_retries, 2))
        for attempt in range(attempts):
            try:
                text = self._runner.run(self._generate(prompt, timeout))
                return text
            except Exception as exc:
                # Only retry transient network failures, never authentication or quota errors.
                if type(exc).__name__ in ("TimeoutError", "ReadTimeout", "ConnectTimeout", "ConnectionError") and attempt + 1 < attempts:
                    self._runner.run(asyncio.sleep(5))
                    continue
                raise session_error(exc) from None
        raise GeminiCookieError("Không nhận được phản hồi Gemini.")

    @staticmethod
    def _align_response(expected, response):
        actual = parse_srt_string(clean_markdown_response(response))
        if len(actual) != len(expected) or any(not item.text.strip() for item in actual):
            raise GeminiSubtitleFormatError("Gemini trả không đủ câu phụ đề.")
        ids = [item.index for item in actual]
        expected_ids = [item.index for item in expected]
        actual_times = [(item.start_str, item.end_str) for item in actual]
        expected_times = [(item.start_str, item.end_str) for item in expected]
        if len(set(ids)) == len(ids) and set(ids) == set(expected_ids):
            mapped = {item.index: item for item in actual}
            ordered = [mapped[item.index] for item in expected]
        elif len(set(actual_times)) == len(actual_times) and set(actual_times) == set(expected_times):
            # Gemini sometimes resets a later batch's numbering to 1. Exact cue
            # timestamps can identify those lines without guessing by position.
            mapped = {(item.start_str, item.end_str): item for item in actual}
            ordered = [mapped[(item.start_str, item.end_str)] for item in expected]
        else:
            raise GeminiSubtitleFormatError("Gemini trả số thứ tự không xác định được.")
        normalized = []
        for original, translated in zip(expected, ordered):
            item = copy.copy(original)
            item.text = translated.text.strip()
            normalized.append(item)
        return normalized

    def _translate_batch(self, batch, prefix, timeout, max_retries):
        data = "\n\n".join(item.to_srt_block().strip() for item in batch)
        try:
            translated = self._align_response(batch, self._request(f"{prefix}\n\n{data}", timeout, max_retries))
        except GeminiSubtitleFormatError:
            if len(batch) > 1:
                middle = len(batch) // 2
                logger.warning("Gemini trả sai cấu trúc ở câu %s–%s; tự chia nhóm %s câu thành %s + %s.",
                               batch[0].index, batch[-1].index, len(batch), middle, len(batch)-middle)
                return (self._translate_batch(batch[:middle], prefix, timeout, max_retries)
                        + self._translate_batch(batch[middle:], prefix, timeout, max_retries))
            correction = f"{prefix}\nCHỈ dịch 1 câu bên dưới. Trả đúng 1 khối SRT, giữ nguyên index {batch[0].index} và timeline."
            try:
                translated = self._align_response(batch, self._request(f"{correction}\n\n{data}", timeout, max_retries))
            except GeminiSubtitleFormatError:
                raise GeminiCookieError(f"Gemini chưa trả bản dịch hợp lệ cho câu {batch[0].index}. Tiến độ đã dịch được giữ lại; chạy lại để tiếp tục.") from None
        if self._on_valid_batch:
            self._on_valid_batch(translated)
        return translated

    def _call_gemini_api(self, prompt: str, timeout: int = 120, max_retries: int = 2) -> str:
        expected = parse_srt_string(prompt)
        if not expected:
            return self._request(prompt, timeout, max_retries)
        first_block = re.search(r"(?m)^\d+\s*\n\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->", prompt)
        prefix = prompt[:first_block.start()] if first_block else "Dịch các câu SRT sau, giữ nguyên index và timeline."
        translated = self._translate_batch(expected, prefix, timeout, max_retries)
        return "\n".join(item.to_srt_block() for item in translated)

    @staticmethod
    def _atomic_text(path, text):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                             prefix=path.name + ".", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(text)
            os.replace(temporary, path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    def translate_srt(self, input_srt_path, output_srt_path):
        source, output = Path(input_srt_path).resolve(), Path(output_srt_path).resolve()
        raw = source.read_text(encoding="utf-8").strip()
        output.parent.mkdir(parents=True, exist_ok=True)
        if not raw:
            self._atomic_text(output, "")
            return []
        items = parse_srt_string(raw)
        if not items or len({item.index for item in items}) != len(items):
            raise GeminiCookieError("File phụ đề gốc không hợp lệ hoặc có số thứ tự trùng nhau.")
        fingerprint = hashlib.sha256(json.dumps(["gemini-web-v1", self.config.whisper_language,
                                                get_target_language(self.config), raw], ensure_ascii=False).encode("utf-8")).hexdigest()
        checkpoint = output.with_name(output.name + ".gemini-progress.json")
        completed = {}
        originals = {item.index: item for item in items}
        try:
            saved = json.loads(checkpoint.read_text(encoding="utf-8"))
            if saved.get("fingerprint") == fingerprint:
                for key, text in saved.get("translations", {}).items():
                    if int(key) in originals and isinstance(text, str) and text.strip():
                        completed[int(key)] = text
        except (OSError, ValueError, TypeError, AttributeError):
            completed = {}
        instruction = translation_instruction_for_voice(self.config, (
            "Bạn là chuyên gia biên dịch phụ đề từ Tiếng Trung sang Tiếng Việt.\n"
            "Dịch tự nhiên, ngắn gọn sang tiếng Việt. Chỉ trả nội dung SRT.\n"
            "GIỮ NGUYÊN TUYỆT ĐỐI timeline, số thứ tự và số lượng câu. Không gộp hay bỏ câu.\n"
        ))
        pending = [item for item in items if item.index not in completed]
        logger.info("Gemini Cookie: khôi phục %s/%s câu đã dịch.", len(completed), len(items))
        with tqdm(total=len(items), initial=len(completed), desc="[Bước 3] Gemini Cookie dịch SRT", leave=False) as progress:
            def save_batch(batch):
                new_count = sum(item.index not in completed for item in batch)
                completed.update({item.index: item.text for item in batch})
                try:
                    self._atomic_text(checkpoint, json.dumps({"fingerprint": fingerprint, "translations": completed}, ensure_ascii=False, indent=2))
                except OSError:
                    raise GeminiCookieError("Không lưu được tiến độ dịch. Kiểm tra quyền ghi hoặc dung lượng ổ đĩa.") from None
                progress.update(new_count)
            self._on_valid_batch = save_batch
            try:
                if pending:
                    with self._session():
                        for start in range(0, len(pending), 15):
                            batch = pending[start:start+15]
                            self._call_gemini_api(instruction + "\n" + "\n".join(item.to_srt_block() for item in batch))
            finally:
                self._on_valid_batch = None
        translated = []
        for original in items:
            item = copy.copy(original)
            item.text = completed[item.index]
            translated.append(item)
        self._atomic_text(output, "\n".join(item.to_srt_block() for item in translated))
        return translated

    def check_status(self) -> dict:
        try:
            with self._session():
                self._call_gemini_api("Chỉ trả lời OK để kiểm tra kết nối.")
            return {"status": "OK", "message": "Kết nối Gemini Cookie thành công. Phiên hiện tại có thể gửi yêu cầu."}
        except Exception as exc:
            return {"status": "ERROR", "message": str(session_error(exc))}
