from __future__ import annotations

import base64
import ctypes
import json
import os
from ctypes import wintypes
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_CODEX_MODEL = "gpt-6-astra"
DEFAULT_CODEX_REASONING = "high"

@dataclass
class ProviderSettings:
    provider: str = "Codex（ChatGPT 登录）"
    base_url: str = "https://api.openai.com/v1"
    model: str = DEFAULT_CODEX_MODEL
    api_key: str = ""
    send_preview: bool = False


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> tuple[DATA_BLOB, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data)
    return DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer


def protect(data: str) -> str:
    if not data:
        return ""
    if os.name != "nt":
        return base64.b64encode(data.encode()).decode()
    source, source_buffer = _blob(data.encode("utf-8"))
    output = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(source), "Ti5 API Key", None, None, None, 0, ctypes.byref(output)):
        raise ctypes.WinError()
    try:
        raw = ctypes.string_at(output.pbData, output.cbData)
        return base64.b64encode(raw).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)


def unprotect(value: str) -> str:
    if not value:
        return ""
    raw = base64.b64decode(value)
    if os.name != "nt":
        return raw.decode()
    source, source_buffer = _blob(raw)
    output = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(output)):
        return ""
    try:
        return ctypes.string_at(output.pbData, output.cbData).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        base = Path(os.getenv("LOCALAPPDATA", Path.home())) / "Ti5ScanRebuild"
        self.path = path or base / "settings.json"

    def load(self) -> ProviderSettings:
        if not self.path.exists():
            return ProviderSettings()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            data["api_key"] = unprotect(data.pop("api_key_encrypted", ""))
            return ProviderSettings(**{k: v for k, v in data.items() if k in ProviderSettings.__annotations__})
        except Exception:
            return ProviderSettings()

    def save(self, settings: ProviderSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(settings)
        data["api_key_encrypted"] = protect(data.pop("api_key"))
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
