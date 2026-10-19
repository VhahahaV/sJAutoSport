"""
下单模块 - 处理体育场馆预订的下单逻辑

包含加密、单次下单确认及明确的错误反馈
"""

import json
import time
import base64
import secrets
import string
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple
from dataclasses import dataclass

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

        resolved: Optional[FieldType] = None
        try:
            if preset.venue_id:
                detail = self.api.get_venue_detail(preset.venue_id)
                field_types = self.api.list_field_types(detail)
                for item in field_types:
                    # 优先使用ID匹配，其次名称匹配
                    if preset.field_type_id and item.id == preset.field_type_id:
                        resolved = item
                        break
                    if (
                        resolved is None
                        and preset.field_type_name
                        and item.name == preset.field_type_name
                    ):
                        resolved = item
        except Exception:
            resolved = None

        if resolved is None:
            fallback_raw: Dict[str, Any] = {}
            category = preset.field_type_code
            if category:
                fallback_raw["code"] = category
                fallback_raw["bizMotionType"] = category
                fallback_raw["motionType"] = category
                fallback_raw["motionId"] = category
            if preset.field_type_id:
                fallback_raw.setdefault("fieldTypeId", preset.field_type_id)
            if preset.field_type_name:
                fallback_raw.setdefault("fieldTypeName", preset.field_type_name)

            fallback_id = preset.field_type_id or preset.field_type_name
            if fallback_id:
                resolved = FieldType(
                    id=str(fallback_id),
                    name=preset.field_type_name or str(fallback_id),
                    category=category,
                    raw=fallback_raw,
                )

        if resolved:
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
        return {
            "venTypeId": preset.field_type_id,
            "venueId": preset.venue_id,
            "fieldType": preset.field_type_name,
            "returnUrl": self.return_url,
            "scheduleDate": date,
            "week": "0",  # 固定值
            "spaces": [{
                "venuePrice": str(int(slot.price or 0)),
                "count": 1,
                "sign": slot.sign or "",
                "status": 1,
                "scheduleTime": f"{actual_start}-{actual_end}",
                "subSitename": slot.field_name or "",
                "subSiteId": slot.sub_site_id or "",
                "tensity": "1",
                "venueNum": 1
            }],
            "tenSity": "紧张"  # 固定值
        }
    
    def _send_order_request(self, payload: Dict) -> Tuple[bool, str, Optional[Dict]]:
        """发送下单请求"""
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
            
            # 发送请求
            url = f"{self.api.base_url}{self.api.endpoints.order_confirm}"
            # 发送加密的载荷作为原始数据
            # 与单用户版本保持一致：发送原始加密字符串到 body
            response = self.api.client.post(
                url,
                data=encrypted_body,
                headers=headers,
                timeout=self.request_timeout
            )
            
            # 解析响应
            try:
                result = response.json()
            except Exception as e:
                return False, f"解析响应失败: {e}", None
            
            # 检查HTTP状态码
            if response.status_code != 200:
                text_preview = response.text[:400]
                error_msg = result.get('msg', result.get('message', text_preview if text_preview else f'HTTP {response.status_code}')) if isinstance(result, dict) else text_preview
                return False, f"HTTP错误 {response.status_code}: {error_msg}", result
            
            # 检查业务逻辑错误
            if isinstance(result, dict):
                code = result.get('code')
                msg = result.get('msg', result.get('message', ''))

                # 统一规范化消息
                if code in (401, "401"):
                    return False, f"登录超时: {msg}", result
                if code in (403, "403"):
                    return False, f"权限不足: {msg}", result
                if code in (404, "404"):
                    return False, f"资源不存在: {msg}", result
                if code in (500, "500"):
                    return False, f"服务器错误: {msg}", result
                if code not in (None, 0, "0"):
                    return False, f"业务错误 {code}: {msg}", result
                if msg and any(keyword in msg for keyword in ['失败', '错误', '超时', '登录', '权限', '不存在', '已满', '不可用', '非法']):
                    return False, f"业务错误: {msg}", result
            
            # 检查是否有订单ID（成功下单的标识）
            if not isinstance(result, dict):
                return False, "下单响应格式异常，未获得有效订单号", None
            order_id = result.get("orderId") or result.get("order_id") or result.get("id") or result.get("data")
            if isinstance(order_id, dict):
                order_id = order_id.get("orderId") or order_id.get("order_id") or order_id.get("id")
            if not isinstance(order_id, (str, int)) or isinstance(order_id, bool) or not str(order_id).strip():
                return False, "下单响应未返回有效订单号", result
            order_id = str(order_id)
            return True, f"下单成功，订单ID: {order_id}", {**result, "orderId": order_id}
                
        except Exception as e:
            return False, f"请求异常: {e}", None
    
    def place_order(self, slot: Slot, preset: PresetOption, date: str,
                    actual_start: str, actual_end: str) -> OrderResult:
        """Submit exactly once; never switch slots or retry an uncertain result."""
        payload = self._build_order_payload(slot, preset, date, actual_start, actual_end)
        success, message, response = self._send_order_request(payload)
        if not success:
            return OrderResult(False, f"{message}；请先查询订单核对结果，再决定是否重新提交", raw_response=response)
        return OrderResult(True, message, order_id=response["orderId"], raw_response=response)

    def place_order_by_preset(self, preset_index: int, date: str, 
                             start_time: str = "21:00", 
                             end_time: str = "22:00") -> OrderResult:
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
                message=f"未找到序号为 {preset_index} 的预设配置"
            )
        
        # 查询可用时间段
        try:
            field_type_info = self._get_field_type_info(preset)
            
            # 获取日期token
            date_tokens = self.api.list_available_dates(preset.venue_id, preset.field_type_id)
            date_token = None
            for date_str_value, token in date_tokens:
                if date_str_value == date:
                    date_token = token
                    break
            if not date_token and field_type_info and field_type_info.raw:
                for key in ("dateId", "dateToken"):
                    raw_value = field_type_info.raw.get(key)
                    if raw_value:
                        date_token = str(raw_value)
                        break
            
            slots = self.api.query_slots(
                venue_id=preset.venue_id,
                field_type_id=preset.field_type_id,
                date_str=date,
                date_token=date_token,
                original_field_type=field_type_info
            )
        except Exception as e:
            return OrderResult(
                success=False,
                message=f"查询时间段失败: {e}"
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
                message=f"未找到可用的时间段 {start_time}-{end_time}"
            )
        
        # 执行下单
        return self.place_order(target_slot, preset, date, start_time, end_time)
