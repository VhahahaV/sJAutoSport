import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
import httpx
from sja_booking import config, service, database
from sja_booking.auth import AuthClient, AuthManager, AuthState, AuthStore
from sja_booking.api import SportsAPI
from sja_booking.database import DatabaseManager
from sja_booking.models import AuthConfig, UserAuth

class LoginTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name)
        self.manager = AuthManager(AuthStore(self.path / "credentials.json"))
        self.auth = AuthConfig()
        self.db = DatabaseManager(self.path / "state.db")
        self.expires = datetime.now(timezone.utc) + timedelta(hours=8)
        for patcher in (patch.object(service, "_auth_manager", self.manager),
                        patch.object(config, "AUTH", self.auth),
                        patch.object(database, "_db_manager", self.db),
                        patch.object(service, "_login_sessions", {}), patch.object(service, "_qr_sessions", {})):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_verified_login_stores_exactly_one_account(self):
        self.manager.save_cookie("JSESSIONID=old", self.expires, username="old")
        with patch.object(service, "SportsAPI") as api:
            api.return_value.check_auth_status.return_value = True
            service._save_verified_login("student", None, "JSESSIONID=test-session", self.expires)
            self.assertEqual(api.call_args.args[2].user.username, "student")
        record = self.manager.load_record()
        self.assertEqual(record["username"], "student")
        self.assertEqual(set(self.manager.store.load()), {"username", "nickname", "cookie", "expires_at"})

    def test_failed_login_preserves_current_credential(self):
        self.manager.save_cookie("JSESSIONID=old", self.expires, username="student")
        with patch.object(service, "SportsAPI") as api:
            api.return_value.check_auth_status.return_value = False
            with self.assertRaises(RuntimeError): service._save_verified_login("student", None, "JSESSIONID=bad", self.expires)
        self.assertEqual(self.manager.load_record()["cookie"], "JSESSIONID=old")

    async def test_start_login_initializes_database_before_captcha(self):
        client, _ = self.client()
        with patch.object(service, "AuthClient", return_value=client):
            result = await service.start_login_session(username="student", password="test-password")
        self.assertTrue(self.db.db_path.exists())
        self.assertTrue(result["captcha_required"])
        self.assertIsNone(self.manager.load_record())
        await service.cancel_login_session(result["session_id"])

    async def test_captcha_success_persists_single_session(self):
        client, state = self.client()
        session = self.session(client, state)
        with patch.object(service, "SportsAPI") as api:
            api.return_value.check_auth_status.return_value = True
            result = await service.submit_login_session_code(session.session_id, "abcde")
        self.assertTrue(result["success"])
        self.assertNotIn("cookie", result)
        self.assertEqual(self.manager.load_record()["username"], "student")
        self.assertFalse(service._login_sessions)

    async def test_captcha_retry_and_expiration(self):
        client, state = self.client()
        session = self.session(client, state)
        client.submit.side_effect = RuntimeError("验证码错误")
        with patch.object(service.asyncio, "sleep", new_callable=AsyncMock):
            retry = await service.submit_login_session_code(session.session_id, "bad")
        self.assertTrue(retry["retry"])
        session.created_at -= timedelta(minutes=6)
        result = await service.submit_login_session_code(session.session_id, "abcde")
        self.assertFalse(result["success"])
        self.assertFalse(service._login_sessions)

    def test_status_returns_one_account_without_cookie(self):
        self.manager.save_cookie("JSESSIONID=test-session", self.expires, username="student")
        with patch.object(service, "SportsAPI") as api:
            api.return_value.check_auth_status.return_value = True
            result = service.login_status()
        self.assertTrue(result["success"])
        self.assertEqual(result["account"]["username"], "student")
        self.assertNotIn("test-session", str(result))

    def test_status_repairs_placeholder_identity_from_verified_profile(self):
        self.manager.save_cookie("JSESSIONID=test-session", self.expires, username="__default__")
        with patch.object(service, "SportsAPI") as api:
            api.return_value.check_auth_status.return_value = True
            api.return_value.check_login.return_value = {"code": 0, "data": {"loginName": "student", "userName": "测试同学"}}
            result = service.login_status()
        self.assertEqual(result["account"]["username"], "student")
        self.assertEqual(result["account"]["nickname"], "测试同学")
        record = self.manager.load_record()
        self.assertEqual(record["cookie"], "JSESSIONID=test-session")
        self.assertEqual(record["expires_at"], self.expires)

    async def test_account_info_returns_real_profile_and_repairs_saved_identity(self):
        self.manager.save_cookie("JSESSIONID=test-session", self.expires, username="__default__")
        with patch.object(service, "SportsAPI") as api:
            api.return_value.check_login.return_value = {"code": 0, "data": {
                "loginName": "student", "userName": "测试同学", "code": "TEST_ID",
                "dept": {"deptName": "测试学院"}, "classNo": "TEST_CLASS",
                "roles": [{"roleName": "学生"}], "sjtuAccessToken": "test-private-token",
            }}
            result = await service.fetch_user_info()
        self.assertTrue(result["success"])
        self.assertEqual(result["profile"]["dept"], "测试学院")
        self.assertEqual(result["profile"]["roles"], ["学生"])
        self.assertEqual(self.manager.load_record()["username"], "student")
        from sja_booking.operations import public
        self.assertNotIn("test-private-token", str(public(result)))

    async def test_failed_profile_does_not_replace_current_identity(self):
        self.manager.save_cookie("JSESSIONID=test-session", self.expires, username="student", nickname="My nickname")
        before = self.manager.store.load()
        with patch.object(service, "SportsAPI") as api:
            api.return_value.check_login.return_value = {"code": 401, "msg": "会话已失效", "data": {"loginName": "other"}}
            result = await service.fetch_user_info()
        self.assertFalse(result["success"])
        self.assertIsNone(result["profile"])
        self.assertEqual(self.manager.store.load(), before)

    def test_profile_identity_update_preserves_custom_nickname_and_newer_session(self):
        self.manager.save_cookie("JSESSIONID=new", self.expires, username="student", nickname="My nickname")
        self.manager.update_identity("JSESSIONID=old", username="other", nickname="Other")
        self.assertEqual(self.manager.load_record()["username"], "student")
        self.manager.update_identity("JSESSIONID=new", username="student", nickname="测试同学")
        self.assertEqual(self.manager.load_record()["nickname"], "My nickname")
        self.assertEqual(self.manager.load_record()["cookie"], "JSESSIONID=new")

    def test_empty_profile_is_not_reported_as_success(self):
        for payload in ({"code": 0, "data": {}}, {"error": "unavailable"}, {"code": 0, "data": {"dept": {"deptName": "测试学院"}}}):
            result = service._normalize_user_payload(payload)
            self.assertFalse(result["success"])
            self.assertIsNone(result["profile"])

    def client(self, *, captcha=True):
        cookies = httpx.Cookies()
        cookies.set("JSESSIONID", "test-session", domain="sports.sjtu.edu.cn")
        state = AuthState(
            prepare_url="https://sports.sjtu.edu.cn/",
            submit_url="https://jaccount.sjtu.edu.cn/",
            captcha_url=None, form={}, cookies=cookies, captcha_required=captcha,
        )
        client = Mock()
        client._client.cookies = cookies
        client.prepare = AsyncMock(return_value=state)
        client.submit = AsyncMock()
        client.follow_redirects = AsyncMock()
        client.fetch_captcha = AsyncMock(return_value=b"captcha-image")
        client.close = AsyncMock()
        return client, state


    def session(self, client, state):
        session = service.LoginSession(
            session_id="test-login", client=client, state=state,
            username="student", password="test-password", nickname="Student",
            created_at=datetime.now(timezone.utc),
        )
        service._login_sessions[session.session_id] = session
        return session


    def test_empty_success_response_is_not_authenticated(self):
        api = SportsAPI.__new__(SportsAPI)
        api.check_login = Mock(return_value={"code": 0, "msg": "操作成功"})
        self.assertFalse(api.check_auth_status())


    def test_profile_response_is_authenticated(self):
        api = SportsAPI.__new__(SportsAPI)
        api.check_login = Mock(return_value={"code": 0, "data": {"loginName": "student"}})
        self.assertTrue(api.check_auth_status())


    def test_error_response_is_not_authenticated(self):
        api = SportsAPI.__new__(SportsAPI)
        api.check_login = Mock(return_value={"code": -1, "error": True})
        self.assertFalse(api.check_auth_status())


    async def test_http_login_form_captcha_post_redirect_and_cookie(self):
        from urllib.parse import parse_qs
        seen = []

        def handler(request):
            seen.append((request.method, request.url.path))
            if request.url.path == "/oauth2/authorize":
                return httpx.Response(200, text='<form action="/jaccount/ulogin"><input type="hidden" name="csrf" value="test-csrf"><img id="captcha-img" src="/jaccount/captcha?uuid=12345678-abcd"></form>')
            if request.url.path == "/jaccount/captcha":
                return httpx.Response(200, content=b"test-image")
            if request.url.path == "/jaccount/ulogin":
                form = parse_qs(request.content.decode())
                self.assertEqual(form["user"], ["student"])
                self.assertEqual(form["pass"], ["test-password"])
                self.assertEqual(form["captcha"], ["abcde"])
                self.assertEqual(form["csrf"], ["test-csrf"])
                return httpx.Response(302, headers={"location": "https://sports.sjtu.edu.cn/oauth2Login"})
            if request.url.path == "/oauth2Login":
                return httpx.Response(302, headers={"location": "/pc/", "set-cookie": "JSESSIONID=test-session; Path=/"})
            return httpx.Response(200, text="logged in")

        client = AuthClient(config.BASE_URL, config.ENDPOINTS, self.auth)
        await client.close()
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
        try:
            state = await client.prepare()
            self.assertTrue(state.captcha_required)
            self.assertEqual(await client.fetch_captcha(state), b"test-image")
            response = await client.submit(state, "student", "test-password", "abcde")
            final = await client.follow_redirects(response)
            self.assertEqual(final.request.url.host, "sports.sjtu.edu.cn")
            self.assertEqual(client._client.cookies.get("JSESSIONID"), "test-session")
            self.assertIn(("POST", "/jaccount/ulogin"), seen)
        finally:
            await client.close()


    async def test_http_login_rejection_returns_actionable_reason(self):
        client = AuthClient(config.BASE_URL, config.ENDPOINTS, self.auth)
        response = httpx.Response(200, text='<span id="errmsg">验证码错误</span>', request=httpx.Request("POST", "https://jaccount.sjtu.edu.cn/jaccount/ulogin"))
        try:
            with self.assertRaisesRegex(RuntimeError, "验证码错误"):
                await client.follow_redirects(response)
        finally:
            await client.close()
