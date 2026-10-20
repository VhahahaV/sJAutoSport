"""CLI integration tests start isolated workers; every campus call is replaced."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import AsyncMock, Mock, patch


def fixture_daemon():
    import httpx
    from unittest.mock import AsyncMock, Mock
    from sja_booking import service, keep_alive
    from sja_booking.auth import AuthState
    from sja_booking.daemon import run

    def client(*args, **kwargs):
        cookies = httpx.Cookies()
        cookies.set("JSESSIONID", "test-session", domain="sports.sjtu.edu.cn")
        state = AuthState(prepare_url="https://sports.sjtu.edu.cn/", submit_url="https://jaccount.sjtu.edu.cn/", captcha_url=None, form={}, cookies=cookies, captcha_required=True)
        fake = Mock()
        fake._client.cookies = cookies
        fake.prepare = AsyncMock(return_value=state)
        fake.fetch_captcha = AsyncMock(return_value=b"mock-image")
        fake.current_user = AsyncMock(return_value={"loginName": "student", "userName": "Student"})

        async def submit(state, username, password, code):
            if code != "abcde":
                raise RuntimeError("验证码错误")
        fake.submit = submit
        fake.follow_redirects = AsyncMock()
        fake.close = AsyncMock()
        return fake

    async def monitor_check(*args):
        pass

    service.AuthClient = client
    service.SportsAPI = Mock()
    service.SportsAPI.return_value.check_auth_status.return_value = True
    service._monitor_check = monitor_check
    keep_alive.AuthClient = client
    run()


def test_separate_cli_calls_login_retry_restart_and_shared_web_head():
    root = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory(prefix="sja-cli-") as temporary:
        env = {**os.environ, "SJA_DATA_DIR": temporary}
        env.pop("SJA_CREDENTIAL_STORE", None)
        processes = []
        log = (Path(temporary) / "test.log").open("w")

        def call(*args, stdin=None, expected=0):
            result = subprocess.run([sys.executable, "-m", "sja_booking", *args], cwd=root,
                                    env=env, capture_output=True, text=True, input=stdin, timeout=20)
            payload = json.loads(result.stdout)
            assert result.returncode == expected, payload
            return payload

        def start():
            process = subprocess.Popen([sys.executable, str(Path(__file__)), "--fixture"], cwd=root,
                                       env=env, stdout=log, stderr=log)
            processes.append(process)
            for _ in range(100):
                if (Path(temporary) / "agent.sock").exists():
                    status = call("daemon", "status")
                    assert status["result"]["restored"]
                    return process
                if process.poll() is not None:
                    raise AssertionError("Fixture daemon failed to start")
                time.sleep(0.03)
            raise AssertionError("Fixture startup timeout")

        try:
            process = start()
            first = call("auth", "start", "--username", "student", "--password-stdin", stdin="test-password\n")["result"]
            assert Path(first["captcha_path"]).read_bytes() == b"mock-image"
            retry = call("auth", "verify", "--session-id", first["session_id"], "--code", "bad", expected=1)["result"]
            assert retry["retry"] and Path(retry["captcha_path"]).exists()
            assert not Path(first["captcha_path"]).exists()
            success = call("auth", "verify", "--session-id", first["session_id"], "--code", "abcde")
            assert success["result"]["success"]
            assert "test-session" not in json.dumps(success)
            assert not Path(retry["captcha_path"]).exists()
            assert call("auth", "status")["result"]["account"]["is_online"]
            invalid = call("auth", "start", "--json", "-", stdin='{"username":1,"password":"test-password"}', expected=1)
            assert "test-password" not in json.dumps(invalid)
            call("keep-alive", "configure", "--json", '{"enabled":true,"interval_minutes":15}')
            call("monitors", "create", "--json", '{"monitor_id":"m","preset":5,"preferred_hours":[19],"preferred_days":[2]}')
            call("monitors", "pause", "--json", '{"monitor_id":"m"}')
            call("daemon", "stop")
            process.wait(timeout=10)
            assert process.returncode == 0
            process = start()
            assert call("auth", "status")["result"]["account"]["is_online"]
            monitors = call("monitors", "list")["result"]["monitors"]
            assert monitors[0]["status"] == "paused"
            assert monitors[0]["preferred_days"] == [2]
            assert call("keep-alive", "status")["result"]["enabled"]
            # Both heads talk to the same fixture core via its Unix socket.
            import importlib
            import pytest
            pytest.importorskip("fastapi")
            from fastapi.testclient import TestClient
            from unittest.mock import patch
            from sja_booking import daemon
            gateway = importlib.import_module("web_api.app")
            with patch.object(daemon, "SOCKET", Path(temporary)/"agent.sock"), patch.object(gateway, "daemon_action", return_value={}):
                with TestClient(gateway.create_app()) as web:
                    response = web.post("/api/core/keep-alive.configure", json={"enabled": True, "interval_minutes": 25})
                    assert response.status_code == 200
                    assert response.json()["result"]["interval_minutes"] == 25
                    assert web.get("/api/health").json()["core"]["pid"] == process.pid
            assert call("keep-alive", "status")["result"]["interval_minutes"] == 25
            call("monitors", "resume", "--json", '{"monitor_id":"m"}')
            call("monitors", "delete", "--json", '{"monitor_id":"m"}')
            call("keep-alive", "configure", "--json", '{"enabled":false}')
            assert call("events", "list")["result"]["events"]
            call("daemon", "stop")
            process.wait(timeout=10)
            assert process.returncode == 0
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=10)
            log.close()


def test_dashboard_query_does_not_block_a_booking_command():
    from sja_booking.daemon import Daemon

    async def exercise():
        entered, release = asyncio.Event(), asyncio.Event()

        async def dispatch(operation, payload):
            if operation == "dashboard.availability":
                entered.set()
                await release.wait()
            return {"success": True}

        with patch("sja_booking.daemon.Operations", return_value=Mock(dispatch=dispatch)), \
             patch("sja_booking.daemon.service._session_key", return_value="same-session"):
            daemon = Daemon()

            def connection(operation):
                reader = asyncio.StreamReader()
                reader.feed_data(json.dumps({"operation": operation}).encode() + b"\n")
                reader.feed_eof()
                writer = Mock(drain=AsyncMock(), wait_closed=AsyncMock())
                return reader, writer

            query = asyncio.create_task(daemon.handle(*connection("dashboard.availability")))
            await entered.wait()
            # No HTTP request is made here; this exercises the actual daemon locks.
            await asyncio.wait_for(daemon.handle(*connection("orders.create")), timeout=1)
            assert not query.done()
            release.set()
            await query
            assert not daemon.active

    asyncio.run(exercise())


if __name__ == "__main__" and "--fixture" in sys.argv:
    fixture_daemon()
