"""Exercise every CLI contract in separate processes against isolated campus transports."""
import asyncio
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def fixture_daemon():
    import httpx
    import websockets.asyncio.client
    from datetime import datetime, timedelta
    from urllib.parse import parse_qs
    from sja_booking import config
    from sja_booking.daemon import run

    preset = config.PRESET_TARGETS[4]
    audit = config.DATA_DIR / "http-audit.jsonl"
    orders = []
    image = b"\x89PNG\r\n\x1a\ntest-image"
    uuid = "11111111-1111-1111-1111-111111111111"

    def handler(request):
        path = request.url.path
        with audit.open("a") as handle:
            handle.write(json.dumps({"method": request.method, "path": path}) + "\n")
        if path == "/oauth2/authorize":
            return httpx.Response(302, headers={"location": "https://jaccount.sjtu.edu.cn/jaccount/login"})
        if path == "/jaccount/login":
            return httpx.Response(200, text=f'<form action="/jaccount/ulogin"><input type="hidden" name="csrf" value="test-csrf"><img id="qr-img"><img id="captcha-img" src="captcha?uuid={uuid}"></form>', headers={"set-cookie": "JSESSIONID=test-jaccount; Path=/"})
        if path in {"/jaccount/captcha", "/jaccount/qrcode"}:
            return httpx.Response(200, content=image)
        if path == "/jaccount/ulogin":
            form = parse_qs(request.content.decode())
            assert form["user"] == ["student"] and form["pass"] == ["test-password"]
            if form.get("captcha") != ["abcde"]:
                return httpx.Response(200, text='<span id="errmsg">验证码错误</span>')
            return httpx.Response(302, headers={"location": "https://sports.sjtu.edu.cn/oauth2Login"})
        if path == "/jaccount/expresslogin":
            return httpx.Response(302, headers={"location": "https://sports.sjtu.edu.cn/oauth2Login"})
        if path == "/oauth2Login":
            return httpx.Response(302, headers={"location": "/pc/", "set-cookie": "JSESSIONID=test-session; Path=/"})
        if path == "/pc/":
            return httpx.Response(200, text="logged in")
        assert "JSESSIONID=test-session" in request.headers.get("cookie", ""), "missing sports credential"
        if path == config.ENDPOINTS.current_user:
            return httpx.Response(200, json={"code": 0, "data": {"loginName": "student", "userName": "Student", "dept": {"deptName": "Test department"}}})
        if path == config.ENDPOINTS.list_venues:
            return httpx.Response(200, json={"code": 0, "rows": [{"id": preset.venue_id, "venueName": preset.venue_name}]})
        if path == config.ENDPOINTS.venue_detail:
            return httpx.Response(200, json={"code": 0, "data": {"venueName": preset.venue_name, "fieldTypeList": [{"id": preset.field_type_id, "fieldTypeName": preset.field_type_name, "category": "test"}]}})
        if path == config.ENDPOINTS.field_reserve:
            return httpx.Response(200, json={"code": 0, "data": [{"date": (datetime.now().date() + timedelta(days=i)).isoformat(), "dateId": f"date-{i}", "open": True, "isAll": False} for i in range(8)]})
        if path == config.ENDPOINTS.field_situation:
            return httpx.Response(200, json={"code": 0, "data": [{"fieldId": "test-court", "fieldName": "Test court", "priceList": [{"id": "test-slot", "startTime": "19:00", "endTime": "20:00", "count": 3, "price": 0, "sign": "test-signature"}]}]})
        if path == config.ENDPOINTS.order_confirm:
            assert len(request.headers["sid"]) > 20 and len(request.headers["tim"]) > 20
            assert request.headers["content-type"].startswith("application/json")
            assert len(base64.b64decode(request.content)) % 16 == 0
            order_id = f"test-order-{len(orders) + 1}"
            orders.append({"pOrderid": order_id, "orderstateid": "1", "cancelOrder": False})
            return httpx.Response(200, json={"code": 0, "orderId": order_id})
        if path == "/venue/personal/personalOrderlist":
            return httpx.Response(200, json={"code": 0, "records": orders, "total": len(orders)})
        if path in {config.ENDPOINTS.refund_create_receipt, config.ENDPOINTS.refund_accept, config.ENDPOINTS.refund_confirm}:
            form = parse_qs(request.content.decode())
            assert form.get("orderId") and form["orderId"][0].startswith("test-order-")
            if path == config.ENDPOINTS.refund_confirm:
                for order in orders:
                    if order["pOrderid"] == form["orderId"][0]:
                        order.update(orderstateid="2", cancelOrder=True)
            code = {config.ENDPOINTS.refund_create_receipt: 1, config.ENDPOINTS.refund_accept: 2,
                    config.ENDPOINTS.refund_confirm: 3}[path]
            return httpx.Response(200, json={"code": code, "msg": "cancelled"})
        raise AssertionError(f"Unexpected campus request: {request.method} {path}")

    # Replace the external transport only. Actual protocol, parsing, crypto and core run unchanged.
    sync_client, async_client = httpx.Client, httpx.AsyncClient

    def client(*args, **kwargs):
        kwargs.update(transport=httpx.MockTransport(handler), trust_env=False)
        return sync_client(*args, **kwargs)

    def aclient(*args, **kwargs):
        kwargs.update(transport=httpx.MockTransport(handler), trust_env=False)
        return async_client(*args, **kwargs)

    class Socket:
        def __init__(self, *args, **kwargs):
            self.initial = True

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def send(self, message):
            assert json.loads(message)["type"] == "UPDATE_QR_CODE"

        async def recv(self):
            if self.initial:
                self.initial = False
                return json.dumps({"type": "UPDATE_QR_CODE", "payload": {"ts": 42, "sig": "test-signature"}})
            while not (config.DATA_DIR / "qr-confirmed").exists():
                await asyncio.sleep(.02)
            return json.dumps({"type": "LOGIN"})

    httpx.Client, httpx.AsyncClient = client, aclient
    websockets.asyncio.client.connect = Socket
    run()


