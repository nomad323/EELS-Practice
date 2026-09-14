#!/usr/bin/env python3
"""Run in an approved, clean Windows build venv. Never installs dependencies."""
import argparse
from datetime import datetime
import hashlib
from importlib.metadata import distribution, version
import json
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def pyinstaller_command(output, work):
    return [sys.executable, "-m", "PyInstaller", "--onedir", "--windowed", "--noupx",
            "--name", "EELS-Practice", "--distpath", str(output),
            "--workpath", str(work / "build"), "--specpath", str(work),
            "--paths", str(ROOT / "src"),
            "--add-data", f"{ROOT / 'src/eels_sim/web'}:eels_sim/web",
            "--exclude-module", "tkinter", "--exclude-module", "matplotlib",
            "--exclude-module", "scipy", "--exclude-module", "pandas",
            str(ROOT / "run_desktop.py")]


def copy_notices(package):
    target = package / "THIRD-PARTY"
    target.mkdir()
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise RuntimeError("找不到 Python LICENSE.txt，停止分发打包；请使用官方 Windows Python。")
    shutil.copy2(python_license, target / "Python-LICENSE.txt")
    for name in ("numpy", "Pillow", "pyinstaller"):
        dist = distribution(name)
        found = False
        for entry in dist.files or ():
            if not any(word in entry.name.lower() for word in ("license", "copying", "notice")):
                continue
            source = Path(dist.locate_file(entry))
            if not source.is_file():
                continue
            # Keep wheel-relative paths (including NumPy's bundled-library
            # notices); never copy unrelated environment files or raw inputs.
            if entry.is_absolute() or ".." in entry.parts:
                continue
            destination = target / name / entry
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            found = True
        if not found:
            raise RuntimeError(f"找不到 {name} 许可文件，停止分发打包。")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="新的输出目录（拒绝覆盖已有目录）")
    args = parser.parse_args()
    if sys.platform != "win32" or struct.calcsize("P") != 8 or platform.machine().lower() not in ("amd64", "x86_64"):
        parser.error("必须使用 Windows x64 Python 构建，不能在 WSL/Linux 交叉生成 Windows exe。")
    if sys.prefix == sys.base_prefix:
        parser.error("请先使用独立构建 venv，避免打入日常环境的大型依赖。")
    versions = {name: version(name) for name in ("numpy", "Pillow", "pyinstaller")}
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    output = (args.output or ROOT / "processed/releases" / f"windows-{stamp}").resolve()
    output.mkdir(parents=True, exist_ok=False)  # Preserve previous binaries.
    work = ROOT / "processed/build" / f"windows-{stamp}"
    work.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                   cwd=ROOT, env=env, check=True)
    subprocess.run(pyinstaller_command(output, work), cwd=ROOT, check=True)
    package = output / "EELS-Practice"
    copy_notices(package)
    shutil.copy2(ROOT / "tools/portable-readme.txt", package / "使用说明.txt")
    # Run from a different, non-ASCII working directory. No default-browser
    # opening: this verifies packaged DLLs, assets, HTTP, PNG and NPZ offline.
    smoke_cwd = work / "自检 空格"
    smoke_cwd.mkdir()
    smoke_report = output / "self-test.json"
    subprocess.run([str(package / "EELS-Practice.exe"), "--self-test", str(smoke_report)],
                   cwd=smoke_cwd, check=True, timeout=90)
    smoke = json.loads(smoke_report.read_text(encoding="utf-8"))
    if smoke["status"] != "PASS" or smoke.get("frozen") is not True:
        raise RuntimeError("打包程序自检未通过，或运行的不是冻结二进制")
    archive = Path(shutil.make_archive(str(output / "EELS-Practice-windows-x64"), "zip",
                                      root_dir=output, base_dir=package.name))
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    report = {"python": sys.version, "platform": platform.platform(), "dependencies": versions,
              "archive": archive.name, "archive_bytes": archive.stat().st_size,
              "unpacked_bytes": sum(p.stat().st_size for p in package.rglob("*") if p.is_file()),
              "sha256": digest,
              "offline_self_test": "PASS", "windows_browser_acceptance": "NOT RUN"}
    (output / "build-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"便携 ZIP：{archive}\n体积：{report['archive_bytes']/1024/1024:.1f} MiB；解压后 {report['unpacked_bytes']/1024/1024:.1f} MiB")
    print("请按使用说明，在目标 Windows 电脑验收自动开浏览器、刷新、关闭网页退出及导出。")


if __name__ == "__main__":
    main()
