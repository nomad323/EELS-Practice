#!/usr/bin/env python3
"""Portable entry point, also runnable from a checkout for offline validation."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))


def entry():
    try:
        from eels_sim.desktop import main
        main()
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        message = f"EELS 启动/自检失败：{exc}"
        if sys.stderr is not None:
            print(message, file=sys.stderr)
        # A windowed PyInstaller executable has no stderr. Do not silently fail
        # or leave a background process; use the OS dialog, not another GUI kit.
        if sys.platform == "win32" and "--self-test" not in sys.argv:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "EELS 像差练习器", 0x10)
        return 1


if __name__ == "__main__":
    raise SystemExit(entry())
