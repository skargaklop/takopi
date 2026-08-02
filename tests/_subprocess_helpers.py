"""Cross-platform helpers for tests that need executable subprocess scripts."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def make_executable_script(
    tmp_path: Path, script_text: str, name: str = "runner"
) -> str:
    """Write a Python script and return a cross-platform executable command path.

    On Unix: writes the script, chmods it 0o755, returns its path (shebang works).
    On Windows: writes the script + a .bat wrapper that invokes sys.executable.
    """
    script = tmp_path / f"{name}.py"
    script.write_text(script_text, encoding="utf-8")
    if sys.platform == "win32":
        wrapper = tmp_path / f"{name}.bat"
        wrapper.write_text(
            f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n',
            encoding="utf-8",
        )
        return str(wrapper)
    os.chmod(script, 0o755)
    return str(script)
