"""Loopback-only local UI. No external framework, file upload or instrument I/O."""
import argparse
from dataclasses import asdict, dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
import time

import numpy as np

from .model import Config, CONTROL_LIMIT, MAX_ORDER, MODEL_VERSION, POWERS, TERMS, coefficients, simulate, terms_through
from .presentation import export_npz, frame, grayscale
from .training import CUSTOM_AMPLITUDE_MIN, DIFFICULTY, GENERATOR_VERSION, Exercise, checked_controls, new_exercise

WEB = Path(__file__).parent / "web"
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/desktop.js": ("desktop.js", "text/javascript; charset=utf-8"),
          "/style.css": ("style.css", "text/css; charset=utf-8")}


@dataclass
class Session:
    exercise: Exercise | None = None
    revealed: bool = False
    last_result: object = None
    last_labels: dict | None = None
    touched: float = field(default_factory=time.monotonic)
    lock: object = field(default_factory=threading.Lock)


class Application:
    def __init__(self):
        self.sessions = {}
        self.lock = threading.Lock()
        self.compute_lock = threading.Lock()

    def create_session(self):
        with self.lock:
            now = time.monotonic()
            self.sessions = {k: v for k, v in self.sessions.items() if now-v.touched < 4*3600}
            if len(self.sessions) >= 32:
                raise ValueError("本地会话已达 32 个；请重启程序释放旧会话")
            token = secrets.token_urlsafe(32)
            self.sessions[token] = Session()
        return {"session": token}

    def dispatch(self, path, data):
        if not isinstance(data, dict):
            raise ValueError("请求必须是 JSON 对象")
        if path == "/api/session":
            if data:
                raise ValueError("创建会话无需参数")
            return self.create_session()
        if path not in ("/api/frame", "/api/export"):
            raise KeyError("接口不存在")
        token = data.get("session")
        if not isinstance(token, str):
            raise ValueError("缺少会话，请刷新页面")
        with self.lock:
            session = self.sessions.get(token)
            if session is None:
                raise ValueError("会话已失效，请刷新页面")
            session.touched = time.monotonic()
        with session.lock:
            if path == "/api/export":
                if set(data) != {"session"} or session.last_result is None:
                    raise ValueError("请先生成一帧图像，再导出")
                return export_npz(session.last_result, session.last_labels)
            return self.render(session, data)

    def render(self, session, data):
        allowed = {"session", "mode", "action", "controls", "config", "seed", "difficulty", "custom_amplitude", "term_count", "max_order", "gamma", "vmax"}
        if set(data) - allowed:
            raise ValueError("请求中含未知字段")
        mode, action = data.get("mode", "free"), data.get("action", "update")
        if mode not in ("free", "practice") or action not in ("update", "new", "reveal", "hide", "retry"):
            raise ValueError("未知模式或操作")
        config = Config.from_dict(data.get("config", {}))
        max_order = data.get("max_order", 3)
        terms_through(max_order)  # Validate even a draft setting before mutation.
        controls = checked_controls(data.get("controls", {}))
        # Validate presentation before mutating an exercise's state.
        grayscale(np.zeros((1, 1)), data.get("gamma", 0.5), data.get("vmax"))
        if mode == "practice":
            if action == "new" or session.exercise is None:
                session.exercise = new_exercise(data.get("seed", 42), data.get("difficulty", "medium"),
                                                data.get("term_count", 9), config, max_order,
                                                custom_amplitude=data.get("custom_amplitude"))
                session.revealed = False
                controls = coefficients()
            if action == "retry":
                controls = coefficients()
                session.revealed = False
            # Updates use the actual question's order, not unsaved UI settings.
            checked_controls(controls, session.exercise.max_order)
            if action == "reveal":
                session.revealed = True
            if action == "hide":
                session.revealed = False
            effective = session.exercise.residual(controls)
            labels = session.exercise.feedback(controls)
        else:
            effective, labels = controls, {"controls": controls, "mode": "free", "max_order": MAX_ORDER}
            session.revealed = False
        start = time.perf_counter()
        with self.compute_lock:
            result = simulate(effective, config)
            response = frame(result, data.get("gamma", 0.5), data.get("vmax"))
        response.update(mode=mode, controls=controls, elapsed_ms=round((time.perf_counter()-start)*1000, 1))
        if mode == "practice":
            response["question"] = {"seed": session.exercise.seed, "difficulty": session.exercise.difficulty,
                                    "term_count": session.exercise.term_count, "max_order": session.exercise.max_order,
                                    "generator_version": session.exercise.generator_version,
                                    "amplitude": session.exercise.amplitude}
            if session.revealed:
                response["feedback"] = labels
        session.last_result, session.last_labels = result, labels
        return response


