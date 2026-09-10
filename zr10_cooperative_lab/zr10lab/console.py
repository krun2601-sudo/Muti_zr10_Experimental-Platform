"""本机总控制中心 HTTP 外壳。

浏览器只负责显示和提交意图，实际运动由 control_center 的独立事件循环执行。
服务仅监听 127.0.0.1，使用每次启动随机令牌、Host/Origin 检查和 JSON 请求，
防止普通外部网页向实验设备提交跨站控制请求；它不是供公网部署的服务器。
HTML、JavaScript、Three.js 都是随 Python 包安装的静态资源，运行时无需联网。
"""
from __future__ import annotations

from dataclasses import asdict, fields
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import secrets
import threading
import time
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit
import webbrowser

from .actions import PARAMETERS
from .config import config_from_dict
from .models import Telemetry, Track
from .recording import jsonable


class ControlHTTPServer(ThreadingHTTPServer):
    """可注入假控制器的本机接口，便于离线测试而不建立任何设备连接。"""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, center: Any, *, port: int = 0, token: str | None = None,
                 web_root: str | Path | None = None, auto_start: dict | None = None):
        if type(port) is not int or not 0 <= port <= 65535:
            raise ValueError("界面端口必须是 0..65535 整数")
        self.center = center
        self.token = token or secrets.token_urlsafe(32)
        self.web_root = Path(web_root or Path(__file__).parent / "web").resolve()
        self.auto_start = auto_start
        self._start_lock = threading.Lock()
        self._scene_lock = threading.Lock()
        self._scene_cache: tuple[tuple, float, dict] | None = None
        self._thread: threading.Thread | None = None
        super().__init__(("127.0.0.1", port), _Handler)

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    @property
    def url(self) -> str:
        # 片段不随HTTP请求、Referer或服务器访问日志发送。
        return self.origin + "/#token=" + self.token

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self.serve_forever,
                                            name="zr10-local-http", daemon=True)
            self._thread.start()

    def close(self) -> None:
        if self._thread is not None:
            self.shutdown()
            self._thread.join(timeout=2)
            self._thread = None
        self.server_close()

    def handle_command(self, payload: dict) -> dict:
        result = self.center.command(payload)
        if payload.get("action") == "heartbeat":
            # run --ui 等页面建立监督连接以后再启动，避免打开浏览器期间无人监督。
            # 先领取一次性任务再执行；失败也不因下一次心跳重复启动设备。
            with self._start_lock:
                pending, self.auto_start = self.auto_start, None
            if pending is not None:
                result = self.center.command(pending)
        return result

    def scene(self, range_m: float) -> dict:
        """把同一份状态快照转换成三维几何，浏览器不另行猜测相机姿态。"""
        from .scene import build_scene

        if not math.isfinite(range_m) or not 1 <= range_m <= 10000:
            raise ValueError("视场显示距离必须在 1..10000 米内")
        snapshot = self.center.snapshot()
        cache_key = (snapshot.get("revision"), range_m)
        now_wall = time.monotonic()
        with self._scene_lock:
            if self._scene_cache and self._scene_cache[0] == cache_key and now_wall - self._scene_cache[1] < 0.1:
                return self._scene_cache[2]
        cfg = config_from_dict(snapshot["config"])
        states = {}
        names = {field.name for field in fields(Telemetry)}
        for item in snapshot.get("devices", []):
            feedback = item.get("feedback")
            if not feedback:
                continue
            values = {key: value for key, value in feedback.items() if key in names}
            values["device_id"] = item["id"]
            values["connected"] = bool(item.get("connected", False) and values.get("connected", True))
            states[item["id"]] = Telemetry(**values)
        track_names = {field.name for field in fields(Track)}
        tracks = [Track(**{key: value for key, value in row.items() if key in track_names})
                  for row in snapshot.get("tracks", [])]
        now = snapshot.get("t", max((s.t for s in states.values()), default=0))
        if snapshot.get("environment") == "hardware":
            now = time.monotonic()  # 页面停止轮询期间，旧硬件状态仍必须自然过期。
        scene = build_scene(cfg, states, tracks, float(now), range_m=range_m,
                            preview=snapshot.get("environment") == "sim")
        histories = {row["track_id"]: row.get("history", []) for row in snapshot.get("tracks", [])}
        history_samples = {row["track_id"]: row.get("history_samples", []) for row in snapshot.get("tracks", [])}
        for row in scene.get("tracks", []):
            row["history"] = histories.get(row.get("track_id"), [])
            row["history_samples"] = history_samples.get(row.get("track_id"), [])
        scene["environment"] = snapshot.get("environment")
        scene["status"] = snapshot.get("status")
        scene["revision"] = snapshot.get("revision")
        scene["session_path"] = snapshot.get("session_path")
        with self._scene_lock:
            self._scene_cache = (cache_key, now_wall, scene)
        return scene


