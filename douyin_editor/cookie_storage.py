"""Protect saved Gemini credentials with the current Windows user's DPAPI key."""
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import json
import os


class CookieStorageError(RuntimeError):
    pass


def _transform(data: bytes, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        raise CookieStorageError("Lưu cookie được mã hóa hiện chỉ hỗ trợ Windows.")

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    protect = crypt32.CryptProtectData
    protect.argtypes = [ctypes.POINTER(DataBlob), wintypes.LPCWSTR, ctypes.POINTER(DataBlob),
                        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob)]
    protect.restype = wintypes.BOOL
    unprotect = crypt32.CryptUnprotectData
    unprotect.argtypes = [ctypes.POINTER(DataBlob), ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(DataBlob),
                          ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob)]
    unprotect.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = DataBlob(len(data), buffer)
    result = DataBlob()
    try:
        if decrypt:
            succeeded = unprotect(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result))
        else:
            # CRYPTPROTECT_UI_FORBIDDEN; deliberately do not set LOCAL_MACHINE.
            succeeded = protect(ctypes.byref(source), "Douyin Studio Gemini Cookie", None,
                                None, None, 1, ctypes.byref(result))
        if not succeeded:
            raise CookieStorageError("Không thể đọc/lưu cookie được mã hóa cho tài khoản Windows hiện tại.")
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        if result.pbData:
            kernel32.LocalFree(ctypes.cast(result.pbData, ctypes.c_void_p))


def protect_cookies(psid: str, psidts: str = "") -> str:
    payload = json.dumps({"psid": psid, "psidts": psidts}).encode("utf-8")
    return "dpapi:v1:" + base64.b64encode(_transform(payload)).decode("ascii")


def unprotect_cookies(value: str) -> tuple[str, str]:
    try:
        if not isinstance(value, str) or not value.startswith("dpapi:v1:"):
            raise ValueError
        encrypted = base64.b64decode(value[len("dpapi:v1:"):], validate=True)
        payload = json.loads(_transform(encrypted, decrypt=True).decode("utf-8"))
        psid, psidts = payload["psid"], payload.get("psidts", "")
        if not isinstance(psid, str) or not isinstance(psidts, str) or not psid:
            raise ValueError
        return psid, psidts
    except CookieStorageError:
        raise
    except Exception:
        raise CookieStorageError("Cookie đã lưu bị lỗi hoặc không đọc được. Hãy nhập và lưu lại cookie.") from None