def test_every_cli_operation_with_isolated_protocols(tmp_path):
    from sja_booking.operations import CONTRACTS
    root = Path(__file__).resolve().parent.parent
    env = {**os.environ, "SJA_DATA_DIR": str(tmp_path)}
    env.pop("SJA_CREDENTIAL_STORE", None)
    env.pop("SJA_SECRET", None)
    invoked = set()
    process = None
    log = (tmp_path / "daemon.log").open("w")

    def call(*args, stdin=None, expected=0):
        result = subprocess.run([sys.executable, "-m", "sja_booking", *args], input=stdin, capture_output=True, text=True, env=env, cwd=root, timeout=30)
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise AssertionError(f"CLI output is not JSON: {args[:2]}, exit={result.returncode}") from exc
        assert result.returncode == expected, payload
        assert "test-password" not in result.stdout and "test-session" not in result.stdout
        if args and args[0] not in {"schema", "daemon"}:
            invoked.add(".".join(args[:2]))
        return payload

    def op(name, payload=None, expected=0):
        return call(*name.split("."), "--json", json.dumps(payload or {}), expected=expected).get("result")

    try:
        assert call()["result"]["initialized"]
        schema = call("schema")["result"]
        assert set(schema) == set(CONTRACTS)
        for name in schema:
            assert call("schema", name)["result"][name]["input"]["additionalProperties"] is False
        process = subprocess.Popen([sys.executable, str(Path(__file__)), "--fixture"], env=env, cwd=root, stdout=log, stderr=log)
        for _ in range(200):
            if (tmp_path / "agent.sock").exists(): break
            assert process.poll() is None, "Fixture daemon exited"
            time.sleep(.02)
        assert call("daemon", "status")["result"]["pid"] == process.pid
        assert call("daemon", "start")["result"]["pid"] == process.pid
        call("venues", "list", expected=1)
        pending = call("auth", "start", "--username", "student", "--password-stdin", stdin="test-password\n")["result"]
        assert Path(pending["captcha_path"]).stat().st_mode & 0o777 == 0o600
        op("auth.cancel", {"session_id": pending["session_id"]})
        assert not Path(pending["captcha_path"]).exists()
        pending = call("auth", "start", "--json", "-", stdin=json.dumps({"username": "student", "password": "test-password"}))["result"]
        retry = call("auth", "verify", "--session-id", pending["session_id"], "--code", "bad", expected=1)["result"]
        assert retry["retry"]
        assert call("auth", "verify", "--session-id", pending["session_id"], "--code", "abcde")["result"]["success"]
        assert op("auth.status")["account"]["is_online"]
        assert op("account.info")["profile"]["login_name"] == "student"
        presets = op("presets.list")
        preset = next(item for item in presets if item["index"] == 5)
        assert op("venues.list")[0]["id"] == preset["venue_id"]
        assert op("venues.fields", {"venue_id": preset["venue_id"]})[0]["id"] == preset["field_type_id"]
        dates = op("dates.list", {"preset": 5})["dates"]
        today = dates[0]["date"]
        assert op("slots.list", {"preset": 5, "date": today})["slots"][0]["slot"]["remain"] == 3
        card = op("dashboard.add", {"preset": 5, "days": 2})
        assert op("dashboard.list") == [card]
        assert len(op("dashboard.availability", {"card_id": card["id"]})["days"]) == 2
        op("dashboard.delete", {"card_id": card["id"]})
        order = op("orders.create", {"preset": 5, "date": today, "start_time": "19:00", "end_time": "20:00",
                                     "request_id": "test-booking"})
        assert order["success"] and order["order_id"] == "test-order-1"
        assert op("orders.reconcile", {"request_id": "test-booking"})["order_id"] == "test-order-1"
        assert op("orders.list")["orders"][0]["can_cancel"]
        assert op("orders.cancel", {"order_id": order["order_id"]})["success"]
        assert not op("orders.list")["orders"][0]["can_cancel"]
        assert op("history.list")[0]["order_id"] == order["order_id"]
        snapshot = op("slots.list", {"preset": 5, "date": today})
        cascaded = op("orders.cascade", {"preset": 5, "date": today, "request_id": "cascade-booking",
                                       "snapshot_id": snapshot["snapshot_id"], "max_price": 0,
                                       "preferences": [{"start_time": "18:00"}, {"start_time": "19:00"}]})
        assert cascaded["success"] and len(cascaded["attempts"]) == 1
        op("orders.cancel", {"order_id": cascaded["order_id"]})
        op("monitors.create", {"monitor_id": "test-monitor", "preset": 5, "preferred_days": [0], "preferred_hours": [19]})
        for _ in range(20):
            monitors = op("monitors.list")["monitors"]
            if monitors[0]["last_check"]: break
            time.sleep(.2)
        assert monitors[0]["last_check"] and monitors[0]["found_slots"]
        op("monitors.pause", {"monitor_id": "test-monitor"})
        op("monitors.resume", {"monitor_id": "test-monitor"})
        op("monitors.delete", {"monitor_id": "test-monitor"})
        assert op("keep-alive.run")["success"]
        assert op("keep-alive.configure", {"enabled": True, "interval_minutes": 15})["enabled"]
        assert op("keep-alive.status")["enabled"]
        op("keep-alive.configure", {"enabled": False})
        assert op("events.list")["events"]
        qr = op("auth.qr-start")
        assert Path(qr["qr_path"]).exists()
        assert op("auth.qr-status", {"session_id": qr["session_id"]})["status"] == "waiting"
        op("auth.qr-cancel", {"session_id": qr["session_id"]})
        assert not Path(qr["qr_path"]).exists()
        qr = op("auth.qr-start")
        (tmp_path / "qr-confirmed").touch()
        for _ in range(10):
            result = op("auth.qr-status", {"session_id": qr["session_id"]})
            if result["status"] == "success": break
            time.sleep(.05)
        assert result["status"] == "success"
        assert op("auth.status")["account"]["username"] == "student"
        assert op("auth.logout")["success"]
        assert not op("auth.status", expected=1)["success"]
        assert op("keep-alive.run", expected=1)["status"] == "login_required"
        assert not op("keep-alive.status")["session"]["sso_available"]
        assert isinstance(op("events.list")["events"], list)
        assert not (tmp_path / "credentials.json").exists()
        assert set(CONTRACTS) == invoked, f"Unexercised CLI operations: {set(CONTRACTS) - invoked}"
        assert isinstance(call("daemon", "logs")["result"]["lines"], list)
        call("daemon", "stop")
        process.wait(timeout=10)
        assert process.returncode == 0
        audit = [json.loads(line) for line in (tmp_path / "http-audit.jsonl").read_text().splitlines()]
        paths = [entry["path"] for entry in audit]
        assert paths.count("/venue/personal/ConfirmOrder") == 2
        assert paths.count("/tRefundReceipt/tRefundReceipt/createUserReceipt") == 2
        assert paths.count("/tRefundReceipt/tRefundReceipt/cannelRefundReceipt") == 2
        assert paths.count("/tRefundReceipt/tRefundReceipt/cannelDetail") == 2
    finally:
        if process and process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        log.close()


