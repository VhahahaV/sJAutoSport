import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
import httpx
from pydantic import ValidationError
from sja_booking import config, database, service
from sja_booking.auth import AuthManager, AuthStore
from sja_booking.database import DatabaseManager
from sja_booking.keep_alive import _ping_cookie, run_keep_alive_once
from sja_booking.models import AuthConfig, BookingTarget, Slot
from sja_booking.operations import CONTRACTS, Operations, public
from sja_booking.order import OrderResult

class OperationsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name)
        self.db = DatabaseManager(self.path / "state.db")
        self.manager = AuthManager(AuthStore(self.path / "credentials.json"))
        for patcher in (patch.object(config, "DATA_DIR", self.path), patch.object(config, "AUTH", AuthConfig()),
                        patch.object(service, "_auth_manager", self.manager), patch.object(service, "_active_monitors", {}),
                        patch.object(service, "_paused_monitors", {}), patch.object(service, "_task_handles", {}),
                        patch.object(service, "_order_lock", None), patch.object(service, "_login_sessions", {}), patch.object(service, "_qr_sessions", {}),
                        patch.object(service, "require_authenticated", new_callable=AsyncMock), patch.object(database, "_db_manager", self.db)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.ops = Operations()

    async def asyncTearDown(self):
        await service.shutdown()

    def user(self):
        self.manager.save_cookie("JSESSIONID=test-session", datetime.now(timezone.utc)+timedelta(hours=8), username="student", nickname="Student")

    def test_failed_order_confirmation_is_not_resubmitted_or_moved_to_another_slot(self):
        from sja_booking.order import OrderManager
        manager = OrderManager(Mock(), config.ENCRYPTION_CONFIG)
        with patch.object(manager, "_send_order_request", return_value=(False, "request timed out", None)) as send, patch("sja_booking.order.time.sleep"):
            result = manager.place_order(Slot("test-slot", "19:00", "20:00", available=True), config.PRESET_TARGETS[4], "2030-01-01", "19:00", "20:00")
        self.assertFalse(result.success)
        self.assertEqual(send.call_count, 1)
        manager.api.query_slots.assert_not_called()
        self.assertIn("查询订单", result.message)

    def test_order_confirmation_normalizes_supported_order_id_shapes(self):
        from sja_booking.order import OrderManager
        api = Mock(auth=AuthConfig())
        api.client.cookies = httpx.Cookies()
        manager = OrderManager(api, config.ENCRYPTION_CONFIG)
        for payload in ({"code": 0, "orderId": "test-order"}, {"code": 0, "data": "test-order"}, {"code": 0, "data": {"orderId": "test-order"}}):
            api.client.post.return_value = httpx.Response(200, json=payload)
            success, message, response = manager._send_order_request({"test": "payload"})
            self.assertTrue(success, message)
            self.assertEqual(response["orderId"], "test-order")

    def test_order_cancellation_uses_state_and_inverted_campus_flag(self):
        records = [{"pOrderid": str(index), "orderstateid": state, "cancelOrder": flag}
                   for index, (state, flag) in enumerate([
                       ("1", False), ("1", "false"), ("1", 0), ("1", True), ("1", "true"),
                       ("7", True), ("7", False), ("2", True), ("8", False), ("19", True)])]
        with patch.object(service, "_create_api") as create:
            create.return_value.list_orders.return_value = {"code": 0, "records": records}
            result = service.get_user_orders()
        self.assertEqual([row["can_cancel"] for row in result["orders"]], [True, True, True, False, False, False, False, False, False, False])

    async def test_dashboard_card_configuration_persists_and_validates(self):
        card = await self.ops.dispatch("dashboard.add", {"preset": 5, "days": 7})
        self.assertEqual(await Operations().dispatch("dashboard.list", {}), [card])
        for days in (0, 8):
            with self.assertRaises(ValidationError):
                await self.ops.dispatch("dashboard.add", {"preset": 5, "days": days})
        with self.assertRaises(ValueError):
            await self.ops.dispatch("dashboard.add", {"preset": 9999, "days": 1})
        with patch.object(service, "dashboard_availability", new_callable=AsyncMock) as query:
            await self.ops.dispatch("dashboard.availability", {"card_id": card["id"]})
            query.assert_awaited_once_with(card)
        await self.ops.dispatch("dashboard.delete", {"card_id": card["id"]})
        self.assertEqual(await self.ops.dispatch("dashboard.list", {}), [])
        with self.assertRaises(ValueError):
            await self.ops.dispatch("dashboard.availability", {"card_id": card["id"]})

    def test_dashboard_screens_dates_before_requesting_slot_details(self):
        from sja_booking.models import DateAvailability, FieldType
        today = datetime.now().date()
        dates = [(today + timedelta(days=i)).isoformat() for i in range(8)]
        summaries = [DateAvailability(dates[0], is_all=True), DateAvailability(dates[1], open=False),
                     DateAvailability(dates[2], token="date-token"), DateAvailability(dates[7])]
        field = FieldType("test-type", "test", category="test")
        option = Mock(venue_id="venue", field_type_id="test-type")
        with patch.object(service, "_create_api") as create, patch.object(service, "_get_preset", return_value=option):
            api = create.return_value
            api.list_date_availability.return_value = summaries
            api.list_field_types.return_value = [field]
            api.query_slots.return_value = [Slot("a", "19:00", "20:00", available=True, remain=3),
                                           Slot("full", "20:00", "21:00", available=False, remain=0)]
            result = service._dashboard_availability_sync({"id": "card", "preset": 5, "days": 7})
            api.list_date_availability.assert_called_once_with("venue", "test-type")
            api.query_slots.assert_called_once_with("venue", "test-type", dates[2], date_token="date-token", original_field_type=field)
            api.close.assert_called_once()
        self.assertEqual([day["status"] for day in result["days"]], ["full", "closed", "available", "unopened", "unopened", "unopened", "unopened"])
        self.assertEqual(result["days"][2]["slots"][0].remain, 3)

    def test_dashboard_full_days_skip_details_and_detail_errors_stay_visible(self):
        from sja_booking.models import DateAvailability
        today = datetime.now().date().isoformat()
        with patch.object(service, "_create_api") as create:
            api = create.return_value
            api.list_date_availability.return_value = [DateAvailability(today, is_all=True)]
            result = service._dashboard_availability_sync({"id": "card", "preset": 5, "days": 1})
            self.assertEqual(result["days"][0]["status"], "full")
            api.get_venue_detail.assert_not_called()
            api.query_slots.assert_not_called()
            api.list_date_availability.return_value = [DateAvailability(today)]
            api.get_venue_detail.side_effect = RuntimeError("temporary failure")
            result = service._dashboard_availability_sync({"id": "card", "preset": 5, "days": 1})
            self.assertEqual(result["days"][0]["status"], "error")
            self.assertIn("temporary failure", result["days"][0]["message"])

    def test_date_summary_errors_are_not_reported_as_no_availability(self):
        from sja_booking.api import SportsAPI
        api = SportsAPI(config.BASE_URL, config.ENDPOINTS, config.AUTH)
        try:
            with patch.object(api, "_req", side_effect=RuntimeError("network error")):
                with self.assertRaisesRegex(RuntimeError, "network error"): api.list_date_availability("v", "f")
            with patch.object(api, "_req", return_value=Mock(json=lambda: {"code": 500, "msg": "summary failed"})):
                with self.assertRaisesRegex(RuntimeError, "summary failed"): api.list_date_availability("v", "f")
        finally:
            api.close()

    def test_slot_details_preserve_zero_remaining_and_free_prices(self):
        from sja_booking.api import SportsAPI
        api = SportsAPI(config.BASE_URL, config.ENDPOINTS, config.AUTH)
        try:
            payload = {"code": 0, "data": [{"fieldId": "field", "priceList": [
                {"id": "full", "startTime": "19:00", "endTime": "20:00", "count": 0, "status": "1", "price": 0},
                {"id": "free", "startTime": "20:00", "endTime": "21:00", "count": 3, "status": "1", "price": 0},
            ]}]}
            with patch.object(api, "_req", return_value=Mock(json=lambda: payload)):
                slots = api.query_slots("v", "f", "2030-01-01")
            self.assertEqual([(slot.available, slot.remain, slot.price) for slot in slots], [(False, 0, 0), (True, 3, 0)])
            payload = {"code": 0, "rows": [{"id": "full", "startTime": "19:00", "endTime": "20:00", "remain": 0, "available": True},
                                           {"id": "blocked", "startTime": "20:00", "endTime": "21:00", "isFull": "1"}]}
            with patch.object(api, "_req", return_value=Mock(json=lambda: payload)):
                slots = api.query_slots("v", "f", "2030-01-01")
            self.assertFalse(any(slot.available for slot in slots))
        finally:
            api.close()

    async def test_removed_operations_and_fields_are_rejected(self):
        for operation in ["users.list", "users.use", "schedules.create", "auto.start", "jobs.list"]:
            with self.assertRaises(ValueError): await self.ops.dispatch(operation, {})
        for operation, payload in [("orders.create", {"preset": 5, "date": "1", "start_time": "18", "user": "other"}),
                                   ("monitors.create", {"monitor_id": "m", "target_users": ["other"]})]:
            with self.assertRaises(ValidationError): await self.ops.dispatch(operation, payload)

    async def test_business_requires_login(self):
        service.require_authenticated.side_effect = PermissionError("login required")
        with patch.object(service, "list_venues", new_callable=AsyncMock) as query:
            with self.assertRaises(PermissionError): await self.ops.dispatch("venues.list", {})
            query.assert_not_called()

    async def test_single_account_order_and_duplicate_guard(self):
        self.user()
        with patch.object(service, "_order_once_sync", return_value=OrderResult(True, "booked", "test-order")) as place:
            result = await self.ops.dispatch("orders.create", {"preset": 5, "date": "2030-01-02", "start_time": "18"})
            self.assertTrue(result.success)
            duplicate = await self.ops.dispatch("orders.create", {"preset": 5, "date": "2030-01-02", "start_time": "18"})
            self.assertFalse(duplicate.success)
            self.assertEqual(place.call_count, 1)

    async def test_monitor_auto_booking_completes_for_current_account(self):
        self.user()
        with patch.object(service, "_monitor_worker", new_callable=AsyncMock):
            await service.start_monitor("m", preset=5, preferred_hours=[19], auto_book=True)
        slot = Slot("slot", "19:00", "20:00", available=True, remain=1)
        result = Mock(slots=[service.SlotAvailability("2030-01-02", slot)], resolved=Mock(label="test", venue_name="test", field_type_name="test"))
        with patch.object(service, "list_slots", new_callable=AsyncMock) as query, patch.object(service, "order_once", new_callable=AsyncMock) as place:
            query.return_value = result
            place.return_value = OrderResult(True, "booked", "test-order")
            await service._monitor_check("m")
            self.assertEqual(service._active_monitors["m"]["status"], "completed")
            place.assert_awaited_once()

    async def test_keep_alive_configuration_is_singleton_and_restores(self):
        with patch.object(service, "_keep_alive_worker", new_callable=AsyncMock):
            await self.ops.dispatch("keep-alive.configure", {"enabled": True, "interval_minutes": 10})
            self.assertEqual(service.keep_alive_status()["interval_minutes"], 10)
            await self.ops.dispatch("keep-alive.configure", {"enabled": True, "interval_minutes": 20})
            self.assertEqual(len(self.db.all("settings")), 1)
            await service.shutdown()
            await service.restore_state()
            self.assertIn("keep-alive", service._task_handles)
            await self.ops.dispatch("keep-alive.configure", {"enabled": False})
            self.assertNotIn("keep-alive", service._task_handles)

    async def test_monitors_restore_with_preferences(self):
        with patch.object(service, "_monitor_worker", new_callable=AsyncMock):
            await service.start_monitor("m", preset=5, preferred_hours=[19], preferred_days=[2])
            await service.pause_monitor("m")
            service._paused_monitors.clear()
            await service.restore_state()
        self.assertEqual(service._paused_monitors["m"]["preferred_days"], [2])

    async def test_keep_alive_rejection_keeps_old_cookie(self):
        self.user()
        with patch("sja_booking.keep_alive._ping_cookie", new_callable=AsyncMock) as ping:
            ping.return_value = (False, "", "expired")
            result = await run_keep_alive_once(auth_manager=self.manager)
        self.assertFalse(result.success)
        self.assertEqual(self.manager.load_record()["cookie"], "JSESSIONID=test-session")

    async def test_captcha_file_retry_and_cleanup(self):
        with patch.object(service, "start_login_session", new_callable=AsyncMock) as start:
            start.return_value = {"success": True, "captcha_required": True, "session_id": "session", "captcha_image": b"first"}
            result = await self.ops.dispatch("auth.start", {"username": "student", "password": "test-password"})
        first = Path(result["captcha_path"])
        self.assertEqual(first.read_bytes(), b"first")
        self.assertEqual(first.stat().st_mode & 0o777, 0o600)
        self.assertEqual(start.call_args.kwargs["password"], "test-password")
        with patch.object(service, "submit_login_session_code", new_callable=AsyncMock) as verify:
            verify.return_value = {"success": False, "retry": True, "captcha_image": b"second"}
            result = await self.ops.dispatch("auth.verify", {"session_id": "session", "code": "bad"})
        self.assertFalse(first.exists())
        second = Path(result["captcha_path"])
        self.assertEqual(second.read_bytes(), b"second")
        with patch.object(service, "submit_login_session_code", new_callable=AsyncMock) as verify:
            verify.return_value = {"success": True, "cookie": "JSESSIONID=test-session"}
            result = public(await self.ops.dispatch("auth.verify", {"session_id": "session", "code": "good"}))
        self.assertFalse(second.exists())
        self.assertNotIn("cookie", result)


    async def test_slots_forward_target_and_date(self):
        with patch.object(service, "list_slots", new_callable=AsyncMock) as query:
            query.return_value = {"slots": []}
            await self.ops.dispatch("slots.list", {"preset": 5, "date": "1", "show_full": True, "target": {"duration_hours": 2}})
        self.assertEqual(query.call_args.kwargs["base_target"].duration_hours, 2)
        self.assertTrue(query.call_args.kwargs["show_full"])


    async def test_monitor_create_pause_resume_delete(self):
        async def sleeper(*args):
            await asyncio.sleep(3600)
        with patch.object(service, "_monitor_worker", side_effect=sleeper):
            result = await self.ops.dispatch("monitors.create", {"monitor_id": "m", "preset": 5, "preferred_hours": [19], "preferred_days": [1], "auto_book": False})
            self.assertTrue(result["success"])
            await asyncio.sleep(0)
            self.assertEqual(self.db.get("monitor", "m")["preferred_hours"], [19])
            self.assertTrue((await self.ops.dispatch("monitors.pause", {"monitor_id": "m"}))["success"])
            self.assertFalse(any(t.get_name() == "monitor:m" for t in asyncio.all_tasks()))
            self.assertTrue((await self.ops.dispatch("monitors.resume", {"monitor_id": "m"}))["success"])
            self.assertTrue((await self.ops.dispatch("monitors.delete", {"monitor_id": "m"}))["success"])
            self.assertIsNone(self.db.get("monitor", "m"))


    async def test_keep_alive_rejects_empty_success_profile(self):
        client = AsyncMock()
        client.cookies = httpx.Cookies()
        client.get.return_value = httpx.Response(200, json={"code": 0, "msg": "success"})
        client.__aenter__.return_value = client
        with patch("sja_booking.keep_alive.httpx.AsyncClient", return_value=client):
            success, _, _ = await _ping_cookie("student", "Student", "JSESSIONID=test-session")
        self.assertFalse(success)


    async def test_database_reservation_history(self):
        await self.db.save_reservation("badminton", "2030-01-01", "order", "booked")
        self.assertEqual((await self.db.get_reservation("badminton", "2030-01-01"))["order_id"], "order")
        self.assertTrue(await self.db.delete_reservation_by_order_id("order"))
        self.assertIsNone(await self.db.get_reservation("badminton", "2030-01-01"))

    async def test_event_cursor(self):
        from sja_booking.notification import emit
        emit("test", {"message": "first"})
        result = await self.ops.dispatch("events.list", {"limit": 1})
        emit("test", {"message": "second"})
        following = await self.ops.dispatch("events.list", {"after": result["next_cursor"]})
        self.assertEqual(len(following["events"]), 1)
        self.assertEqual(following["events"][0]["data"]["message"], "second")


    def test_slot_query_never_falls_back_to_a_different_date(self):
        from sja_booking.monitor import SlotMonitor
        from sja_booking.models import MonitorPlan
        api = Mock()
        api.resolve_target_dates.return_value = ["2030-01-02"]
        api.list_available_dates.return_value = [("2030-01-03", "date-token")]
        monitor = SlotMonitor(api, BookingTarget(), MonitorPlan())
        monitor.resolve_context = Mock()
        self.assertEqual(monitor.run_once(), [])
        api.query_slots.assert_not_called()


    def test_credential_store_is_private(self):
        self.user()
        self.assertEqual(self.manager.store.path.stat().st_mode & 0o777, 0o600)


    def test_corrupt_credentials_are_not_overwritten(self):
        self.manager.store.path.write_text("{broken-json")
        with self.assertRaises(RuntimeError):
            self.manager.load_record()
        self.assertEqual(self.manager.store.path.read_text(), "{broken-json")


    def test_cancel_order_http_chain_and_error_stops_later_requests(self):
        from sja_booking.api import SportsAPI
        api = SportsAPI.__new__(SportsAPI)
        api.endpoints = config.ENDPOINTS
        api._req = Mock(side_effect=[httpx.Response(200, json={"code": code}) for code in ["1", "2", "3"]])
        self.assertEqual(len(api.cancel_order("test-order")), 3)
        self.assertEqual(api._req.call_count, 3)
        api._req = Mock(return_value=httpx.Response(200, json={"code": 401, "msg": "login required"}))
        with self.assertRaises(RuntimeError):
            api.cancel_order("test-order")
        self.assertEqual(api._req.call_count, 1)
        api._req = Mock(return_value=httpx.Response(200, text="<html>login</html>"))
        with self.assertRaises(RuntimeError):
            api.cancel_order("test-order")


    def test_all_contracts_have_schema_and_no_web_dependency(self):
        for model, description in CONTRACTS.values():
            self.assertTrue(model.model_json_schema())
            self.assertTrue(description)
        self.assertNotIn("test-password", json.dumps(public({"password": "test-password", "nested": {"cookie": "secret"}})))
