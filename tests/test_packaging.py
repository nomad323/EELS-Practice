from pathlib import Path
import hashlib
import io
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import build_macos, build_windows


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


class MacPackagingTests(unittest.TestCase):
    def test_sha256_uses_bounded_reads_without_file_digest(self):
        class TrackedStream(io.BytesIO):
            sizes = []

            def read(self, size=-1):
                self.sizes.append(size)
                return super().read(size)

        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "archive.zip"
            contents = b"eels-practice" * 200000
            archive.write_bytes(contents)
            with patch.object(build_macos.hashlib, "file_digest", side_effect=AssertionError("Python 3.10 has no file_digest"), create=True):
                self.assertEqual(build_macos.sha256_file(archive), hashlib.sha256(contents).hexdigest())
                stream = TrackedStream(contents)
                self.assertEqual(build_macos.sha256_file(Mock(open=Mock(return_value=stream))), hashlib.sha256(contents).hexdigest())
                self.assertTrue(stream.sizes and all(0 < size <= 1024 * 1024 for size in stream.sizes))

    def test_native_app_command_and_resources(self):
        with patch.object(build_macos.platform, "machine", return_value="arm64"):
            command = build_macos.pyinstaller_command(Path("output space"), Path("work space"))
        for flag in ("--onedir", "--windowed", "--noupx", "--osx-bundle-identifier"):
            self.assertIn(flag, command)
        self.assertNotIn("--onefile", command)
        self.assertEqual(command[command.index("--target-architecture") + 1], "arm64")
        self.assertTrue(command[-1].endswith("run_desktop.py"))
        self.assertTrue(command[command.index("--add-data") + 1].endswith("web:eels_sim/web"))
        self.assertFalse(any("raw/" in arg or "processed/" in arg for arg in command))

    def test_non_macos_build_is_refused_before_any_subprocess(self):
        with patch.object(build_macos.sys, "platform", "linux"), \
                patch.object(build_macos.sys, "argv", ["build_macos.py"]), \
                patch.object(build_macos.subprocess, "run") as invoke:
            with self.assertRaises(SystemExit) as error:
                build_macos.main()
            self.assertEqual(error.exception.code, 2)
            invoke.assert_not_called()

    def test_unknown_macos_architecture_is_refused(self):
        with patch.object(build_macos.sys, "platform", "darwin"), \
                patch.object(build_macos.platform, "machine", return_value="mips"), \
                patch.object(build_macos.sys, "argv", ["build_macos.py"]), \
                patch.object(build_macos.subprocess, "run") as invoke:
            with self.assertRaises(SystemExit) as error:
                build_macos.main()
            self.assertEqual(error.exception.code, 2)
            invoke.assert_not_called()


if __name__ == "__main__":
    unittest.main()
