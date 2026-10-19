import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
import httpx
from sja_booking import config, service, database, keep_alive
from sja_booking.auth import AuthClient, AuthManager, AuthState, AuthStore, restore_cookies, serialize_cookies
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
        self.assertEqual(set(self.manager.store.load()), {"username", "nickname", "cookie", "expires_at", "session_cookies", "verified_at", "renewed_at", "login_required"})

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
        self.assertIsNone(self.manager.load_record()["expires_at"])
        self.assertTrue(any(c["domain"] == "jaccount.sjtu.edu.cn" for c in self.manager.load_record()["session_cookies"]))
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

    async def test_status_returns_one_account_without_cookie(self):
        self.manager.save_cookie("JSESSIONID=test-session", self.expires, username="student")
        client, _ = self.client()
        with patch.object(keep_alive, "AuthClient", return_value=client):
            result = await service.login_status()
        self.assertTrue(result["success"])
        self.assertEqual(result["account"]["username"], "student")
        self.assertNotIn("test-session", str(result))

    async def test_status_repairs_placeholder_identity_from_verified_profile(self):
        self.manager.save_cookie("JSESSIONID=test-session", self.expires, username="__default__")
        client, _ = self.client()
        with patch.object(keep_alive, "AuthClient", return_value=client):
            result = await service.login_status()
        self.assertEqual(result["account"]["username"], "student")
        self.assertEqual(result["account"]["nickname"], "测试同学")
        record = self.manager.load_record()
        self.assertEqual(record["cookie"], "JSESSIONID=test-session")
        self.assertIsNone(record["expires_at"])

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
        cookies.set("JSESSIONID", "test-sso", domain="jaccount.sjtu.edu.cn", path="/jaccount")
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
        client.current_user = AsyncMock(return_value={"loginName": "student", "userName": "测试同学"})
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

    def seed_sso(self):
        cookies = httpx.Cookies()
        cookies.set("JSESSIONID", "old-sports", domain="sports.sjtu.edu.cn", path="/")
        cookies.set("JSESSIONID", "sso-login", domain="jaccount.sjtu.edu.cn", path="/jaccount")
        cookies.set("JSESSIONID", "sso-oauth", domain="jaccount.sjtu.edu.cn", path="/oauth2")
        cookies.set("ticket", "sso-ticket", domain="jaccount.sjtu.edu.cn", path="/")
        self.manager.save_cookie("JSESSIONID=old-sports", username="student",
                                 session_cookies=serialize_cookies(cookies))
        return cookies

    def campus_transport(self, handler):
        real_client = httpx.AsyncClient
        return patch("sja_booking.auth.httpx.AsyncClient", side_effect=lambda **kwargs:
                     real_client(transport=httpx.MockTransport(handler), **kwargs))

    def recovery_handler(self, *, challenge=False, account="student", on_callback=None):
        seen = []
        def handler(request):
            seen.append((request.url.host, request.url.path))
            header = request.headers.get("cookie", "")
            if request.url.host == "jaccount.sjtu.edu.cn":
                self.assertIn("JSESSIONID=sso-oauth", header)
                self.assertIn("ticket=sso-ticket", header)
                self.assertNotIn("old-sports", header)
                self.assertNotIn("sso-login", header)
                if challenge:
                    return httpx.Response(200, text='<form id="passwordForm">captcha required</form>')
                return httpx.Response(302, headers={"location": "https://sports.sjtu.edu.cn/oauth2Login?code=test-code"})
            self.assertNotIn("sso-ticket", header)
            self.assertNotIn("sso-login", header)
            if request.url.path == "/oauth2Login":
                if on_callback:
                    on_callback()
                return httpx.Response(302, headers={"location": "/pc/", "set-cookie": "JSESSIONID=new-sports.route1; Path=/; Secure; HttpOnly"})
            if request.url.path == "/pc/":
                return httpx.Response(200, text="sports")
            self.assertEqual(request.url.path, config.ENDPOINTS.current_user)
            if "new-sports.route1" in header:
                return httpx.Response(200, json={"code": 0, "data": {"loginName": account, "userName": "Student"}})
            return httpx.Response(200, json={"code": 0, "data": None})
        return handler, seen

    def test_cookie_jar_round_trip_keeps_domain_path_and_security(self):
        cookies = self.seed_sso()
        restored = restore_cookies(self.manager.load_record())
        self.assertEqual(serialize_cookies(restored), serialize_cookies(cookies))
        self.assertEqual(self.path.joinpath("credentials.json").stat().st_mode & 0o777, 0o600)
        from sja_booking.operations import public
        rendered = str(public(self.manager.load_record()))
        for secret in ("old-sports", "sso-login", "sso-oauth", "sso-ticket"):
            self.assertNotIn(secret, rendered)

    async def test_expired_sports_session_recovers_with_scoped_sso(self):
        self.seed_sso()
        handler, seen = self.recovery_handler()
        with self.campus_transport(handler):
            result = await service.login_status()
        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "renewed")
        record = self.manager.load_record()
        self.assertEqual(record["cookie"], "JSESSIONID=new-sports.route1")
        self.assertIsNone(record["expires_at"])
        self.assertTrue(record["renewed_at"])
        sports_cookie = next(c for c in record["session_cookies"] if c["domain"] == "sports.sjtu.edu.cn")
        self.assertTrue(sports_cookie["secure"])
        self.assertFalse(sports_cookie["domain_specified"])
        self.assertIn("HttpOnly", sports_cookie["rest"])
        self.assertTrue(result["account"]["sso_available"])
        self.assertEqual(sum(host == "jaccount.sjtu.edu.cn" for host, _ in seen), 1)
        self.assertEqual([e["type"] for e in self.db.all("event")], ["session_renewed"])
        # Dotted server routing suffixes are valid and must be sent unchanged.
        api = SportsAPI(config.BASE_URL, config.ENDPOINTS, config.AUTH)
        try:
            self.assertIn("new-sports.route1", api.client.build_request("GET", "/").headers["cookie"])
        finally:
            api.close()

    async def test_concurrent_checks_authorize_once(self):
        self.seed_sso()
        handler, seen = self.recovery_handler()
        with self.campus_transport(handler):
            results = await asyncio.gather(*[keep_alive.run_keep_alive_once(auth_manager=self.manager) for _ in range(5)])
        self.assertTrue(all(r.success for r in results))
        self.assertEqual(sum(r.status == "renewed" for r in results), 1)
        self.assertEqual(sum(host == "jaccount.sjtu.edu.cn" for host, _ in seen), 1)

    async def test_sso_challenge_is_latched_until_user_logs_in(self):
        self.seed_sso()
        original = self.manager.load_record()
        handler, seen = self.recovery_handler(challenge=True)
        with self.campus_transport(handler):
            first = await keep_alive.run_keep_alive_once(auth_manager=self.manager)
            count = len(seen)
            second = await keep_alive.run_keep_alive_once(auth_manager=self.manager)
        self.assertEqual(first.status, "login_required")
        self.assertEqual(second.message, first.message)
        self.assertEqual(len(seen), count)
        self.assertEqual(self.manager.load_record()["cookie"], original["cookie"])
        self.assertEqual(self.manager.load_record()["session_cookies"], original["session_cookies"])
        self.assertEqual(len(self.db.all("event")), 1)
        # A new successful interactive login clears the latch.
        self.seed_sso()
        self.assertFalse(self.manager.load_record()["login_required"])

    async def test_network_failure_preserves_credentials_and_does_not_request_login(self):
        self.seed_sso()
        original = self.manager.store.load()
        def handler(request):
            raise httpx.ConnectTimeout("private authorization URL must not be exposed", request=request)
        with self.campus_transport(handler):
            result = await keep_alive.run_keep_alive_once(auth_manager=self.manager)
        self.assertEqual(result.status, "error")
        self.assertNotIn("private", result.message)
        self.assertEqual(self.manager.store.load(), original)
        self.assertFalse(self.db.all("event"))

    async def test_failed_reauthorization_keeps_valid_sso_for_later_retry(self):
        self.seed_sso()
        original = self.manager.store.load()
        handler, _ = self.recovery_handler()
        def failing(request):
            if request.url.host == "jaccount.sjtu.edu.cn":
                return httpx.Response(503)
            return handler(request)
        with self.campus_transport(failing):
            result = await keep_alive.run_keep_alive_once(auth_manager=self.manager)
        self.assertEqual(result.status, "error")
        self.assertEqual(self.manager.store.load(), original)

    async def test_profile_service_errors_do_not_discard_session(self):
        self.seed_sso()
        original = self.manager.store.load()
        responses = [httpx.Response(503), httpx.Response(200, text="malformed"),
                     httpx.Response(200, json={"code": 500, "msg": "service unavailable"})]
        for response in responses:
            with self.campus_transport(lambda request: response):
                result = await keep_alive.run_keep_alive_once(auth_manager=self.manager)
            self.assertEqual(result.status, "error")
            self.assertEqual(self.manager.store.load(), original)

    async def test_storage_failure_is_not_misreported_as_a_campus_outage(self):
        self.seed_sso()
        handler, _ = self.recovery_handler()
        with self.campus_transport(handler), patch.object(self.manager, "save_cookie", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                await keep_alive.run_keep_alive_once(auth_manager=self.manager)

    async def test_different_account_does_not_replace_saved_session(self):
        self.seed_sso()
        handler, _ = self.recovery_handler(account="other-student")
        with self.campus_transport(handler):
            result = await keep_alive.run_keep_alive_once(auth_manager=self.manager)
        self.assertEqual(result.status, "login_required")
        self.assertEqual(self.manager.load_record()["username"], "student")
        self.assertEqual(self.manager.load_record()["cookie"], "JSESSIONID=old-sports")

    async def test_logout_during_recovery_does_not_resurrect_credentials(self):
        self.seed_sso()
        handler, _ = self.recovery_handler(on_callback=self.manager.clear)
        with self.campus_transport(handler):
            result = await keep_alive.run_keep_alive_once(auth_manager=self.manager)
        self.assertEqual(result.status, "session_changed")
        self.assertIsNone(self.manager.load_record())
        self.assertFalse(self.db.all("event"))

    async def test_new_login_during_recovery_is_not_overwritten(self):
        self.seed_sso()
        handler, _ = self.recovery_handler(on_callback=lambda: self.manager.save_cookie("JSESSIONID=other-session", username="other"))
        with self.campus_transport(handler):
            result = await keep_alive.run_keep_alive_once(auth_manager=self.manager)
        self.assertEqual(result.status, "session_changed")
        self.assertEqual(self.manager.load_record()["username"], "other")
        self.assertEqual(self.manager.load_record()["cookie"], "JSESSIONID=other-session")

    async def test_legacy_sports_cookie_requires_one_login_to_capture_sso(self):
        self.manager.save_cookie("JSESSIONID=old-sports", self.expires, username="student")
        with self.campus_transport(lambda request: httpx.Response(401)):
            result = await keep_alive.run_keep_alive_once(auth_manager=self.manager)
        self.assertEqual(result.status, "login_required")
        self.assertIn("重新登录一次", result.message)

    async def test_recovery_rejects_redirects_outside_campus_auth(self):
        self.seed_sso()
        original = self.manager.store.load()
        handler, _ = self.recovery_handler()
        def malicious(request):
            if request.url.host == "jaccount.sjtu.edu.cn":
                return httpx.Response(302, headers={"location": "https://example.org/collect?code=private-code"})
            return handler(request)
        with self.campus_transport(malicious):
            result = await keep_alive.run_keep_alive_once(auth_manager=self.manager)
        self.assertEqual(result.status, "error")
        self.assertNotIn("private-code", result.message)
        self.assertEqual(self.manager.store.load(), original)


    async def test_http_login_rejection_returns_actionable_reason(self):
        client = AuthClient(config.BASE_URL, config.ENDPOINTS, self.auth)
        response = httpx.Response(200, text='<span id="errmsg">验证码错误</span>', request=httpx.Request("POST", "https://jaccount.sjtu.edu.cn/jaccount/ulogin"))
        try:
            with self.assertRaisesRegex(RuntimeError, "验证码错误"):
                await client.follow_redirects(response)
        finally:
            await client.close()
