import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import httpx

from sja_booking import service
from sja_booking.api import SportsAPI
from sja_booking.auth import AuthManager, AuthState, AuthStore
from sja_booking.models import AuthConfig, UserAuth
from web_api.routes.booking import _list_available_users


class LoginTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.manager = AuthManager(AuthStore(Path(directory.name) / "credentials.json"))
        self.auth = AuthConfig(users=[])
        for patcher in (
            patch.object(service, "_auth_manager", self.manager),
            patch.object(service.CFG, "AUTH", self.auth),
            patch.object(service, "_login_sessions", {}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.expires = datetime.now(timezone.utc) + timedelta(hours=8)

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

    async def test_no_credentials_means_no_profile_request(self):
        with patch.object(service, "_fetch_user_info_sync") as fetch:
            self.assertEqual(await service.fetch_user_infos(), [])
            fetch.assert_not_called()

    def test_user_summary_does_not_expose_configured_password(self):
        self.auth.users.append(UserAuth(nickname="Student", username="student", password="test-password"))
        users = _list_available_users()
        self.assertTrue(users[0]["has_password"])
        self.assertNotIn("password_masked", users[0])
        self.assertNotIn("test-password", str(users))

    def test_named_new_user_is_verified_with_own_cookie_and_saved(self):
        self.auth.users.append(UserAuth(nickname="Other", username="other", cookie="JSESSIONID=other"))
        with patch.object(service, "SportsAPI") as api:
            api.return_value.check_auth_status.return_value = True
            nickname = service._save_verified_login("student", "Student", "JSESSIONID=test-session", self.expires)
            candidate = api.call_args.args[2].users
            self.assertEqual([(u.username, u.cookie) for u in candidate], [("student", "JSESSIONID=test-session")])
            api.return_value.close.assert_called_once()
        self.assertEqual(nickname, "Student")
        users, _ = self.manager.load_all_cookies()
        self.assertEqual(users["student"]["nickname"], "Student")
        self.assertEqual(service._find_user("student").cookie, "JSESSIONID=test-session")

    def test_failed_validation_preserves_existing_credentials(self):
        self.manager.save_cookie("JSESSIONID=old", self.expires, username="student", nickname="Old")
        self.auth.users.append(UserAuth(nickname="Old", username="student", cookie="JSESSIONID=old"))
        with patch.object(service, "SportsAPI") as api:
            api.return_value.check_auth_status.return_value = False
            with self.assertRaises(RuntimeError):
                service._save_verified_login("student", "Student", "JSESSIONID=bad", self.expires)
            api.return_value.close.assert_called_once()
        users, _ = self.manager.load_all_cookies()
        self.assertEqual(users["student"]["cookie"], "JSESSIONID=old")
        self.assertEqual(service._find_user("student").cookie, "JSESSIONID=old")

    async def test_captcha_start_returns_image_without_storing_credentials(self):
        client, _ = self.client()
        with patch.object(service, "AuthClient", return_value=client):
            result = await service.start_login_session(username="student", password="test-password", nickname="Student")
        self.assertTrue(result["captcha_required"])
        self.assertEqual(result["captcha_image"], b"captcha-image")
        self.assertEqual(self.manager.load_all_cookies()[0], {})
        await service.cancel_login_session(result["session_id"])
        client.close.assert_awaited_once()

    async def test_no_captcha_login_uses_verified_persistence(self):
        client, _ = self.client(captcha=False)
        with patch.object(service, "AuthClient", return_value=client), patch.object(service, "SportsAPI") as api:
            api.return_value.check_auth_status.return_value = True
            result = await service.start_login_session(username="student", password="test-password", nickname="Student")
        self.assertTrue(result["success"])
        self.assertIsNotNone(service._find_user("student"))
        client.close.assert_awaited_once()

    async def test_captcha_success_saves_new_user_and_closes_session(self):
        client, state = self.client()
        session = self.session(client, state)
        with patch.object(service, "SportsAPI") as api:
            api.return_value.check_auth_status.return_value = True
            result = await service.submit_login_session_code(session.session_id, "abcde")
        self.assertTrue(result["success"])
        self.assertNotIn(session.session_id, service._login_sessions)
        self.assertIsNotNone(service._find_user("student"))
        client.close.assert_awaited_once()

    async def test_bad_captcha_returns_new_image_without_unbound_nickname(self):
        client, state = self.client()
        client.submit.side_effect = RuntimeError("验证码错误")
        session = self.session(client, state)
        with patch.object(service.asyncio, "sleep", new_callable=AsyncMock):
            result = await service.submit_login_session_code(session.session_id, "wrong")
        self.assertTrue(result["retry"])
        self.assertEqual(result["nickname"], "Student")
        self.assertEqual(result["captcha_image"], b"captcha-image")
        self.assertEqual(self.manager.load_all_cookies()[0], {})

    async def test_expired_captcha_closes_session(self):
        client, state = self.client()
        session = self.session(client, state)
        session.created_at -= timedelta(minutes=6)
        result = await service.submit_login_session_code(session.session_id, "abcde")
        self.assertFalse(result["success"])
        self.assertNotIn(session.session_id, service._login_sessions)
        client.close.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
