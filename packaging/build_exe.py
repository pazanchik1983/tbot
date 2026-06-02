"""Build .exe for Windows 11 via PyInstaller.

Run from project root on Windows:
    python packaging/build_exe.py

Result: dist/TBot/TBot.exe
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    if sys.platform != "win32":
        print("[WARN] This script is designed for Windows. On other OS PyInstaller "
              "will also work, but .exe will be valid only for current platform.")

    # cleanup previous build
    for d in ("build", "dist"):
        p = ROOT / d
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "TBot",
        "--noconfirm", "--clean",
        "--windowed",
        "--icon", str(ROOT / "tbot/resources/app.ico"),
        "--collect-submodules", "tinkoff.invest",
        "--collect-submodules", "lightgbm",
        "--collect-submodules", "scipy",          # <-- НОВОЕ
        "--collect-data", "ta",
        "--hidden-import", "pyqtgraph",
        "--hidden-import", "keyring.backends.Windows",
        "--hidden-import", "scipy._cyutility",    # <-- НОВОЕ
        "--hidden-import", "scipy._lib._ccallback_c",  # <-- НОВОЕ
        "--add-data", f"{ROOT / 'tbot/resources'};tbot/resources",
        "tbot/__main__.py",
    ]

    # remove --icon if icon file missing
    if not (ROOT / "tbot/resources/app.ico").exists():
        i = cmd.index("--icon")
        del cmd[i:i + 2]

    # remove --add-data if resources folder missing
    if not (ROOT / "tbot/resources").exists():
        i = cmd.index("--add-data")
        del cmd[i:i + 2]

    print("CMD:", " ".join(cmd))
    r = subprocess.call(cmd, cwd=ROOT)
    if r != 0:
        return r

    print("\n[OK] Build complete. Run: dist/TBot/TBot.exe")
    print("For installer run: iscc packaging/installer.iss")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
