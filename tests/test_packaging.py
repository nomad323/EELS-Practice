from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import build_windows


class PackagingTests(unittest.TestCase):
    def test_lightweight_build_command_and_resources(self):
        command = build_windows.pyinstaller_command(Path("output space"), Path("work space"))
        for flag in ("--onedir", "--windowed", "--noupx"):
            self.assertIn(flag, command)
        self.assertNotIn("--onefile", command)
        self.assertNotIn("--noconfirm", command)
        self.assertTrue(command[-1].endswith("run_desktop.py"))
        self.assertTrue(command[command.index("--add-data") + 1].endswith("web:eels_sim/web"))
        self.assertFalse(any("raw/" in arg or "processed/" in arg for arg in command))

    def test_linux_build_is_refused_before_any_subprocess(self):
        with patch.object(build_windows.sys, "platform", "linux"), \
                patch.object(build_windows.sys, "argv", ["build_windows.py"]), \
                patch.object(build_windows.subprocess, "run") as invoke:
            with self.assertRaises(SystemExit) as error:
                build_windows.main()
            self.assertEqual(error.exception.code, 2)
            invoke.assert_not_called()

    def test_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "existing"
            output.mkdir()
            original = output / "human.txt"
            original.write_text("preserve", encoding="utf-8")
            with patch.object(build_windows.sys, "platform", "win32"), \
                    patch.object(build_windows.platform, "machine", return_value="AMD64"), \
                    patch.object(build_windows.sys, "prefix", "venv"), \
                    patch.object(build_windows.sys, "base_prefix", "base"), \
                    patch.object(build_windows.sys, "argv", ["build_windows.py", "--output", str(output)]), \
                    patch.object(build_windows, "version", return_value="test"), \
                    patch.object(build_windows.subprocess, "run") as invoke:
                with self.assertRaises(FileExistsError):
                    build_windows.main()
                invoke.assert_not_called()
            self.assertEqual(original.read_text(encoding="utf-8"), "preserve")


if __name__ == "__main__":
    unittest.main()