class _Handler(BaseHTTPRequestHandler):
    """仅开放明确定义的 API 和 web/ 内的静态文件；不提供目录浏览或任意文件读取。"""

    server: ControlHTTPServer
    protocol_version = "HTTP/1.1"
    server_version = "ZR10Local/4"
    MAX_BODY_BYTES = 2 * 1024 * 1024

    def setup(self):
        super().setup()
        self.connection.settimeout(8)

    def log_message(self, format, *args):
        # 高频状态轮询不污染实验终端，也不把本机认证信息写入日志。
        pass

    def _response(self, status: int, content: bytes, content_type: str) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy",
                "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                "img-src 'self' blob: data:; connect-src 'self'; font-src 'self'; object-src 'none'; "
                "base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass  # 页面关闭不影响后台的租约和急停机制。

    def _json(self, status: int, value: Any) -> None:
        data = json.dumps(jsonable(value), ensure_ascii=False, allow_nan=False).encode("utf-8")
        self._response(status, data, "application/json; charset=utf-8")

    def _check_origin(self, *, authenticated: bool) -> bool:
        port = self.server.server_address[1]
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host", "") not in hosts:
            self._json(403, {"ok": False, "error": "仅允许通过本机控制中心地址访问"})
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin not in {f"http://{host}" for host in hosts}:
            self._json(403, {"ok": False, "error": "拒绝跨站请求"})
            return False
        if authenticated and not secrets.compare_digest(self.headers.get("X-ZR10-Token", ""), self.server.token):
            self._json(403, {"ok": False, "error": "控制中心令牌无效，请使用本次启动打印的完整链接"})
            return False
        return True

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        url = urlsplit(self.path)
        path = unquote(url.path)
        is_api = path.startswith("/api/")
        if not self._check_origin(authenticated=is_api):
            return
        try:
            if path == "/api/state":
                self._json(200, self.server.center.snapshot())
            elif path == "/api/schema":
                self._json(200, {"parameters": {name: asdict(spec) for name, spec in PARAMETERS.items()}})
            elif path == "/api/scene":
                query = parse_qs(url.query)
                distance = float(query.get("range_m", ["200"])[0])
                self._json(200, self.server.scene(distance))
            elif path.startswith("/api/frame/") and path.endswith(".jpg"):
                device_id = path[len("/api/frame/"):-4]
                if device_id not in {d["id"] for d in self.server.center.snapshot().get("devices", [])}:
                    raise ValueError("未知设备")
                frame = self.server.center.frame(device_id)
                if frame:
                    self._response(200, frame, "image/jpeg")
                else:
                    self._json(404, {"ok": False, "error": "视频尚未启用或没有新鲜画面"})
            elif is_api:
                self._json(404, {"ok": False, "error": "未知接口"})
            else:
                self._static(path)
        except (ValueError, TypeError, KeyError) as exc:
            self._json(400, {"ok": False, "error": str(exc)})
        except Exception as exc:
            self._json(500, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})

    def _static(self, path: str) -> None:
        relative = "index.html" if path == "/" else path.lstrip("/")
        file = (self.server.web_root / relative).resolve()
        types = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml",
                 ".png": "image/png", ".ico": "image/x-icon", ".json": "application/json; charset=utf-8"}
        if not file.is_relative_to(self.server.web_root) or not file.is_file() or file.suffix not in types:
            self._json(404, {"ok": False, "error": "资源不存在"})
            return
        self._response(200, file.read_bytes(), types[file.suffix])

    def do_POST(self):
        if not self._check_origin(authenticated=True):
            self.close_connection = True
            return
        if urlsplit(self.path).path != "/api/command":
            self._json(404, {"ok": False, "error": "未知接口"})
            self.close_connection = True
            return
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            self._json(415, {"ok": False, "error": "控制命令必须使用 application/json"})
            self.close_connection = True
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= self.MAX_BODY_BYTES:
                self._json(413, {"ok": False, "error": "请求体为空或超过 2 MiB"})
                self.close_connection = True
                return
            if self.headers.get("Transfer-Encoding"):
                raise ValueError("不接受分块控制命令")
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("请求未完整接收")
            def reject_constant(value):
                raise ValueError(f"JSON 不允许非有限数值 {value}")
            payload = json.loads(raw.decode("utf-8"), parse_constant=reject_constant)
            if not isinstance(payload, dict) or not isinstance(payload.get("action"), str):
                raise ValueError("命令必须包含 action 字符串")
            result = self.server.handle_command(payload)
            self._json(200 if result.get("ok", True) else 409, result)
        except (ValueError, TypeError, KeyError, UnicodeError) as exc:
            self._json(400, {"ok": False, "error": str(exc)})
        except TimeoutError:
            # 已送入设备控制线程的命令可能已被执行，不能自动重试非幂等参数。
            self._json(504, {"ok": False, "error": "命令处理超时，请查看反馈和事件；不要自动重试拍照或录像切换"})
        except Exception as exc:
            self._json(409, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})

    def do_OPTIONS(self):
        self._json(403, {"ok": False, "error": "不提供跨站控制接口"})