class Handler(BaseHTTPRequestHandler):
    server_version = "EELSLocal/1.0"
    protocol_version = "HTTP/1.1"
    # Reuse loopback connections instead of reconnecting/thread-starting for
    # every slider update. Avoid Nagle/delayed-ACK stalls on separate headers
    # and body writes; idle keep-alive handlers must not linger indefinitely.
    disable_nagle_algorithm = True
    timeout = 30

    def parse_request(self):
        if not super().parse_request():
            return False
        if self.request_version == "HTTP/0.9":
            return True  # Headerless requests are rejected by the Host gate.
        lengths = self.headers.get_all("Content-Length", [])
        # This API accepts fixed-length JSON POSTs and bodyless GETs only.
        # Reject ambiguous/unread bodies before reusing a persistent stream,
        # including the desktop GET endpoint which subclasses this handler.
        if ("Transfer-Encoding" in self.headers or len(lengths) > 1
                or self.command == "GET" and lengths not in ([], ["0"])):
            self.json_response(400, {"error": "不支持的请求体长度或传输编码"})
            return False
        return True

    def _local_request(self):
        port = self.server.server_port
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host", "") not in hosts:
            return False
        origin = self.headers.get("Origin")
        return (origin is None or origin in {f"http://{h}" for h in hosts}) and self.headers.get("Sec-Fetch-Site") != "cross-site"

    def send_content(self, status, body, content_type):
        # Errors can reject a POST before consuming its body. Never interpret
        # those unread bytes as the next request on a keep-alive connection.
        if status >= 400:
            self.close_connection = True
        self.send_response(status)
        if self.close_connection:
            self.send_header("Connection", "close")
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        if content_type == "application/octet-stream":
            self.send_header("Content-Disposition", 'attachment; filename="eels-sample.npz"')
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def json_response(self, status, value):
        self.send_content(status, json.dumps(value, ensure_ascii=False, allow_nan=False).encode(), "application/json; charset=utf-8")

    def do_GET(self):
        if not self._local_request():
            self.json_response(403, {"error": "仅允许本机同源访问"})
        elif self.path in STATIC:
            filename, mime = STATIC[self.path]
            self.send_content(200, (WEB/filename).read_bytes(), mime)
        elif self.path == "/api/meta":
            self.json_response(200, {"model_version": MODEL_VERSION, "terms": TERMS, "powers": POWERS,
                                     "max_order": MAX_ORDER, "default_practice_order": 3,
                                     "generator_version": GENERATOR_VERSION, "difficulties": DIFFICULTY,
                                     "custom_amplitude_min": CUSTOM_AMPLITUDE_MIN,
                                     "control_limit": CONTROL_LIMIT, "defaults": asdict(Config())})
        else:
            self.json_response(404, {"error": "路径不存在"})

    def do_POST(self):
        if not self._local_request():
            self.json_response(403, {"error": "仅允许本机同源访问"})
            return
        if self.headers.get_content_type() != "application/json":
            self.json_response(415, {"error": "需要 application/json"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 32_768:
                raise ValueError("请求大小应为 1…32768 字节")
            data = json.loads(self.rfile.read(length))
            response = self.server.application.dispatch(self.path, data)
            if isinstance(response, bytes):
                self.send_content(200, response, "application/octet-stream")
            else:
                self.json_response(200, response)
        except (ValueError, TypeError, OverflowError) as exc:
            self.json_response(400, {"error": str(exc)})
        except KeyError:
            self.json_response(404, {"error": "接口不存在"})

    def log_message(self, fmt, *args):
        # Do not log bodies, hidden labels, session IDs or filesystem paths.
        pass


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port=8765, *, handler_class=Handler):
        self.application = Application()
        super().__init__(("127.0.0.1", port), handler_class)


def main():
    parser = argparse.ArgumentParser(description="离线 EELS 像差练习器（仅本地回环地址）")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("端口须在 1…65535 之间")
    try:
        server = LocalServer(args.port)
    except OSError as exc:
        parser.exit(1, f"无法启动本地服务: {exc}。可用 --port 8766 更换端口。\n")
    print(f"EELS 练习器：http://localhost:{server.server_port}", flush=True)
    print("在 Windows/WSL 浏览器打开上述地址；Ctrl+C 停止。合成模型，不连接仪器。", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
