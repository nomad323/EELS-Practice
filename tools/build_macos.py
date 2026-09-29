#!/usr/bin/env python3
"""Build a native macOS app in an approved, isolated venv. Never installs dependencies."""
import argparse
from datetime import datetime
import hashlib
from importlib.metadata import distribution, version
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "EELS-Practice"


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def architecture():
    machine = platform.machine().lower()
    return {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x86_64"}.get(machine)


def pyinstaller_command(output, work):
    arch = architecture() or platform.machine().lower()
    return [sys.executable, "-m", "PyInstaller", "--onedir", "--windowed", "--noupx",
            "--name", APP_NAME, "--osx-bundle-identifier", "com.nwhphy.eelspractice",
            "--target-architecture", arch,
            "--distpath", str(output), "--workpath", str(work / "build"),
            "--specpath", str(work), "--paths", str(ROOT / "src"),
            "--add-data", f"{ROOT / 'src/eels_sim/web'}:eels_sim/web",
            "--exclude-module", "tkinter", "--exclude-module", "matplotlib",
            "--exclude-module", "scipy", "--exclude-module", "pandas",
            str(ROOT / "run_desktop.py")]


def python_license():
    version_dir = f"python{sys.version_info.major}.{sys.version_info.minor}"
    candidates = [
        Path(sys.base_prefix) / "LICENSE.txt",
        Path(sys.base_prefix) / "LICENSE",
        Path(sys.base_prefix) / "lib" / version_dir / "LICENSE.txt",
        Path(sys.base_prefix).parents[3] / "LICENSE" if len(Path(sys.base_prefix).parents) > 3 else Path(),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError("找不到 Python 许可文件，停止分发打包；请使用带许可文件的 Python 发行版。")


def copy_notices(package):
    target = package / "THIRD-PARTY"
    target.mkdir()
    shutil.copy2(python_license(), target / "Python-LICENSE.txt")
    for name in ("numpy", "Pillow", "pyinstaller"):
        dist = distribution(name)
        found = False
        for entry in dist.files or ():
            if not any(word in entry.name.lower() for word in ("license", "copying", "notice")):
                continue
            source = Path(dist.locate_file(entry))
            if not source.is_file() or entry.is_absolute() or ".." in entry.parts:
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
    arch = architecture()
    if sys.platform != "darwin" or arch is None:
        parser.error("必须在 Intel 或 Apple Silicon macOS 上原生构建，不能交叉生成 macOS App。")
    if sys.prefix == sys.base_prefix:
        parser.error("请先使用独立构建 venv，避免修改或打入日常 Python 环境。")

    versions = {name: version(name) for name in ("numpy", "Pillow", "pyinstaller")}
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    output = (args.output or ROOT / "processed/releases" / f"macos-{arch}-{stamp}").resolve()
    output.mkdir(parents=True, exist_ok=False)
    work = ROOT / "processed/build" / f"macos-{arch}-{stamp}"
    work.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))

    subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                   cwd=ROOT, env=env, check=True)
    app_build = work / "dist"
    subprocess.run(pyinstaller_command(app_build, work), cwd=ROOT, check=True)
    app = app_build / f"{APP_NAME}.app"
    executable = app / "Contents" / "MacOS" / APP_NAME
    if not executable.is_file():
        raise RuntimeError("PyInstaller 未生成预期的 macOS App。")

    package = output / f"{APP_NAME}-macOS-{arch}"
    package.mkdir()
    shutil.move(str(app), package / app.name)
    shutil.copy2(ROOT / "tools/macos-readme.txt", package / "使用说明.txt")
    copy_notices(package)

    smoke_cwd = work / "自检 空格"
    smoke_cwd.mkdir()
    smoke_report = output / "self-test.json"
    packaged_executable = package / app.name / "Contents" / "MacOS" / APP_NAME
    subprocess.run([str(packaged_executable), "--self-test", str(smoke_report)],
                   cwd=smoke_cwd, check=True, timeout=90)
    smoke = json.loads(smoke_report.read_text(encoding="utf-8"))
    if smoke.get("status") != "PASS" or smoke.get("frozen") is not True:
        raise RuntimeError("打包程序自检未通过，或运行的不是冻结二进制。")
    subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(package / app.name)],
                   check=True, capture_output=True)

    archive = output / f"{APP_NAME}-macOS-{arch}.zip"
    subprocess.run(["/usr/bin/ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
                    str(package), str(archive)], check=True)
    digest = sha256_file(archive)
    report = {
        "python": sys.version,
        "platform": platform.platform(),
        "architecture": arch,
        "dependencies": versions,
        "archive": archive.name,
        "archive_bytes": archive.stat().st_size,
        "unpacked_bytes": sum(p.stat().st_size for p in package.rglob("*") if p.is_file()),
        "sha256": digest,
        "offline_self_test": "PASS",
        "codesign_structure_check": "PASS (ad hoc; not Developer ID/notarized)",
        "macos_default_browser_acceptance": "NOT RUN",
    }
    (output / "build-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "build-dependencies.txt").write_text(
        "\n".join(f"{name}=={value}" for name, value in versions.items()) + "\n", encoding="utf-8")
    print(f"macOS ZIP：{archive}\n体积：{report['archive_bytes']/1024/1024:.1f} MiB；"
          f"解压后 {report['unpacked_bytes']/1024/1024:.1f} MiB")
    print("请按使用说明验收双击启动、默认浏览器、刷新、关闭网页退出及导出。")


if __name__ == "__main__":
    main()