def default_mode(cfg) -> str:
    """把原有 CLI 策略配置映射到界面模式，不改变旧配置的算法含义。"""
    name = cfg.policy.get("name", cfg.policy.get("type", "cooperative"))
    if name == "cooperative":
        return "center" if cfg.policy.get("mode") == "center" else "multi"
    if name in ("scan", "hold", "track", "manual", "localize", "center", "multi"):
        return name
    # run --ui 沿用原算法配置；页面默认选项不能把自定义算法替换为手动。
    return "custom"


def launch_console(cfg, *, environment="sim", armed=False, output=None,
                   port: int | None = None, open_browser=True, auto_run=False,
                   duration_s: float | None = None) -> None:
    """启动本机页面并维持服务；实验停止后保留窗口，以便检查结果或再次启动。"""
    from .control_center import ControlCenter

    center = ControlCenter(cfg, environment=environment, armed=armed, output=output)
    pending = None
    if auto_run:
        pending = {"action": "start", "environment": environment, "armed": armed,
                   "mode": default_mode(cfg),
                   "duration_s": duration_s if duration_s is not None else cfg.system.get("duration_s", 60)}
    server = None
    try:
        center.start()
        server = ControlHTTPServer(center,
            port=cfg.control_center.get("port", 0) if port is None else port,
            auto_start=pending)
        server.start()
        print("ZR10 总控制中心已启动（仅本机访问）。", flush=True)
        print(server.url, flush=True)
        print("实验结束后界面保留；在此终端按 Ctrl+C 停机并关闭控制中心。", flush=True)
        if open_browser:
            webbrowser.open(server.url, new=1)
        while True:
            time.sleep(0.25)
    except KeyboardInterrupt:
        print("正在停止设备、保存记录并关闭控制中心……", flush=True)
    finally:
        # 先停止接收新的HTTP请求，再关闭控制执行线程。
        if server is not None:
            server.close()
        center.close()


def main():
    import argparse
    from .config import load_config
    parser = argparse.ArgumentParser(description="ZR10 本机监视与控制中心")
    parser.add_argument("--config", default="configs/four_zr10.yaml")
    parser.add_argument("--mode", choices=("sim", "hardware"), default="sim")
    parser.add_argument("--arm", action="store_true")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    launch_console(load_config(args.config), environment=args.mode, armed=args.arm,
                   port=args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
