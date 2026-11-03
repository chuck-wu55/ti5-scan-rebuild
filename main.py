import os
import sys
from pathlib import Path


def _prepare_frozen_dll_paths() -> None:
    """Register bundled Qt/Shiboken directories before importing PySide6."""
    if not getattr(sys, "frozen", False) or not hasattr(os, "add_dll_directory"):
        return
    root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    for candidate in (root, root / "PySide6", root / "shiboken6"):
        if candidate.is_dir():
            os.add_dll_directory(str(candidate))


_prepare_frozen_dll_paths()

from ti5_app.ui_qt import run


if __name__ == "__main__":
    run()
