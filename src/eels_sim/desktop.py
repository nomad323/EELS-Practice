"""Portable browser launcher; no browser engine, tray service or instrument I/O."""
import argparse
import io
import json
from pathlib import Path
import secrets
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit
import urllib.request
import webbrowser

import numpy as np

from .server import Handler, LocalServer


class BrowserLifetime:
    """Live HTTP streams, not JS timers (which browsers throttle in background)."""

    def __init__(self, startup_timeout=90.0, close_grace=5.0, clock=time.monotonic):
        self.token = secrets.token_urlsafe(32)
        self.clock = clock
        self.close_grace = close_grace
        self.deadline = clock() + startup_timeout
        self.connected_once = False
        self.connections = set()
        self.lock = threading.Lock()
        self.stopping = threading.Event()

    def attach(self):
        with self.lock:
            if self._expired():
                self.stopping.set()
                return None
            connection = object()
            self.connections.add(connection)
            self.connected_once = True
            return connection

    def detach(self, connection):
        with self.lock:
            if connection not in self.connections:
                return
            self.connections.remove(connection)
            if not self.connections:
                self.deadline = self.clock() + self.close_grace

    def _expired(self):
        return self.stopping.is_set() or (not self.connections and self.clock() >= self.deadline)

    def expired(self):
        with self.lock:
            if self._expired():
                self.stopping.set()  # Latch expiry; a late connection cannot revive it.
            return self.stopping.is_set()


class DesktopHandler(Handler):
    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path != "/api/desktop/events":
            return super().do_GET()
        if not self._local_request():
            self.json_response(403, {"error": "仅允许本机同源访问"})
            return
        query = parse_qs(parsed.query)
        token = query.get("token", [])
        lifetime = self.server.lifetime
        if (set(query) != {"token"} or len(token) != 1
                or not secrets.compare_digest(token[0].encode(), lifetime.token.encode())):
            self.json_response(403, {"error": "启动链接已失效，请重新双击程序"})
            return
        connection = lifetime.attach()
        if connection is None:
            self.json_response(410, {"error": "程序正在退出，请重新双击程序"})
            return
        try:
            self.connection.settimeout(3)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            # Background/frozen JS need not run. A closed/crashed browser drops
            # the socket; repeated writes detect that even without pagehide.
            while not lifetime.stopping.is_set():
                self.wfile.write(b"data: alive\n\n")
                self.wfile.flush()
                lifetime.stopping.wait(1)
        except OSError:
            pass
        finally:
            self.close_connection = True
            lifetime.detach(connection)


class DesktopServer(LocalServer):
    def __init__(self, lifetime):
        self.lifetime = lifetime
        super().__init__(0, handler_class=DesktopHandler)


def run(opener=webbrowser.open, lifetime=None):
    lifetime = lifetime if lifetime is not None else BrowserLifetime()
    server = DesktopServer(lifetime)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/#desktop={lifetime.token}"
        if not opener(url):
            raise RuntimeError("无法打开默认浏览器。请在 Windows 设置中配置默认浏览器后重试。")
        while not lifetime.expired():
            lifetime.stopping.wait(0.2)
        if not lifetime.connected_once:
            raise RuntimeError("90 秒内未连接到程序网页，服务已关闭。请检查默认浏览器、本机代理或安全软件后重新双击程序。")
    finally:
        lifetime.stopping.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def self_test(report_path):
    """Offline packaged-binary check. Never opens a browser or connects hardware."""
    server = LocalServer(0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = f"http://127.0.0.1:{server.server_port}"

    def request(path, data=None):
        body = None if data is None else json.dumps(data).encode()
        req = urllib.request.Request(base + path, data=body, headers={"Content-Type": "application/json"})
        with opener.open(req, timeout=30) as response:
            return response.read()

    try:
        for path in ("/", "/app.js", "/desktop.js", "/style.css"):
            if not request(path):
                raise RuntimeError(f"缺少资源 {path}")
        meta = json.loads(request("/api/meta"))
        session = json.loads(request("/api/session", {}))["session"]
        frame = json.loads(request("/api/frame", {"session": session}))
        fwhm = frame["metrics"]["fwhm_mev"]
        if not 7.8 <= fwhm <= 8.2 or not frame["image_png"]:
            raise RuntimeError("零像差/PNG 自检失败")
        with np.load(io.BytesIO(request("/api/export", {"session": session})), allow_pickle=False) as sample:
            if not np.array_equal(sample["spectrum"], sample["counts"].sum(axis=0)):
                raise RuntimeError("NPZ 积分谱自检失败")
        report = {"status": "PASS", "frozen": bool(getattr(sys, "frozen", False)),
                  "model_version": meta["model_version"], "baseline_fwhm_mev": fwhm,
                  "checks": ["web assets", "loopback HTTP", "NumPy simulation", "Pillow PNG", "NPZ export"]}
        Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def main():
    parser = argparse.ArgumentParser(description="EELS 便携版：浏览器打开，关闭最后一个程序页面后退出")
    parser.add_argument("--self-test", metavar="REPORT_JSON", help="只运行离线打包自检并保存报告，不打开浏览器")
    args = parser.parse_args()
    if args.self_test:
        self_test(args.self_test)
    else:
        run()
