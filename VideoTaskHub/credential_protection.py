"""Windows user-bound protection for credentials stored in local JSON settings."""

from __future__ import annotations

import base64
import ctypes
import json
import os
from ctypes import wintypes


_MARKER = "__videotaskhub_dpapi__"
_SENSITIVE_NAMES = frozenset({"api_key", "api_keys", "access_token", "token", "password"})


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes):
    buffer = (ctypes.c_byte * len(data)).from_buffer_copy(data)
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def _protect_bytes(data: bytes) -> bytes:
    if os.name != "nt":
        raise OSError("Windows DPAPI is unavailable on this platform")
    incoming, keepalive = _blob(data)
    outgoing = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    if not crypt32.CryptProtectData(ctypes.byref(incoming), None, None, None, None, 0, ctypes.byref(outgoing)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(outgoing.pbData, outgoing.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(outgoing.pbData)


def _unprotect_bytes(data: bytes) -> bytes:
    if os.name != "nt":
        raise OSError("Windows DPAPI is unavailable on this platform")
    incoming, keepalive = _blob(data)
    outgoing = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    if not crypt32.CryptUnprotectData(ctypes.byref(incoming), None, None, None, None, 0, ctypes.byref(outgoing)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(outgoing.pbData, outgoing.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(outgoing.pbData)


def _protect_value(value):
    if value in (None, "", []):
        return value
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    encrypted = _protect_bytes(encoded)
    return {_MARKER: base64.b64encode(encrypted).decode("ascii"), "kind": "list" if isinstance(value, list) else "scalar"}


def _unprotect_value(value):
    if not isinstance(value, dict) or _MARKER not in value:
        return value
    fallback = [] if value.get("kind") == "list" else ""
    try:
        encrypted = base64.b64decode(str(value[_MARKER]), validate=True)
        return json.loads(_unprotect_bytes(encrypted).decode("utf-8"))
    except Exception:
        return fallback


def protect_sensitive_config(value):
    if isinstance(value, dict):
        if _MARKER in value:
            return dict(value)
        return {key: (_protect_value(item) if str(key).lower() in _SENSITIVE_NAMES else protect_sensitive_config(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [protect_sensitive_config(item) for item in value]
    return value


def unprotect_sensitive_config(value):
    if isinstance(value, dict):
        if _MARKER in value:
            return _unprotect_value(value)
        return {key: unprotect_sensitive_config(item) for key, item in value.items()}
    if isinstance(value, list):
        return [unprotect_sensitive_config(item) for item in value]
    return value
