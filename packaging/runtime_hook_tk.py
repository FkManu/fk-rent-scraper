from __future__ import annotations

import os
import sys
from pathlib import Path


def _bundle_root() -> Path:
    raw = getattr(sys, "_MEIPASS", "")
    if raw:
        return Path(raw).resolve()
    return Path(__file__).resolve().parent


root = _bundle_root()
tcl_library = root / "tcl8.6"
tk_library = root / "tk8.6"

if tcl_library.exists():
    os.environ["TCL_LIBRARY"] = str(tcl_library)
if tk_library.exists():
    os.environ["TK_LIBRARY"] = str(tk_library)
