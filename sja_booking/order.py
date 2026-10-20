"""
下单模块 - 处理体育场馆预订的下单逻辑

包含加密、单次下单确认及明确的错误反馈
"""

import json
import time
import base64
import secrets
import string
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
from dataclasses import dataclass, field
import httpx

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5

from .models import FieldType, Slot, PresetOption
from .api import SportsAPI


@dataclass
class OrderResult:
    """下单结果"""
    success: bool
    message: str
    order_id: Optional[str] = None
    raw_response: Optional[Dict] = None
    status: str = ""
    request_id: Optional[str] = None
    timings_ms: Dict[str, float] = field(default_factory=dict)
    attempts: list = field(default_factory=list)
    response_info: Dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.status:
            self.status = "success" if self.success else "unknown"


def _next_hour(time_text: str, duration_hours: int = 1) -> str:
    """Return time string duration_hours after time_text (HH:MM)."""
    try:
        base = datetime.strptime(time_text, "%H:%M")
    except ValueError:
        return time_text
    result = base + timedelta(hours=duration_hours)
    return result.strftime("%H:%M")


class OrderManager:
    """下单管理器"""
    
    def __init__(self, api: SportsAPI, encryption_config: Dict, *, request_timeout: float = 10.0):
        self.api = api
        self.encryption_config = encryption_config
        self.rsa_public_key = encryption_config["rsa_public_key"]
        self.return_url = encryption_config["return_url"]
        try:
            self.request_timeout = max(1.0, float(request_timeout))
        except Exception:
            self.request_timeout = 10.0
        self._field_type_cache: Dict[str, FieldType] = {}

    def _field_type_cache_key(self, preset: PresetOption) -> str:
        """缓存键：同一场馆+项目复用 FieldType 详情"""
        venue_part = preset.venue_id or ""
        field_part = preset.field_type_id or preset.field_type_name or ""
        return f"{venue_part}:{field_part}"

    def _get_field_type_info(self, preset: PresetOption) -> Optional[FieldType]:
        """获取带原始数据的 FieldType，用于补齐查询所需参数"""
        cache_key = self._field_type_cache_key(preset)
        if cache_key in self._field_type_cache:
            return self._field_type_cache[cache_key]

        detail = self.api.get_venue_detail(preset.venue_id)
        resolved = next((item for item in self.api.list_field_types(detail) if item.id == preset.field_type_id), None)
        if resolved is None:
            raise ValueError("场馆未返回该运动项目的预约配置")
        self._field_type_cache[cache_key] = resolved
        return resolved

    def _generate_aes_key(self) -> str:
        """生成16位AES密钥"""
        alphabet = string.ascii_uppercase + string.digits
        return ''.join(secrets.choice(alphabet) for _ in range(16))
    
    def _aes_encrypt(self, key: str, plaintext: str) -> str:
        """AES-128-ECB加密"""
        key_bytes = key.encode('utf-8')
        cipher = AES.new(key_bytes, AES.MODE_ECB)
        padded_data = pad(plaintext.encode('utf-8'), 16)
        encrypted = cipher.encrypt(padded_data)
        return base64.b64encode(encrypted).decode()
    
    def _rsa_encrypt(self, data: str) -> str:
        """RSA加密"""
        rsa_key = RSA.import_key(self.rsa_public_key)
        cipher = PKCS1_v1_5.new(rsa_key)
        encrypted = cipher.encrypt(data.encode('utf-8'))
        return base64.b64encode(encrypted).decode()
    
    def _build_order_payload(self, slot: Slot, preset: PresetOption, date: str, actual_start: str, actual_end: str) -> Dict:
        """构建下单请求载荷"""
        field_type = self._field_type_cache.get(self._field_type_cache_key(preset))
        tension = (field_type.raw if field_type else {}).get("tension")
        tension_label = {"0": "正常", "1": "紧张", "2": "很紧张", "3": "非常紧张", "4": "很紧张(签退)"}.get(str(tension))
        return {
            "venTypeId": preset.field_type_id,
            "venueId": preset.venue_id,
            "fieldType": preset.field_type_name,
            "returnUrl": self.return_url,
            "scheduleDate": date,
            "week": str((datetime.strptime(date, "%Y-%m-%d").weekday() + 1) % 7),
            "spaces": [{
                "venuePrice": format(slot.price or 0, ".12g"),
                "count": 1,
                "sign": slot.sign or "",
                "status": 1,
                "scheduleTime": f"{actual_start}-{actual_end}",
                "subSitename": slot.field_name or "",
                "subSiteId": slot.sub_site_id or "",
                "tensity": slot.raw.get("field_detail_status"),
                "venueNum": 1
            }],
            "tenSity": tension_label,
        }
    
    def _send_order_request(self, payload: Dict) -> OrderResult:
        """Send once and distinguish a rejected request from an uncertain outcome."""
        started = time.perf_counter()
        try:
            # 生成加密参数
            aes_key = self._generate_aes_key()
            timestamp = str(int(time.time() * 1000))
            
            # 加密载荷
            plain_json = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
            encrypted_body = self._aes_encrypt(aes_key, plain_json)
            
            # 加密密钥和时间戳
            encrypted_key = self._rsa_encrypt(aes_key)
            encrypted_timestamp = self._rsa_encrypt(timestamp)
            # 构建请求头
            # Use the current verified session for the encrypted confirmation.
            account = self.api.auth.user
            cookie_str = account.cookie if account and account.cookie else ""
            if not cookie_str:
                cookies = self.api.client.cookies
                cookie_parts = []
                for name, value in cookies.items():
                    cookie_parts.append(f"{name}={value}")
                cookie_str = "; ".join(cookie_parts)
            
            headers = {
                "Accept": "application/json, text/plain, */*",
                # 与单用户版本保持一致：application/json;charset=UTF-8
                "Content-Type": "application/json;charset=UTF-8",
                "sid": encrypted_key,
                "tim": encrypted_timestamp,
                "Cookie": cookie_str,
                "Origin": "https://sports.sjtu.edu.cn",
                "Referer": "https://sports.sjtu.edu.cn/pc/",
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            }
            
        except (ValueError, TypeError, KeyError):
            return OrderResult(False, "下单参数或加密配置无效，请检查配置", status="not_submitted")

        url = f"{self.api.base_url}{self.api.endpoints.order_confirm}"
        self.api.timings_ms["encryption"] = round((time.perf_counter() - started) * 1000, 2)
        started = time.perf_counter()
        try:
            response = self.api.client.post(
                url,
                data=encrypted_body,
                headers=headers,
                timeout=self.request_timeout
            )
            
        except httpx.HTTPError as exc:
            return OrderResult(False, "下单连接异常，服务端是否已创建订单尚不确定", status="unknown",
                               response_info={"transport_error": type(exc).__name__})
        finally:
            self.api.timings_ms["confirmation"] = round((time.perf_counter() - started) * 1000, 2)
        try:
            result = response.json()
        except ValueError:
            result = None
        info = self._response_info(response.status_code, result, payload)

        def outcome(success, message, order_id=None, raw_response=None, *, status):
            return OrderResult(success, message, order_id, raw_response, status=status, response_info=info)

        if response.status_code == 401:
            return outcome(False, "下单需要重新登录", status="login_required")
        if response.status_code in (403, 429):
            return outcome(False, f"下单被拒绝（HTTP {response.status_code}），请稍后核对", status="rejected")
        if response.status_code != 200:
            return outcome(False, f"下单响应异常（HTTP {response.status_code}），结果待核对", status="unknown")
        if not isinstance(result, dict):
            return outcome(False, "下单响应格式异常，结果待核对", status="unknown")
        code = result.get("code")
        msg = info.get("server_message", "")
        if code in (1002, "1002"):
            return outcome(False, "预约需要人工验证码，请在官方预约页面完成验证",
                               raw_response=result, status="challenge_required")
        if code in (401, "401"):
            return outcome(False, "下单需要重新登录", raw_response=result, status="login_required")
        if code in (500, "500"):
            detail = f"：{msg}" if msg else ""
            return outcome(False, f"校园服务返回业务码 500{detail}；下单结果待核对",
                           raw_response=result, status="unknown")
        if code not in (None, 0, "0"):
            return outcome(False, f"预约被拒绝（{info.get('business_code')}）：{msg}",
                           raw_response=result, status="rejected")
        order_id = result.get("orderId") or result.get("order_id") or result.get("id") or result.get("data")
        if isinstance(order_id, dict):
            order_id = order_id.get("orderId") or order_id.get("order_id") or order_id.get("id")
        if not isinstance(order_id, (str, int)) or isinstance(order_id, bool) or not str(order_id).strip():
            return outcome(False, "下单响应未返回有效订单号，结果待核对", raw_response=result, status="unknown")
        order_id = str(order_id)
        return outcome(True, f"下单成功，订单ID: {order_id}", order_id, result, status="success")

    def _response_info(self, http_status, body, payload):
        """Retain bounded response evidence without persisting arbitrary server data."""
        info = {"http_status": http_status, "received_at": datetime.now(timezone.utc).isoformat()}
        if not isinstance(body, dict):
            return info
        code = body.get("code")
        if type(code) is int or (isinstance(code, str) and re.fullmatch(r"-?\d{1,9}", code)):
            info["business_code"] = code
        message = body.get("msg") or body.get("message")
        if not isinstance(message, str):
            return info
        private_values = []
        account = self.api.auth.user
        if account:
            private_values.extend(getattr(account, key, None)
                                  for key in ("username", "nickname", "password", "cookie", "token"))
        private_values.extend(self.api.client.cookies.values())
        private_values.extend(space.get("sign") for space in payload.get("spaces", []) if isinstance(space, dict))
        private_values.extend(payload.get(key) for key in ("dateId", "sign", "sid", "tim", "tid"))
        for value in sorted({v for v in private_values if isinstance(v, str) and v}, key=len, reverse=True):
            message = message.replace(value, "[REDACTED]")
        message = re.sub(r"(?i)\b(?:cookie|authorization|password|token|sign|dateId|sid|tim|tid)\s*[:=]\s*\S+",
                         "[REDACTED]", message)
        message = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|\d{6,}|[A-Za-z0-9_+/=-]{24,}",
                         "[REDACTED]", message)
        info["server_message"] = " ".join(message.split())[:500]
        return info
    
    def place_order(self, slot: Slot, preset: PresetOption, date: str,
                    actual_start: str, actual_end: str) -> OrderResult:
        """Submit exactly once; never switch slots or retry an uncertain result."""
        if not slot.sign or not slot.sub_site_id or not slot.field_name:
            return OrderResult(False, "场次缺少有效预约信息，请重新查询", status="not_submitted")
        if not slot.available or slot.price is None or not math.isfinite(slot.price) or slot.price < 0:
            return OrderResult(False, "场次不可预约或价格信息无效，请重新查询", status="not_submitted")
        payload = self._build_order_payload(slot, preset, date, actual_start, actual_end)
        result = self._send_order_request(payload)
        result.timings_ms = dict(self.api.timings_ms)
        if result.status == "unknown":
            result.message += "；请先查询订单核对结果，核对前暂停其他预约"
        return result

    def place_order_by_preset(self, preset_index: int, date: str, 
                             start_time: str = "21:00", 
                             end_time: str = "22:00", *, still_valid=lambda: True) -> OrderResult:
        """
        通过预设序号下单
        
        Args:
            preset_index: 预设序号
            date: 预订日期 (YYYY-MM-DD)
            start_time: 开始时间 (HH:MM)
            end_time: 结束时间 (HH:MM)
            
        Returns:
            OrderResult: 下单结果
        """
        # 查找预设配置
        preset = None
        for p in self.api.preset_targets:
            if p.index == preset_index:
                preset = p
                break
        
        if not preset:
            return OrderResult(
                success=False,
                message=f"未找到序号为 {preset_index} 的预设配置", status="not_submitted"
            )
        
        # 查询可用时间段
        try:
            slots = self.query_day(preset, date)
        except Exception as e:
            return OrderResult(
                success=False,
                message=f"查询时间段失败: {type(e).__name__}", status="not_submitted"
            )
        
        # 查找匹配的时间段
        def _normalize(label: Optional[str]) -> Optional[str]:
            if not label:
                return None
            label = str(label).strip()
            if not label or label in {"-", "--", "?", "null", "None"}:
                return None
            if ":" in label:
                parts = label.split(":", 1)
                if len(parts) == 2 and parts[0].isdigit():
                    try:
                        hour = int(parts[0]) % 24
                        minute = int(parts[1])
                        return f"{hour:02d}:{minute:02d}"
                    except (TypeError, ValueError):
                        return None
                return label
            if label.startswith("slot-") and label[5:].isdigit():
                hour = (7 + int(label[5:])) % 24
                return f"{hour:02d}:00"
            if label.isdigit():
                hour = int(label) % 24
                return f"{hour:02d}:00"
            return None

        normalized_start = _normalize(start_time)
        normalized_end = _normalize(end_time)

        target_slot = None
        for slot in slots:
            slot_start = _normalize(slot.start)
            slot_end = _normalize(slot.end) or (slot_start and _next_hour(slot_start, 1))
            if (
                slot.available
                and slot_start == normalized_start
                and (normalized_end is None or slot_end == normalized_end)
            ):
                target_slot = slot
                break

        if not target_slot:
            return OrderResult(
                success=False,
                message=f"未找到可用的时间段 {start_time}-{end_time}", status="not_submitted"
            )
        
        # 执行下单
        if not still_valid():
            return OrderResult(False, "登录会话已变化，本次未下单，请重新查询", status="not_submitted")
        return self.place_order(target_slot, preset, date, start_time, end_time)

    def query_day(self, preset: PresetOption, date: str):
        """Keep metadata in the core, but always get fresh date and slot tokens."""
        field_type = self._get_field_type_info(preset)
        days = self.api.list_date_availability(preset.venue_id, preset.field_type_id)
        day = next((entry for entry in days if entry.date == date), None)
        if day is None or not day.open:
            return []
        if not day.token:
            raise ValueError("日期缺少预约凭据，请刷新日期列表")
        return self.api.query_slots(preset.venue_id, preset.field_type_id, date,
                                    date_token=day.token, original_field_type=field_type)

    def place_candidates(self, preset, date, slots, preferences, *, max_attempts, max_price,
                         continue_on_codes, still_valid):
        """One query result, ordered candidates, and at most one successful order."""
        attempted, seen = [], set()
        result = OrderResult(False, "候选时段内没有符合价格上限的可用场地", status="not_submitted")
        for preference in preferences:
            for slot in slots:
                if (slot.slot_id in seen or not slot.available or slot.price is None or slot.price > max_price
                        or slot.start != preference["start_time"] or slot.end != preference["end_time"]
                        or (preference.get("candidate_id") and preference["candidate_id"] != slot.slot_id)):
                    continue
                seen.add(slot.slot_id)
                if not still_valid():
                    result = OrderResult(False, "查询已过期或登录已变化，已停止候选预约", status="not_submitted")
                    result.attempts = attempted
                    return result
                result = self.place_order(slot, preset, date, slot.start, slot.end)
                code = (result.raw_response or {}).get("code")
                attempted.append({"candidate_id": slot.slot_id, "start_time": slot.start, "end_time": slot.end,
                                  "price": slot.price, "status": result.status, "code": code,
                                  "response_info": dict(result.response_info),
                                  "timings_ms": dict(result.timings_ms)})
                result.attempts = list(attempted)
                # Never infer safety from timeout, HTTP failure, captcha, authentication,
                # or an unrecognized business code. Defaults permit no POST retries.
                if (result.success or result.status != "rejected" or not result.raw_response
                        or str(code) not in {str(c) for c in continue_on_codes}
                        or len(attempted) >= max_attempts):
                    return result
        return result
