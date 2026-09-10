"""总控制中心的本机HTTP边界测试：只接内存假控制器，不访问ZR10。"""
from copy import deepcopy
from dataclasses import asdict
import http.client
import json
from pathlib import Path
import time

import pytest

from zr10lab.config import config_from_dict, load_config
from zr10lab.console import ControlHTTPServer, default_mode
from zr10lab.models import Telemetry


PROJECT = Path(__file__).resolve().parents[1]


class FakeCenter:
    def __init__(self):
        self.cfg = load_config(PROJECT / "configs/four_zr10.yaml")
        self.calls = []

    def snapshot(self):
        return {"revision": 1, "status": "running", "environment": "sim", "t": 0.0,
                "config": self.cfg.to_dict(), "tracks": [],
                "devices": [{"id": d.id, "connected": True,
                    "feedback": asdict(Telemetry(d.id, 0, 0, 0, source="simulation"))}
                    for d in self.cfg.active_devices]}

    def command(self, payload):
        self.calls.append(deepcopy(payload))
        return {"ok": True, "action": payload["action"]}

    def frame(self, device_id):
        return None


@pytest.fixture
def service(tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<!doctype html><title>控制中心</title>", encoding="utf-8")
    (web / "app.js").write_text("export const ready = true", encoding="utf-8")
    (tmp_path / "private.js").write_text("secret", encoding="utf-8")
    server = ControlHTTPServer(FakeCenter(), web_root=web)
    server.start()
    try:
        yield server
    finally:
        server.close()


def request(server, path, method="GET", data=None, headers=None, authenticated=True):
    values = {"X-ZR10-Token": server.token} if authenticated else {}
    if data is not None:
        values["Content-Type"] = "application/json"
    values.update(headers or {})
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
    try:
        connection.request(method, path, body=data, headers=values)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def test_static_page_has_no_token_and_only_api_requires_auth(service):
    status, headers, body = request(service, "/", authenticated=False)
    assert status == 200 and service.token.encode() not in body
    assert headers["X-Frame-Options"] == "DENY"
    assert "connect-src 'self'" in headers["Content-Security-Policy"]
    assert request(service, "/api/state", authenticated=False)[0] == 403
    assert request(service, "/api/state")[0] == 200
    assert not service.center.calls


def test_external_origin_and_rebound_host_never_dispatch_motion(service):
    command = json.dumps({"action": "manual", "device_id": "zr10_25", "yaw_deg": 10})
    for headers in ({"Origin": "https://example.org"}, {"Host": "evil.example:123"},
                    {"X-ZR10-Token": "wrong"}):
        assert request(service, "/api/command", "POST", command, headers)[0] == 403
    assert not service.center.calls


def test_strict_json_body_and_no_get_mutation(service):
    invalid = ("{}", "[]", '{"action":"manual","yaw_deg":NaN}', '{"action":"manual","yaw_deg":Infinity}')
    for body in invalid:
        assert request(service, "/api/command", "POST", body)[0] == 400
    assert request(service, "/api/command?action=estop")[0] == 404
    assert request(service, "/api/command", "POST", "action=manual",
                   {"Content-Type": "application/x-www-form-urlencoded"})[0] == 415
    assert not service.center.calls
    result = request(service, "/api/command", "POST", '{"action":"pause"}')
    assert result[0] == 200 and json.loads(result[2])["ok"]
    assert service.center.calls == [{"action": "pause"}]


def test_static_traversal_directory_listing_and_unknown_frame_rejected(service):
    for path in ("/%2e%2e/private.js", "/../private.js", "/vendor/", "/config.py", "/api/unknown"):
        assert request(service, path)[0] == 404
    assert request(service, "/api/frame/unknown.jpg")[0] == 400
    assert request(service, "/api/frame/zr10_25.jpg")[0] == 404
    assert request(service, "/app.js")[1]["Content-Type"].startswith("text/javascript")


def test_autorun_waits_for_valid_heartbeat_and_is_exactly_once(service):
    service.auto_start = {"action": "start", "mode": "scan", "environment": "sim", "duration_s": 1}
    request(service, "/api/state")
    assert service.center.calls == []
    request(service, "/api/command", "POST", '{"action":"heartbeat"}', authenticated=False)
    assert service.auto_start is not None
    for _ in range(2):
        assert request(service, "/api/command", "POST", '{"action":"heartbeat"}')[0] == 200
    assert [c["action"] for c in service.center.calls] == ["heartbeat", "start", "heartbeat"]


def test_scene_converts_shared_feedback_and_bounds_input(service):
    status, _, body = request(service, "/api/scene?range_m=150")
    assert status == 200, body.decode()
    scene = json.loads(body)
    assert len(scene["devices"]) == 4 and scene["environment"] == "sim"
    for distance in ("nan", "inf", "0", "-1", "10001", "oops"):
        assert request(service, f"/api/scene?range_m={distance}")[0] == 400


def test_control_center_config_boolean_and_single_station_contract():
    data = load_config(PROJECT / "configs/four_zr10.yaml").to_dict()
    data["devices"] = data["devices"][:1]
    assert len(config_from_dict(data).active_devices) == 1
    for bad in ("ture", "false", 1):
        changed = deepcopy(data)
        changed["devices"][0]["calibration_verified"] = bad
        with pytest.raises(ValueError, match="true/false"):
            config_from_dict(changed)
    for options in ({"heartbeat_timeout_s": 0}, {"port": -1}, {"enabled": "true"}, {"preview_fps": 90}):
        changed = {**data, "control_center": options}
        with pytest.raises(ValueError):
            config_from_dict(changed)


def test_cli_mode_mapping_and_interface_flags(monkeypatch):
    from zr10lab.cli import main
    cfg = load_config(PROJECT / "configs/four_zr10.yaml")
    assert default_mode(cfg) == "multi"
    cfg.policy["mode"] = "center"
    assert default_mode(cfg) == "center"
    cfg.policy = {"name": "custom", "class_path": "examples.custom_policy:MyPolicy"}
    cfg.control_center["default_mode"] = "manual"
    assert default_mode(cfg) == "custom"
    calls = []
    monkeypatch.setattr("zr10lab.console.launch_console", lambda cfg, **kw: calls.append((cfg, kw)))
    assert main(["run", "--config", str(PROJECT / "configs/four_zr10.yaml"),
                 "--ui", "--duration", "0", "--no-browser"]) == 0
    assert calls[-1][1]["auto_run"] and calls[-1][1]["duration_s"] == 0
    assert not calls[-1][1]["open_browser"]
    assert main(["console", "--config", str(PROJECT / "configs/four_zr10.yaml"), "--no-browser"]) == 0
    assert not calls[-1][1].get("auto_run", False)
