"""Encrypt saved credentials for the current Windows user with DPAPI.

Other systems keep credentials in memory/environment instead of plaintext files.
"""
import base64
import ctypes
from ctypes import wintypes
import json
import logging
import os

logger = logging.getLogger(__name__)


def _crypt(payload, decrypt=False):
    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(payload)
    source = Blob(len(payload), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    operation = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    operation.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                          ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    operation.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel32.LocalFree(target.data)


def seal_secrets(secrets):
    if os.name != "nt":
        return None
    try:
        return base64.b64encode(_crypt(json.dumps(secrets).encode("utf-8"))).decode("ascii")
    except OSError:
        logger.warning("Không lưu được thông tin đăng nhập an toàn; chỉ giữ trong phiên hiện tại.")
        return None


def open_secrets(token):
    if not token or os.name != "nt":
        return {}
    try:
        result = json.loads(_crypt(base64.b64decode(token), decrypt=True).decode("utf-8"))
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError, TypeError):
        logger.warning("Không đọc được thông tin đăng nhập đã mã hóa; hãy nhập lại.")
        return {}
