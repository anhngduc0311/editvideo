"""Gemini web-session translation with one sequential, short-lived async client."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager, suppress
from http.cookies import CookieError, SimpleCookie
import time

from config import PipelineConfig
from translator import GeminiTranslator, clean_markdown_response, parse_srt_string


class GeminiCookieError(RuntimeError):
    """A user-facing error which never includes session credentials."""


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
    """Reuse SRT batching and language prompts; supply an authenticated web transport."""

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.psid, self.psidts = parse_gemini_cookies(config.gemini_web_psid, config.gemini_web_psidts)
        self.model_name = "Gemini Web (tự động)"
        self._runner = None
        self._client = None
        self._last_request = None

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
                raise GeminiCookieError("Gemini trả phản hồi rỗng. Đã dừng để tránh tạo bản dịch thiếu nội dung.")
            return text
        finally:
            self._last_request = time.monotonic()

    def _call_gemini_api(self, prompt: str, timeout: int = 120, max_retries: int = 2) -> str:
        if self._runner is None:
            raise GeminiCookieError("Phiên Gemini chưa được khởi tạo.")
        attempts = max(1, min(max_retries, 2))
        for attempt in range(attempts):
            try:
                text = self._runner.run(self._generate(prompt, timeout))
                expected = parse_srt_string(prompt)
                actual = parse_srt_string(clean_markdown_response(text))
                if expected and ([item.index for item in actual] != [item.index for item in expected]
                                 or any(not item.text.strip() for item in actual)):
                    raise GeminiCookieError("Gemini trả thiếu hoặc sai thứ tự câu phụ đề. Đã dừng; hãy thử lại để tránh xuất video dịch thiếu.")
                return text
            except Exception as exc:
                # Only retry transient network failures, never authentication or quota errors.
                if type(exc).__name__ in ("TimeoutError", "ReadTimeout", "ConnectTimeout", "ConnectionError") and attempt + 1 < attempts:
                    self._runner.run(asyncio.sleep(5))
                    continue
                raise session_error(exc) from None
        raise GeminiCookieError("Không nhận được phản hồi Gemini.")

    def translate_srt(self, input_srt_path, output_srt_path):
        with self._session():
            return super().translate_srt(input_srt_path, output_srt_path)

    def check_status(self) -> dict:
        try:
            with self._session():
                self._call_gemini_api("Chỉ trả lời OK để kiểm tra kết nối.")
            return {"status": "OK", "message": "Kết nối Gemini Cookie thành công. Phiên hiện tại có thể gửi yêu cầu."}
        except Exception as exc:
            return {"status": "ERROR", "message": str(session_error(exc))}
