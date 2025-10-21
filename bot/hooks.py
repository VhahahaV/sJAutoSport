"""
自定义消息预处理器与调试工具。
"""

from __future__ import annotations

from typing import Optional

from nonebot import logger
from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import MessageEvent, Message, MessageSegment
from nonebot.message import (
    IgnoredException,
    event_preprocessor,
    run_preprocessor,
)
from nonebot.params import CommandStart
from nonebot.typing import T_State

_ALLOW_EMPTY_PREFIX_FLAG = "_sja_allow_empty_prefix"


def _strip_leading_text_segment(message: Message, index: int = 0) -> None:
    """去掉指定文本段的前置空白，方便命令解析。"""
    if not message or index >= len(message):
        return
    segment = message[index]
    if segment.type != "text":
        return
    original = segment.data.get("text", "")
    stripped = original.lstrip()
    if stripped == original and original:
        return
    if not stripped:
        message.pop(index)
    else:
        message[index] = MessageSegment.text(stripped)


@event_preprocessor
async def preprocess_mentions(
    bot: Bot,
    event: Event,
    state: T_State,
) -> None:
    """在 matcher 匹配前处理 @ 提及的命令形式。"""
    if not isinstance(event, MessageEvent):
        return

    message = event.get_message()
    if not message:
        return

    for idx, segment in enumerate(message):
        if segment.type != "at":
            continue
        if segment.data.get("qq") not in {str(bot.self_id), bot.self_id}:
            continue

        original_plain = event.original_message.extract_plain_text()
        message.pop(idx)
        while message and message[0].type == "text" and not message[0].data.get("text", "").strip():
            message.pop(0)
        if message:
            _strip_leading_text_segment(message, 0)
        state[_ALLOW_EMPTY_PREFIX_FLAG] = True
        if hasattr(event, "to_me"):
            event.to_me = True

        logger.debug(
            f"检测到 @ 机器人消息，移除前缀后重新解析: user={event.get_user_id()} raw='{original_plain}'"
        )
        break


@run_preprocessor
async def guard_empty_prefix(
    event: Event,
    state: T_State,
    command_start: Optional[str] = CommandStart(),
) -> None:
    """只有在明确 @ 机器人时才允许无前缀命令继续执行。"""
    if not isinstance(event, MessageEvent):
        return

    if command_start:
        logger.debug(
            f"检测到命令前缀 '{command_start}' (user={event.get_user_id()}, message='{event.get_message().extract_plain_text()}')"
        )
        return

    if state.get(_ALLOW_EMPTY_PREFIX_FLAG):
        logger.debug(
            f"允许无前缀命令: user={event.get_user_id()} message='{event.get_message().extract_plain_text()}'"
        )
        return

    logger.debug(
        f"忽略未提及机器人的无前缀消息: user={event.get_user_id()} message='{event.get_message().extract_plain_text()}'"
    )
    raise IgnoredException("Command without prefix ignored")
