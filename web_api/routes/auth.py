from __future__ import annotations

from base64 import b64encode
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from sja_booking import service

router = APIRouter(prefix="/auth", tags=["auth"])


def _guess_mime(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"GIF8"):
        return "image/gif"
    return "application/octet-stream"


def _encode_captcha(payload: Dict[str, Any]) -> Dict[str, Any]:
    image = payload.get("captcha_image")
    if isinstance(image, (bytes, bytearray)):
        payload["captcha_image"] = b64encode(image).decode("ascii")
        payload.setdefault("captcha_mime", _guess_mime(image))
    return payload


class LoginStartPayload(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    nickname: Optional[str] = None
    user_id: Optional[str] = None


class LoginVerifyPayload(BaseModel):
    session_id: str
    code: str


class LoginCancelPayload(BaseModel):
    session_id: str


@router.post("/login/start")
async def start_login(payload: LoginStartPayload) -> Dict[str, Any]:
    """Start login workflow and optionally return captcha."""
    result = await service.start_login_session(
        user_id=payload.user_id,
        username=payload.username,
        password=payload.password,
        nickname=payload.nickname,
    )
    return _encode_captcha(result)


@router.post("/login/verify")
async def verify_login(payload: LoginVerifyPayload) -> Dict[str, Any]:
    """Submit captcha code to continue login workflow."""
    code = payload.code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="验证码不能为空")

    result = await service.submit_login_session_code(payload.session_id, code)
    return _encode_captcha(result)


@router.post("/login/cancel")
async def cancel_login(payload: LoginCancelPayload) -> Dict[str, Any]:
    """Cancel an in-flight login session."""
    return await service.cancel_login_session(payload.session_id)
