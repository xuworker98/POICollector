# -*- coding: utf-8 -*-
"""Windows-user-bound encrypted JSON storage using DPAPI."""
from __future__ import annotations

import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes) -> tuple[_DataBlob, object]:
    buffer = ctypes.create_string_buffer(data)
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def _dpapi(data: bytes, decrypt: bool) -> bytes:
    if os.name != "nt":
        raise RuntimeError("安全配置仅支持 Windows DPAPI")
    in_blob, keepalive = _blob(data)
    out_blob = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if decrypt:
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
        )
    else:
        ok = crypt32.CryptProtectData(
            ctypes.byref(in_blob), "POICollector keys", None, None, None, 0,
            ctypes.byref(out_blob),
        )
    _ = keepalive
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def save_encrypted_json(path: str | Path, value: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
    encrypted = _dpapi(payload, decrypt=False)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_bytes(encrypted)
    os.replace(temporary, target)


def load_encrypted_json(path: str | Path) -> dict:
    target = Path(path)
    if not target.exists():
        return {}
    payload = _dpapi(target.read_bytes(), decrypt=True)
    value = json.loads(payload.decode("utf-8"))
    return value if isinstance(value, dict) else {}
