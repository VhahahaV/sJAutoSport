"""Notification helpers for communicating with the Bot service."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence

import httpx

import config as CFG

logger = logging.getLogger(__name__)


@dataclass
class OrderNotification:
    """Order notification payload."""

    order_id: str
    user_nickname: str
    venue_name: str
    field_type_name: str
    date: str
    start_time: str
    end_time: str
    success: bool
    message: str


def _format_day_label(day: int) -> str:
    mapping = {
        0: "今天",
        1: "明天",
        2: "后天",
        3: "第3天",
        4: "第4天",
        5: "第5天",
        6: "第6天",
        7: "第7天",
        8: "第8天",
    }
    label = mapping.get(day)
    return f"{day}（{label}）" if label else str(day)


def _format_hour_label(hour: int) -> str:
    return f"{int(hour):02d}:00"


def _format_monitor_slot_line(slot: Dict[str, Any]) -> str:
    date = slot.get("date") or "-"
    start = slot.get("start") or "?"
    end = slot.get("end") or "?"
    field = slot.get("field_name") or slot.get("area_name")
    remain = slot.get("remain")
    price = slot.get("price")

    meta_parts: List[str] = []
    if remain not in (None, "", "-1"):
        meta_parts.append(f"余{remain}")
    if isinstance(price, (int, float)):
        meta_parts.append(f"¥{price:.0f}")

    parts = [f"{date} {start}-{end}"]
    if field:
        parts.append(str(field))
    if meta_parts:
        parts.append(" ".join(meta_parts))
    return " | ".join(parts)


def _unique(values: Optional[Iterable[Any]]) -> List[str]:
    if not values:
        return []
    seen: set[str] = set()
    result: List[str] = []
    for item in values:
        text = str(item).strip()
        if not text or text.lower() in {"all", "everyone"}:
            continue
        if text not in seen:
            seen.add(text)
            result.append(text)
    return result


class NotificationService:
    """Notification service wrapper around an OneBot-compatible HTTP API."""

    def __init__(
        self,
        bot_http_url: str = "http://127.0.0.1:3000",
        access_token: Optional[str] = None,
        *,
        default_delay: int = 0,
        retry_count: int = 3,
        retry_delay: int = 5,
        template: Optional[Dict[str, str]] = None,
    ) -> None:
        self.bot_http_url = bot_http_url.rstrip("/")
        self.access_token = access_token or None
        self.default_delay = max(0, int(default_delay))
        self.retry_count = max(1, int(retry_count))
        self.retry_delay = max(0, int(retry_delay))
        self.template = template or {}
        self.client = httpx.AsyncClient(timeout=10.0)

    async def broadcast(
        self,
        message: str,
        *,
        target_groups: Optional[Sequence[str]] = None,
        target_users: Optional[Sequence[str]] = None,
    ) -> bool:
        """Send a plain text message to the configured targets."""
        groups = _unique(target_groups)
        users = _unique(target_users)
        if not groups and not users:
            logger.warning("通知未发送：未配置任何目标群组或用户。")
            return False

        if self.default_delay:
            await asyncio.sleep(self.default_delay)

        success = False
        # 为每个群组发送之间添加间隔，避免触发 QQ 风控
        for index, group_id in enumerate(groups):
            if index > 0:
                await asyncio.sleep(2.5)  # 每个群组之间间隔 2.5 秒
            try:
                group_numeric = int(float(group_id))
            except (TypeError, ValueError):
                logger.error("群组 ID %s 不是有效的数字，已跳过。", group_id)
                continue
            if await self._post_with_retry(
                "/send_group_msg",
                {"group_id": int(group_numeric), "message": message},
            ):
                success = True
        # 为每个用户发送之间添加间隔
        for index, user_id in enumerate(users):
            if index > 0 or groups:  # 如果有群组，第一个用户也需要间隔
                await asyncio.sleep(2.5)  # 每个用户之间间隔 2.5 秒
            try:
                user_numeric = int(float(user_id))
            except (TypeError, ValueError):
                logger.error("用户 ID %s 不是有效的数字，已跳过。", user_id)
                continue
            if await self._post_with_retry(
                "/send_private_msg",
                {"user_id": int(user_numeric), "message": message},
            ):
                success = True
        return success

    async def send_order_success_notification(
        self,
        notification: OrderNotification,
        target_groups: Optional[Sequence[str]] = None,
        target_users: Optional[Sequence[str]] = None,
    ) -> bool:
        """Send an order success notification to Bot targets."""
        message = self._build_order_message(notification)
        return await self.broadcast(message, target_groups=target_groups, target_users=target_users)

    async def send_monitor_slots_notification(
        self,
        *,
        monitor_id: str,
        venue_name: Optional[str],
        field_type_name: Optional[str],
        slots: List[Dict[str, Any]],
        auto_book: bool,
        target_groups: Optional[Sequence[str]] = None,
        target_users: Optional[Sequence[str]] = None,
        preferred_hours: Optional[Sequence[int]] = None,
        preferred_days: Optional[Sequence[int]] = None,
        booking_users: Optional[Sequence[str]] = None,
        excluded_users: Optional[Sequence[str]] = None,
    ) -> bool:
        """Send availability information discovered by a monitor."""
        if not slots:
            return False
        message = self._build_monitor_message(
            monitor_id=monitor_id,
            venue_name=venue_name,
            field_type_name=field_type_name,
            slots=slots,
            auto_book=auto_book,
            preferred_hours=preferred_hours,
            preferred_days=preferred_days,
            booking_users=booking_users,
            excluded_users=excluded_users,
        )
        return await self.broadcast(message, target_groups=target_groups, target_users=target_users)

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    async def _post_with_retry(self, path: str, payload: Dict[str, Any]) -> bool:
        url = f"{self.bot_http_url}{path}"
        for attempt in range(1, self.retry_count + 1):
            try:
                response = await self.client.post(url, json=payload, headers=self._headers())
                response.raise_for_status()
                data = response.json()
                if data.get("status") == "ok":
                    return True
                logger.error("Bot 返回异常状态 %s: %s", path, data)
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                text = exc.response.text
                logger.error(
                    "Bot 接口 %s 返回 HTTP %s: %s",
                    path,
                    status,
                    text.strip()[:500] if text else "无响应体",
                )
                if status == 502:
                    logger.error(
                        "Bot 服务返回 502。请确认 OneBot/Go-CQHTTP 服务已启动并监听 %s。",
                        self.bot_http_url,
                    )
            except Exception as exc:  # pylint: disable=broad-except
                logger.error(
                    "Bot 接口 %s 请求异常（第 %s/%s 次尝试）: %s",
                    path,
                    attempt,
                    self.retry_count,
                    exc,
                )
            if attempt < self.retry_count:
                await asyncio.sleep(self.retry_delay)
        return False

    def _build_order_message(self, notification: OrderNotification) -> str:
        if notification.success:
            title = self.template.get("success_title", "🎉 订单预订成功！")
            reminder = self.template.get("payment_reminder")
        else:
            title = self.template.get("failure_title", "❌ 订单预订失败")
            reminder = None

        message = (
            f"{title}\n\n"
            f"📋 订单信息：\n"
            f"🆔 订单ID: {notification.order_id}\n"
            f"👤 用户: {notification.user_nickname}\n"
            f"🏟️ 场馆: {notification.venue_name}\n"
            f"🏃 项目: {notification.field_type_name}\n"
            f"📅 日期: {notification.date}\n"
            f"⏰ 时间: {notification.start_time} - {notification.end_time}\n\n"
        )
        if reminder:
            message += f"{reminder}\n\n"
        message += notification.message
        return message

    def _build_monitor_message(
        self,
        *,
        monitor_id: str,
        venue_name: Optional[str],
        field_type_name: Optional[str],
        slots: List[Dict[str, Any]],
        auto_book: bool,
        preferred_hours: Optional[Sequence[int]],
        preferred_days: Optional[Sequence[int]],
        booking_users: Optional[Sequence[str]],
        excluded_users: Optional[Sequence[str]],
    ) -> str:
        lines = [
            f"📡 监控任务 {monitor_id} 检测到可预订场次",
        ]
        if venue_name or field_type_name:
            venue_line = " / ".join(
                [text for text in (venue_name, field_type_name) if text]
            )
            if venue_line:
                lines.append(f"🏟️ {venue_line}")
        lines.append(f"🤖 自动预订：{'开启' if auto_book else '关闭'}")

        if preferred_hours:
            hours_text = ", ".join(_format_hour_label(int(hour)) for hour in preferred_hours)
            lines.append(f"⏱️ 优先时段：{hours_text}")
        if preferred_days:
            days_text = ", ".join(_format_day_label(int(day)) for day in preferred_days)
            lines.append(f"📅 优先天数：{days_text}")
        if booking_users:
            lines.append(f"👥 指定账号：{', '.join(str(u) for u in booking_users)}")
        if excluded_users:
            lines.append(f"🚫 排除账号：{', '.join(str(u) for u in excluded_users)}")

        lines.append("\n可用时间段：")
        for slot in slots:
            lines.append(f"• {_format_monitor_slot_line(slot)}")

        return "\n".join(lines)


# Global notification instance -------------------------------------------------
_notification_service: Optional[NotificationService] = None


def get_notification_service() -> NotificationService:
    """Return a singleton NotificationService instance."""
    global _notification_service
    if _notification_service is None:
        _notification_service = NotificationService(
            bot_http_url=getattr(CFG, "BOT_HTTP_URL", "http://127.0.0.1:3000"),
            access_token=getattr(CFG, "BOT_ACCESS_TOKEN", None),
            default_delay=getattr(CFG, "NOTIFICATION_DELAY", 0),
            retry_count=getattr(CFG, "NOTIFICATION_RETRY_COUNT", 3),
            retry_delay=getattr(CFG, "NOTIFICATION_RETRY_DELAY", 5),
            template=getattr(CFG, "NOTIFICATION_TEMPLATE", None),
        )
    return _notification_service


async def send_order_notification(
    *,
    order_id: str,
    user_nickname: str,
    venue_name: str,
    field_type_name: str,
    date: str,
    start_time: str,
    end_time: str,
    success: bool,
    message: str,
    target_groups: Optional[Sequence[str]] = None,
    target_users: Optional[Sequence[str]] = None,
) -> bool:
    """Convenience wrapper for sending an order notification."""
    notification = OrderNotification(
        order_id=order_id,
        user_nickname=user_nickname,
        venue_name=venue_name,
        field_type_name=field_type_name,
        date=date,
        start_time=start_time,
        end_time=end_time,
        success=success,
        message=message,
    )
    service = get_notification_service()
    return await service.send_order_success_notification(
        notification,
        target_groups=target_groups,
        target_users=target_users,
    )


async def send_monitor_notification(
    *,
    monitor_id: str,
    venue_name: Optional[str],
    field_type_name: Optional[str],
    slots: List[Dict[str, Any]],
    auto_book: bool,
    target_groups: Optional[Sequence[str]] = None,
    target_users: Optional[Sequence[str]] = None,
    preferred_hours: Optional[Sequence[int]] = None,
    preferred_days: Optional[Sequence[int]] = None,
    booking_users: Optional[Sequence[str]] = None,
    excluded_users: Optional[Sequence[str]] = None,
) -> bool:
    """Send a monitor availability notification."""
    service = get_notification_service()
    return await service.send_monitor_slots_notification(
        monitor_id=monitor_id,
        venue_name=venue_name,
        field_type_name=field_type_name,
        slots=slots,
        auto_book=auto_book,
        target_groups=target_groups,
        target_users=target_users,
        preferred_hours=preferred_hours,
        preferred_days=preferred_days,
        booking_users=booking_users,
        excluded_users=excluded_users,
    )
