from __future__ import annotations

import base64
import ctypes
import sys
from ctypes import wintypes

_ENC_PREFIX = "enc:dpapi:"
_CRYPTPROTECT_UI_FORBIDDEN = 0x01


class SecretDecryptionError(RuntimeError):
    pass


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def _blob_from_bytes(data: bytes) -> tuple[_DATA_BLOB, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data)
    blob = _DATA_BLOB(
        cbData=len(data),
        pbData=ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)),
    )
    return blob, buffer


def _blob_to_bytes(blob: _DATA_BLOB) -> bytes:
    if not blob.pbData or blob.cbData <= 0:
        return b""
    return ctypes.string_at(blob.pbData, blob.cbData)


def _is_windows() -> bool:
    return sys.platform.startswith("win")


def is_encrypted(value: str) -> bool:
    return str(value or "").startswith(_ENC_PREFIX)


def _dpapi_encrypt(raw: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    in_blob, in_buf = _blob_from_bytes(raw)
    out_blob = _DATA_BLOB()
    if not crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    ):
        raise ctypes.WinError()
    try:
        return _blob_to_bytes(out_blob)
    finally:
        if out_blob.pbData:
            kernel32.LocalFree(out_blob.pbData)
        del in_buf


def _dpapi_decrypt(raw: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    in_blob, in_buf = _blob_from_bytes(raw)
    out_blob = _DATA_BLOB()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    ):
        raise ctypes.WinError()
    try:
        return _blob_to_bytes(out_blob)
    finally:
        if out_blob.pbData:
            kernel32.LocalFree(out_blob.pbData)
        del in_buf


def protect_text(value: str) -> str:
    text = str(value or "")
    if not text or is_encrypted(text):
        return text
    if not _is_windows():
        return text
    encrypted = _dpapi_encrypt(text.encode("utf-8"))
    token = base64.urlsafe_b64encode(encrypted).decode("ascii")
    return f"{_ENC_PREFIX}{token}"


def unprotect_text(value: str, *, strict: bool = False) -> str:
    text = str(value or "")
    if not text:
        return text
    if not is_encrypted(text):
        return text
    if not _is_windows():
        if strict:
            raise SecretDecryptionError("Encrypted secret requires Windows DPAPI to be read.")
        return text
    payload = text[len(_ENC_PREFIX) :]
    try:
        raw = base64.urlsafe_b64decode(payload.encode("ascii"))
        return _dpapi_decrypt(raw).decode("utf-8")
    except Exception as exc:
        if strict:
            raise SecretDecryptionError(f"Unable to decrypt DPAPI secret: {exc}") from exc
        return text
