from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def _resource_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))


def codex_candidates() -> list[Path]:
    """Return likely Codex executables, including the Windows desktop app runtime."""
    candidates: list[Path] = []
    for name in ("TI5_CODEX_BIN", "CODEX_BIN"):
        value = os.environ.get(name, "").strip().strip('"')
        if value:
            candidates.append(Path(value).expanduser())

    # A release may carry the official CLI runtime beside its Python resources.
    candidates.extend([
        _resource_root() / "resources" / "codex-runtime" / "codex.exe",
        Path(sys.executable).resolve().parent / "_internal" / "resources" / "codex-runtime" / "codex.exe",
        Path(__file__).resolve().parents[1] / "resources" / "codex-runtime" / "codex.exe",
    ])

    for name in ("codex.exe", "codex"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))

    local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    desktop_bin = local_app_data / "OpenAI" / "Codex" / "bin"
    if desktop_bin.is_dir():
        candidates.extend(sorted(
            desktop_bin.glob("*/codex.exe"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        ))
    windows_apps = local_app_data / "Microsoft" / "WindowsApps"
    if windows_apps.is_dir():
        candidates.extend(sorted(windows_apps.glob("OpenAI.Codex_*/*/resources/codex.exe"), reverse=True))
        candidates.extend(sorted(windows_apps.glob("OpenAI.Codex_*/app/resources/codex.exe"), reverse=True))

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            key = str(candidate.resolve()).casefold()
        except OSError:
            key = str(candidate).casefold()
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def find_codex() -> str | None:
    for candidate in codex_candidates():
        if candidate.is_file():
            return str(candidate.resolve())
    return None


def resolve_codex() -> str:
    executable = find_codex()
    if executable:
        return executable
    raise FileNotFoundError(
        "未找到 Codex 运行时。请安装 Codex 桌面应用或 Codex CLI；也可通过 "
        "TI5_CODEX_BIN 指定 codex.exe。"
    )