def test_cli_daemon_lifecycle_input_formats_and_exit_codes(tmp_path):
    root = Path(__file__).resolve().parent.parent
    env = {**os.environ, "SJA_DATA_DIR": str(tmp_path / "data")}
    env.pop("SJA_CREDENTIAL_STORE", None)
    env.pop("SJA_SECRET", None)
    executable = [sys.executable, "-m", "sja_booking"]
    foreground = None

    def call(*args, stdin=None, expected=0):
        result = subprocess.run([*executable, *args], cwd=root, env=env, input=stdin, capture_output=True, text=True, timeout=20)
        assert result.returncode == expected, result.stderr
        return json.loads(result.stdout)

    try:
        pid = call("daemon", "start")["result"]["pid"]
        assert call("daemon", "start")["result"]["pid"] == pid
        assert call("daemon", "status")["result"]["restored"]
        for name in ("agent.sock", "daemon.log"):
            assert (tmp_path / "data" / name).stat().st_mode & 0o777 == 0o600
        document = tmp_path / "input.json"
        document.write_text('{"keyword":"test"}')
        for args, stdin in [(("--json", "@" + str(document)), None), (("--json", "-"), '{"keyword":"test"}')]:
            assert call("venues", "list", *args, stdin=stdin, expected=1)["error"]["code"] == "login_required"
        missing = call("venues", "list", "--json", "@" + str(tmp_path / "missing.json"), expected=2)
        assert missing["error"]["code"] == "cli_error"
        assert "JSON input file" in missing["error"]["message"]
        for value in ("[]", "{invalid"):
            assert call("venues", "list", "--json", value, expected=2)["error"]["code"] == "cli_error"
        assert call("slots", "list", "--json", '{"preset":0}', expected=1)["error"]["code"] == "invalid_input"
        assert call("auth", "status", expected=1)["result"]["account"] is None
        call("daemon", "logs")
        call("daemon", "stop")
        assert not (tmp_path / "data/agent.sock").exists()
        assert call("daemon", "status", expected=2)["error"]["code"] == "daemon_unavailable"
        with (tmp_path / "foreground.log").open("w") as log:
            foreground = subprocess.Popen([*executable, "daemon", "run"], cwd=root, env=env, stdout=log, stderr=log)
            for _ in range(100):
                if (tmp_path / "data/agent.sock").exists(): break
                assert foreground.poll() is None
                time.sleep(.03)
            assert call("daemon", "status")["result"]["pid"] == foreground.pid
            call("daemon", "stop")
            foreground.wait(timeout=10)
            assert foreground.returncode == 0
    finally:
        if foreground and foreground.poll() is None:
            foreground.terminate()
            foreground.wait(timeout=10)
        if (tmp_path / "data/agent.sock").exists():
            call("daemon", "stop")


if __name__ == "__main__" and "--fixture" in sys.argv:
    fixture_daemon()
