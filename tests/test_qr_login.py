import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import httpx

from sja_booking import config, database, service
from sja_booking.auth import AuthClient, AuthManager, AuthState, AuthStore
from sja_booking.database import DatabaseManager
from sja_booking.models import AuthConfig
from sja_booking.operations import Operations, public


class Socket:
    def __init__(self):
        self.messages = asyncio.Queue()
        self.send = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def recv(self):
        value = await self.messages.get()
        if isinstance(value, Exception):
            raise value
        return json.dumps(value)


class QrLoginTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name)
        self.manager = AuthManager(AuthStore(self.path / "credentials.json"))
        self.db = DatabaseManager(self.path / "state.db")
        for patcher in (patch.object(config, "DATA_DIR", self.path), patch.object(config, "AUTH", AuthConfig()),
                        patch.object(service, "_auth_manager", self.manager), patch.object(service, "_qr_sessions", {}),
                        patch.object(service, "_login_sessions", {}), patch.object(database, "_db_manager", self.db)):
            patcher.start()
            self.addCleanup(patcher.stop)

    async def asyncTearDown(self):
        for sid in list(service._qr_sessions):
            await service.cancel_qr_login(sid)

    def client(self):
        client = Mock()
        cookies = httpx.Cookies()
        cookies.set("JSESSIONID", "test-jaccount-session", domain="jaccount.sjtu.edu.cn")
        client._client.cookies = cookies
        state = AuthState(prepare_url="https://jaccount.sjtu.edu.cn/jaccount/login", submit_url="https://jaccount.sjtu.edu.cn/jaccount/ulogin", captcha_url=None, form={}, cookies=cookies,
                          metadata={"qr_image_url": "https://jaccount.sjtu.edu.cn/jaccount/qrcode?uuid=test-uuid",
                                    "qr_socket_url": "wss://jaccount.sjtu.edu.cn/jaccount/sub/test-uuid",
                                    "qr_express_url": "https://jaccount.sjtu.edu.cn/jaccount/expresslogin?uuid=test-uuid"})
        client.prepare = AsyncMock(return_value=state)
        client.close = AsyncMock()
        client.follow_redirects = AsyncMock()

        async def get(url, **kwargs):
            url = str(url)
            if "expresslogin" in url:
                cookies.set("JSESSIONID", "test-sports-session", domain="sports.sjtu.edu.cn")
            return httpx.Response(200, content=b"\x89PNG\r\n\x1a\nmock-image", request=httpx.Request("GET", url))
        client._client.get = AsyncMock(side_effect=get)
        return client

    async def test_live_markup_with_empty_qr_src_uses_dynamic_uuid(self):
        markup = '<img id="qr-img"><img id="captcha-img" src="captcha?uuid=11111111-1111-1111-1111-111111111111&amp;t=42">'
        client = AuthClient(config.BASE_URL, config.ENDPOINTS, config.AUTH)
        await client.close()
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=markup)))
        try:
            state = await client.prepare()
            self.assertIn("/jaccount/sub/11111111-1111-1111-1111-111111111111", state.metadata["qr_socket_url"])
            self.assertNotIn("amp;", state.captcha_url)
        finally:
            await client.close()

    async def test_qr_update_then_login_verifies_and_persists_cookie(self):
        client = self.client()
        socket = Socket()
        socket.messages.put_nowait({"type": "UPDATE_QR_CODE", "payload": {"ts": 42, "sig": "test-signature"}})
        with patch.object(service, "AuthClient", return_value=client), patch("websockets.asyncio.client.connect", return_value=socket) as connect, patch.object(service, "_save_qr_cookie", return_value="Student") as verify:
            result = await service.start_qr_login()
            self.assertEqual(result["status"], "waiting")
            self.assertTrue(result["qr_image"].startswith(b"\x89PNG"))
            self.assertEqual(connect.call_args.kwargs["origin"], "https://jaccount.sjtu.edu.cn")
            self.assertIn("test-jaccount-session", connect.call_args.kwargs["additional_headers"]["Cookie"])
            self.assertIsNone(self.manager.load_record())
            socket.messages.put_nowait({"type": "LOGIN"})
            await service._qr_sessions[result["session_id"]]["task"]
            final = service.qr_login_status(result["session_id"])
            self.assertEqual(final["status"], "success")
            self.assertNotIn("qr_image", final)
            verify.assert_called_once_with("JSESSIONID=test-sports-session")
            client.follow_redirects.assert_awaited_once()

    async def test_qr_image_is_private_and_removed_on_cancel(self):
        socket = Socket()
        socket.messages.put_nowait({"type": "UPDATE_QR_CODE", "payload": {"ts": 42, "sig": "test-signature"}})
        with patch.object(service, "AuthClient", return_value=self.client()), patch("websockets.asyncio.client.connect", return_value=socket):
            operations = Operations()
            result = await operations.dispatch("auth.qr-start", {})
            path = Path(result["qr_path"])
            self.assertTrue(path.exists())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertTrue(result["qr_base64"])
            await operations.dispatch("auth.qr-cancel", {"session_id": result["session_id"]})
            self.assertFalse(path.exists())

    async def test_qr_socket_error_preserves_existing_login(self):
        self.manager.save_cookie("JSESSIONID=old", datetime.now(timezone.utc)+timedelta(hours=8), username="student")
        socket = Socket()
        socket.messages.put_nowait(OSError("connection closed"))
        with patch.object(service, "AuthClient", return_value=self.client()), patch("websockets.asyncio.client.connect", return_value=socket):
            result = await service.start_qr_login()
        self.assertEqual(result["status"], "error")
        self.assertEqual(self.manager.load_record()["cookie"], "JSESSIONID=old")

    def test_qr_profile_verification_requires_valid_username(self):
        with patch.object(service, "SportsAPI") as api, patch.object(service, "_save_verified_login") as save:
            api.return_value.check_login.return_value = {"code": 0, "data": {"loginName": "student", "userName": "Student"}}
            service._save_qr_cookie("JSESSIONID=test-session")
            self.assertEqual(save.call_args.args[:3], ("student", "Student", "JSESSIONID=test-session"))
            api.return_value.check_login.return_value = {"code": 0}
            with self.assertRaises(RuntimeError): service._save_qr_cookie("JSESSIONID=bad")
