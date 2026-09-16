"""找到可用的 Python 3.10+ 解释器。

本机可能同时装了旧版 python3（例如 anaconda 3.9）和 Homebrew 新版；
生成页面与识别都需要 3.10+，所以统一走这里挑选。
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

CANDIDATES = ["python3.13", "python3.12", "python3.11", "python3.10", "python3", "python"]
PREFERRED_PATHS = ["/opt/homebrew/bin/python3", "/usr/local/bin/python3"]


def interpreter() -> str:
    """返回一个 3.10+ 解释器路径；找不到时退回当前解释器。"""
    if sys.version_info >= (3, 10):
        return sys.executable or "python3"
    for path in PREFERRED_PATHS:
        resolved = Path(path)
        if resolved.exists() and _usable(str(resolved)):
            return str(resolved)
    for name in CANDIDATES:
        found = shutil.which(name)
        if found and _usable(found):
            return found
    return sys.executable or "python3"


def _usable(path: str) -> bool:
    import subprocess
    try:
        return subprocess.run([path, "-c", "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)"],
                              capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
