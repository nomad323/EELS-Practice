"""Test a built Windows exe with an existing isolated Chromium browser.

Usage: python tests/windows_binary_smoke.py EXE BROWSER NEW_OUTPUT_DIRECTORY
No installs or personal profiles. A child-only BROWSER override captures the
real exe's URL; Windows default-browser association remains operator acceptance.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import struct
import subprocess
import sys
import time
from urllib.parse import urlsplit


def wait_for(check, timeout, message):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.1)
    raise RuntimeError(message)


class CDP:
    """Minimal synchronous loopback WebSocket client for this offline test only."""
    def __init__(self, port, path):
        self.socket = socket.create_connection(("127.0.0.1", port), timeout=20)
        key = base64.b64encode(os.urandom(16)).decode()
        self.socket.sendall((f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\n"
                             f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        header = b""
        while not header.endswith(b"\r\n\r\n"):
            header += self.read(1)
            if len(header) > 8192:
                raise RuntimeError("Oversized WebSocket handshake")
        accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest())
        if not header.startswith(b"HTTP/1.1 101 ") or accept not in header:
            raise RuntimeError("WebSocket handshake failed")
        self.next_id = 0
        self.exceptions = []

    def read(self, length):
        result = b""
        while len(result) < length:
            part = self.socket.recv(length - len(result))
            if not part:
                raise RuntimeError("CDP socket closed")
            result += part
        return result

    def send(self, payload, opcode=1):
        length = len(payload)
        prefix = bytes([0x80 | opcode])
        if length < 126:
            prefix += bytes([0x80 | length])
        elif length <= 65535:
            prefix += bytes([0x80 | 126]) + struct.pack("!H", length)
        else:
            prefix += bytes([0x80 | 127]) + struct.pack("!Q", length)
        mask = os.urandom(4)
        self.socket.sendall(prefix + mask + bytes(v ^ mask[i % 4] for i, v in enumerate(payload)))

    def receive(self):
        message = b""
        while True:
            first, second = self.read(2)
            length = second & 127
            if length == 126:
                length = struct.unpack("!H", self.read(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self.read(8))[0]
            if second & 128 or length > 16 * 1024 * 1024:
                raise RuntimeError("Unexpected CDP frame")
            payload = self.read(length)
            opcode = first & 15
            if opcode == 8:
                raise RuntimeError("CDP closed")
            if opcode == 9:
                self.send(payload, 10)
                continue
            if opcode == 10:
                continue
            if opcode not in (0, 1):
                raise RuntimeError("Unexpected CDP message type")
            message += payload
            if first & 128:
                return json.loads(message)

    def command(self, method, params=None, session=None):
        self.next_id += 1
        request = {"id": self.next_id, "method": method, "params": params or {}}
        if session:
            request["sessionId"] = session
        self.send(json.dumps(request).encode())
        while True:
            response = self.receive()
            if response.get("method") == "Runtime.exceptionThrown":
                self.exceptions.append(response["params"])
            if response.get("id") == self.next_id:
                if "error" in response:
                    raise RuntimeError(str(response["error"]))
                return response["result"]

    def evaluate(self, source, session):
        response = self.command("Runtime.evaluate", {"expression": source, "returnByValue": True}, session)
        if "exceptionDetails" in response:
            raise RuntimeError(str(response["exceptionDetails"]))
        return response["result"].get("value")


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--capture-url":
        Path(os.environ["EELS_TEST_LAUNCH_URL_FILE"]).write_text(sys.argv[2], encoding="utf-8")
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exe", type=Path)
    parser.add_argument("browser", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Run on Windows with an already built exe and installed Chromium.")
    exe, browser, output = args.exe.resolve(), args.browser.resolve(), args.output.resolve()
    if not exe.is_file() or not browser.is_file():
        parser.error("Missing exe or browser")
    output.mkdir(parents=True, exist_ok=False)
    profile, captured = output / "isolated-browser-profile", output / "launch-url.txt"
    env = dict(os.environ)
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    system_root = os.environ["SystemRoot"]  # Windows environ ignores case; dict(env) does not.
    env["PATH"] = os.pathsep.join([str(Path(system_root) / "System32"), system_root])
    env["BROWSER"] = f'"{sys.executable}" "{Path(__file__).resolve()}" --capture-url "%s"'
    env["EELS_TEST_LAUNCH_URL_FILE"] = str(captured)
    subprocess.run([str(exe), "--self-test", str(output / "relocated-self-test.json")], cwd=output, env=env, check=True, timeout=90)
    report = json.loads((output / "relocated-self-test.json").read_text(encoding="utf-8"))
    if report.get("frozen") is not True or report.get("status") != "PASS":
        raise RuntimeError("Relocated binary self-test failed")
    app, chrome, cdp = None, None, None
    try:
        app = subprocess.Popen([str(exe)], cwd=output, env=env)
        wait_for(lambda: captured.is_file() or app.poll() is not None, 30, "No launch URL from packaged app")
        if app.poll() is not None:
            raise RuntimeError(f"Packaged launcher exited early: {app.returncode}")
        url = captured.read_text(encoding="utf-8")
        parsed = urlsplit(url)
        if parsed.hostname != "127.0.0.1" or not parsed.fragment.startswith("desktop="):
            raise RuntimeError("Not a loopback portable launch URL")
        with (output / "browser-stderr.txt").open("wb") as stderr:
            chrome = subprocess.Popen([str(browser), "--headless=new", "--disable-gpu", "--no-proxy-server",
                "--disable-background-networking", "--disable-component-update", "--no-first-run",
                "--no-default-browser-check", "--disable-default-apps", "--disable-sync",
                f"--user-data-dir={profile}", "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0", "about:blank"],
                cwd=output, stdout=subprocess.DEVNULL, stderr=stderr)
            active = profile / "DevToolsActivePort"
            wait_for(lambda: active.is_file(), 25, "Browser DevTools did not start")
            port, endpoint = active.read_text().splitlines()[:2]
            cdp = CDP(int(port), endpoint)
            product = cdp.command("Browser.getVersion")["product"]
            unrelated = cdp.command("Target.createTarget", {"url": "about:blank"})["targetId"]

            def ready(session):
                wait_for(lambda: cdp.evaluate("document.documentElement.dataset.desktop === 'connected' && document.body.dataset.ready === 'true' && !running && !dirty", session), 20, "UI not ready")
                if cdp.evaluate("document.getElementById('error').textContent", session):
                    raise RuntimeError("UI error")

            def open_page():
                target = cdp.command("Target.createTarget", {"url": "about:blank"})["targetId"]
                session = cdp.command("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
                cdp.command("Runtime.enable", session=session)
                cdp.command("Page.enable", session=session)
                cdp.command("Emulation.setDeviceMetricsOverride", {"width": 1920, "height": 1080, "deviceScaleFactor": 1, "mobile": False}, session)
                cdp.command("Page.navigate", {"url": url}, session)
                ready(session)
                return target, session

            first, session = open_page()
            baseline = float(cdp.evaluate("document.getElementById('fwhm').textContent", session))
            if abs(baseline - 8) > 0.2:
                raise RuntimeError("Browser baseline FWHM incorrect")
            layouts = []
            saved_frame = cdp.evaluate("JSON.stringify({controls,frame:lastFrame})", session)
            for width, height, dpr in [(1280, 600, 1), (1920, 1080, 1), (1984, 1066, 1.5), (3072, 1728, 1), (1366, 768, 2)]:
                cdp.command("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": dpr, "mobile": False}, session)
                cdp.command("Runtime.evaluate", {"expression": "new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))", "awaitPromise": True}, session)
                layout = cdp.evaluate("""(() => {
                    const root = parseFloat(getComputedStyle(document.documentElement).fontSize);
                    const row = document.getElementById('row-D10'), input = document.getElementById('value-D10');
                    const plots = [document.getElementById('spot'), document.getElementById('spectrum')];
                    const els = [...plots, document.getElementById('fwhm'), ...document.querySelectorAll('.coefficient:not([hidden])'),
                        ...document.querySelectorAll('.coefficient:not([hidden]) input, .coefficient:not([hidden]) button')];
                    const header = document.querySelector('header').getBoundingClientRect().bottom;
                    const hidden = els.filter(el => { const r = el.getBoundingClientRect();
                        return r.width <= 0 || r.height <= 0 || r.left < 0 || r.top < header || r.right > innerWidth || r.bottom > innerHeight
                            || !el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)); }).map(el => el.id);
                    return {width:innerWidth,height:innerHeight,dpr:devicePixelRatio,root,
                        input:parseFloat(getComputedStyle(input).fontSize), label:parseFloat(getComputedStyle(row.querySelector('label')).fontSize),
                        inputHeight:input.getBoundingClientRect().height, rowHeight:row.getBoundingClientRect().height,
                        canvasFont:parseFloat(plots[1].getContext('2d').font), hidden,
                        zoom:getComputedStyle(document.documentElement).zoom,
                        overflow:document.documentElement.scrollWidth > innerWidth,
                        buffers:plots.every(c => c.width === Math.round(c.clientWidth*devicePixelRatio) && c.height === Math.round(c.clientHeight*devicePixelRatio))};
                })()""", session)
                if layout["hidden"] or layout["overflow"] or not layout["buffers"] or layout["zoom"] not in ("1", "normal"):
                    raise RuntimeError(f"Layout visibility/DPI failure: {layout}")
                if width >= 1920 and (min(layout["root"], layout["input"], layout["canvasFont"]) < 18 or layout["label"] < 16 or layout["inputHeight"] < 28 or layout["rowHeight"] < 45):
                    raise RuntimeError(f"Large-screen type/controls too small: {layout}")
                if width == 1280 and layout["root"] != 12:
                    raise RuntimeError("Short-window baseline changed")
                if cdp.evaluate("JSON.stringify({controls,frame:lastFrame})", session) != saved_frame:
                    raise RuntimeError("Resizing changed simulation/controls")
                layouts.append(layout)
                shot = cdp.command("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}, session)["data"]
                (output / f"layout-{width}x{height}-dpr{dpr}.png").write_bytes(base64.b64decode(shot))
            previous = cdp.evaluate("session", session)
            cdp.command("Page.reload", {"ignoreCache": True}, session)
            wait_for(lambda: cdp.evaluate(f"typeof session !== 'undefined' && session !== {json.dumps(previous)}", session), 20, "Reload did not rebuild session")
            ready(session)
            second, session2 = open_page()
            cdp.command("Target.closeTarget", {"targetId": first})
            time.sleep(8)
            if app.poll() is not None:
                raise RuntimeError("Closing one tab killed the other")
            cdp.command("Page.setWebLifecycleState", {"state": "frozen"}, session2)
            time.sleep(8)
            if app.poll() is not None:
                raise RuntimeError("Frozen JS killed the app")
            cdp.command("Page.setWebLifecycleState", {"state": "active"}, session2)
            ready(session2)
            screenshot = cdp.command("Page.captureScreenshot", {"format": "png"}, session2)["data"]
            (output / "windows-ui.png").write_bytes(base64.b64decode(screenshot))
            closing = time.monotonic()
            cdp.command("Target.closeTarget", {"targetId": second})
            app.wait(timeout=15)
            elapsed = time.monotonic() - closing
            if app.returncode != 0:
                raise RuntimeError(f"Packaged launcher exit code: {app.returncode}")
            if unrelated not in [t["targetId"] for t in cdp.command("Target.getTargets")["targetInfos"]]:
                raise RuntimeError("Unrelated browser tab was closed")
            with socket.socket() as connection:
                connection.settimeout(2)
                if connection.connect_ex(("127.0.0.1", parsed.port)) == 0:
                    raise RuntimeError("App still listening")
            if cdp.exceptions:
                raise RuntimeError(str(cdp.exceptions))
            report = {"status": "PASS", "platform": platform.platform(), "frozen": True, "browser": product,
                      "baseline_display_mev": baseline, "exit_after_last_tab_seconds": round(elapsed, 3), "readable_layouts": layouts,
                      "default_browser_association": "NOT TESTED (child BROWSER override)",
                      "checks": ["relocated binary with Python removed from PATH", "actual exe launch URL", "isolated Windows browser render/SSE",
                                 "real reload", "multiple tabs", "frozen JS", "last tab exits exe", "port released", "unrelated tab survives", "no JS exceptions"]}
            (output / "windows-browser-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        if cdp:
            try:
                cdp.command("Browser.close")
            except (OSError, RuntimeError):
                pass
            cdp.socket.close()
        if chrome and chrome.poll() is None:
            try:
                chrome.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # Only the process tree we created with a private test profile.
                subprocess.run([str(Path(system_root) / "System32/taskkill.exe"), "/PID", str(chrome.pid), "/T", "/F"], check=False, stdout=subprocess.DEVNULL)
                chrome.wait(timeout=10)
        if app and app.poll() is None:
            app.terminate()
            app.wait(timeout=10)


if __name__ == "__main__":
    main()
