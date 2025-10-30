"""
下单模块 - 处理体育场馆预订的下单逻辑

包含加密、下单确认、错误重试等功能
"""

import json
import time
import base64
import random
import string
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass

import httpx
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5

from .models import FieldType, Slot, OrderIntent, PresetOption
from .api import SportsAPI


@dataclass
class OrderResult:
    """下单结果"""
    success: bool
    message: str
    order_id: Optional[str] = None
    raw_response: Optional[Dict] = None


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
        return ''.join(random.choice(alphabet) for _ in range(16))
    
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
            # 统一从当前 httpx 客户端获取 Cookie（多用户模式下与当前用户绑定），并确保含有 JSESSIONID
            # 完全对齐单用户版本：若配置中提供了 cookie，则优先使用（常见为 "JSESSIONID=..."）
            cookie_str = ""
            try:
                # 优先使用当前切换到的用户
                if getattr(self.api, "_current_user", None) and self.api._current_user.cookie:
                    cookie_str = self.api._current_user.cookie
                elif getattr(self.api, "auth", None) and getattr(self.api.auth, "users", None):
                    user0 = self.api.auth.users[0]
                    if user0 and user0.cookie:
                        cookie_str = user0.cookie
            except Exception:
                cookie_str = ""
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
            order_id = result.get('orderId') or result.get('order_id') or result.get('id') or result.get('data')
            if not order_id:
                return False, f"下单失败: 未返回订单ID - {result}", result
            
            return True, f"下单成功，订单ID: {order_id}", result
                
        except Exception as e:
            return False, f"请求异常: {e}", None
    
    def _refresh_slot_data(self, preset: PresetOption, date: str) -> Optional[Slot]:
        """刷新时间段数据，获取最新的sign和sub_site_id"""
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
            
            # 查询可用时间段
            slots = self.api.query_slots(
                venue_id=preset.venue_id,
                field_type_id=preset.field_type_id,
                date_str=date,
                date_token=date_token,
                original_field_type=field_type_info
            )
            
            if slots:
                return slots[0]  # 返回第一个可用时间段
            return None
        except Exception as e:
            print(f"刷新时间段数据失败: {e}")
            return None
    
    def place_order(self, slot: Slot, preset: PresetOption, date: str, 
                   actual_start: str, actual_end: str, max_retries: int = 3) -> OrderResult:
        """
        下单
        
        Args:
            slot: 要预订的时间段
            preset: 场馆预设配置
            date: 预订日期
            max_retries: 最大重试次数
            
        Returns:
            OrderResult: 下单结果
        """
        current_slot = slot
        backoff_base = 2.0
        for attempt in range(max_retries):
            print(f"下单尝试 {attempt + 1}/{max_retries}")
            
            # 构建下单载荷
            payload = self._build_order_payload(current_slot, preset, date, actual_start, actual_end)
            
            # 发送下单请求（加密 ConfirmOrder 流程）
            success, message, response = self._send_order_request(payload)
            
            if success:
                return OrderResult(
                    success=True,
                    message=message,
                    order_id=response.get("orderId") if response else None,
                    raw_response=response
                )
            
            print(f"下单失败: {message}")

            # 回退策略：尝试使用简单提交接口 order_immediately（与旧版一致）
            try:
                # 从 slot.raw 中尽可能获取 orderId；否则退化为 slot.slot_id
                order_identifier = None
                if isinstance(current_slot.raw, dict):
                    order_identifier = current_slot.raw.get("orderId") or current_slot.raw.get("id")
                if not order_identifier:
                    order_identifier = current_slot.slot_id
                if order_identifier:
                    intent = OrderIntent(
                        venue_id=preset.venue_id,
                        field_type_id=preset.field_type_id,
                        slot_id=current_slot.slot_id,
                        date=date,
                        order_id=str(order_identifier),
                        payload=current_slot.raw,
                    )
                    resp = self.api.order_immediately(intent)
                    if isinstance(resp, dict):
                        code = resp.get("code")
                        msg = resp.get("msg") or resp.get("message") or ""
                        if code in (0, "0") and not any(k in str(msg) for k in ["非法", "失败", "错误"]):
                            return OrderResult(
                                success=True,
                                message=msg or "下单成功（简易提交）",
                                order_id=resp.get("orderId") or resp.get("data") or str(order_identifier),
                                raw_response=resp,
                            )
            except Exception as _:
                # 忽略回退异常，进入刷新逻辑
                pass
            
            # 如果不是最后一次尝试，刷新时间段数据
            if attempt < max_retries - 1:
                print("刷新时间段数据...")
                refreshed_slot = self._refresh_slot_data(preset, date)
                if refreshed_slot:
                    current_slot = refreshed_slot
                    print("时间段数据已刷新，准备重试...")
                else:
                    print("无法刷新时间段数据，使用原始数据重试...")
                delay_seconds = backoff_base + attempt * 2.0 + random.uniform(0.3, 0.8)
                print(f"等待 {delay_seconds:.1f} 秒后再次尝试...")
                time.sleep(delay_seconds)
        
        return OrderResult(
            success=False,
            message=f"下单失败，已重试{max_retries}次",
            raw_response=None
        )
    
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
        target_slot = None
        for i, slot in enumerate(slots):
            # 根据slot索引计算实际时间 - 使用与monitor.py相同的逻辑
            actual_start_hour = (7 + i) % 24  # slot-0对应07:00
            actual_start = f"{actual_start_hour:02d}:00"
            actual_end_hour = (actual_start_hour + 1) % 24
            actual_end = f"{actual_end_hour:02d}:00"
            
            # 使用计算出的实际时间进行匹配
            if actual_start == start_time and actual_end == end_time and slot.available:
                target_slot = slot
                break
        
        if not target_slot:
            return OrderResult(
                success=False,
                message=f"未找到可用的时间段 {start_time}-{end_time}"
            )
        
        # 执行下单
        return self.place_order(target_slot, preset, date, start_time, end_time)
