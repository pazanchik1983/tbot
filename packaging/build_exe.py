"""Сборка .exe для Windows 11 через PyInstaller.

Запуск из корня проекта на Windows:
    python packaging/build_exe.py

Результат: dist/TBot/TBot.exe
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    if sys.platform != "win32":
        print("⚠ Скрипт рассчитан на Windows. На других ОС PyInstaller тоже "
              "сработает, но .exe будет valid только для текущей платформы.")

    # очистка предыдущей сборки
    for d in ("build", "dist"):
        p = ROOT / d
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "TBot",
        "--noconfirm", "--clean",
        "--windowed",                     # без консольного окна
        "--icon", str(ROOT / "tbot/resources/app.ico"),
        "--collect-submodules", "tinkoff.invest",
        "--collect-submodules", "lightgbm",
        "--collect-data", "ta",
        "--hidden-import", "pyqtgraph",
        "--hidden-import", "keyring.backends.Windows",
        "--add-data", f"{ROOT / 'tbot/resources'};tbot/resources",
        "tbot/__main__.py",
    ]

    # убираем флаг --icon, если иконки нет
    if not (ROOT / "tbot/resources/app.ico").exists():
        i = cmd.index("--icon")
        del cmd[i:i + 2]

    # ⬇ ЗАЩИТА: убираем --add-data, если папки resources нет
    if not (ROOT / "tbot/resources").exists():
        i = cmd.index("--add-data")
        del cmd[i:i + 2]

    print("→", " ".join(cmd))
    r = subprocess.call(cmd, cwd=ROOT)
    if r != 0:
        return r

    print("\n✔ Готово. Запуск: dist/TBot/TBot.exe")
    print("Для инсталлятора .exe запустите: iscc packaging/installer.iss")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
