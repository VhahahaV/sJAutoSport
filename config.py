"""Runtime configuration for the SJTU Sports CLI.

Configuration is loaded from environment variables so the same codebase can
run in different environments (development, staging, production) without
modifying source files.  See README/Docs for variable descriptions."""

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from urllib.parse import quote_plus

from sja_booking.models import AuthConfig, BookingTarget, EndpointSet, MonitorPlan, PresetOption, SchedulePlan, UserAuth


ENVIRONMENT = os.getenv("SJA_ENV", "development").lower()
CONFIG_ROOT = Path(os.getenv("SJA_CONFIG_ROOT", Path(__file__).resolve().parent / "data")).resolve()
CONFIG_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("SJABOT_CREDENTIAL_STORE", str(CONFIG_ROOT / "credentials.json"))


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _split_env_list(name: str) -> List[str]:
    value = os.getenv(name, "")
    if not value:
        return []
    return [item.strip() for item in value.replace(";", ",").split(",") if item.strip()]


def _load_json_from_env(env_key: str) -> Optional[Any]:
    raw = os.getenv(env_key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError(f"环境变量 {env_key} 不是有效的 JSON") from None


def _load_json_from_file(path: Optional[str]) -> Optional[Any]:
    if not path:
        return None
    file_path = Path(path).expanduser().resolve()
    if not file_path.exists():
        raise RuntimeError(f"配置文件 {file_path} 不存在")
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"配置文件 {file_path} 不是有效的 JSON: {exc}") from exc


def _load_users() -> List[UserAuth]:
    data = _load_json_from_env("SJA_USERS_JSON")
    if data is None:
        data = _load_json_from_file(os.getenv("SJA_USERS_FILE"))

    users: List[UserAuth] = []
    if isinstance(data, list):
        for entry in data:
            if not isinstance(entry, dict):
                continue
            users.append(
                UserAuth(
                    nickname=entry.get("nickname"),
                    username=entry.get("username"),
                    password=entry.get("password"),
                    token=entry.get("token"),
                )
            )

    if users:
        return users

    # 开发环境提供示例用户，生产环境默认空列表
    if ENVIRONMENT == "development":
        sample = [
            {
                "nickname": os.getenv("SJA_USER0_NICK", "sample"),
                "username": os.getenv("SJA_USER0_USERNAME", "sample@example.com"),
                "password": os.getenv("SJA_USER0_PASSWORD"),
            }
        ]
        return [
            UserAuth(
                nickname=item.get("nickname"),
                username=item.get("username"),
                password=item.get("password"),
            )
            for item in sample
            if item.get("username")
        ]

    return []


def _load_notification_targets(default: Dict[str, List[str]]) -> Dict[str, List[str]]:
    groups = _split_env_list("SJA_NOTIFICATION_GROUPS")
    users = _split_env_list("SJA_NOTIFICATION_USERS")
    if groups:
        default = {**default, "groups": groups}
    if users:
        default = {**default, "users": users}
    return default


def _load_target(default_target: BookingTarget) -> BookingTarget:
    override = _load_json_from_env("SJA_TARGET_JSON")
    if not isinstance(override, dict):
        file_override = _load_json_from_file(os.getenv("SJA_TARGET_FILE"))
        if isinstance(file_override, dict):
            override = file_override
    if isinstance(override, dict):
        payload = default_target.__dict__.copy()
        payload.update(override)
        return BookingTarget(**payload)
    return default_target


def _load_presets(default_presets: List[PresetOption]) -> List[PresetOption]:
    override = _load_json_from_env("SJA_PRESETS_JSON")
    if override is None:
        override = _load_json_from_file(os.getenv("SJA_PRESETS_FILE"))
    presets: List[PresetOption] = []
    if isinstance(override, list):
        for entry in override:
            if not isinstance(entry, dict):
                continue
            try:
                presets.append(
                    PresetOption(
                        index=int(entry["index"]),
                        venue_id=str(entry["venue_id"]),
                        venue_name=str(entry["venue_name"]),
                        field_type_id=str(entry["field_type_id"]),
                        field_type_name=str(entry["field_type_name"]),
                        field_type_code=entry.get("field_type_code"),
                    )
                )
            except (KeyError, ValueError):
                continue
    if presets:
        return presets
    return default_presets


def _parse_int_list(name: str) -> Optional[List[int]]:
    values = _split_env_list(name)
    if not values:
        return None
    result: List[int] = []
    for item in values:
        try:
            result.append(int(item))
        except ValueError:
            continue
    return result or None

# Base address for all API requests. Most SJTU deployments respond on this host.
BASE_URL = os.getenv("SJA_BASE_URL", "https://sports.sjtu.edu.cn")

# 多用户认证配置 - 用户基础信息从环境/外部 JSON 文件加载
AUTH = AuthConfig(users=_load_users())

# =============================================================================
# 通知配置
# =============================================================================
_default_notification_targets = {
    "groups": ["1071889524"],
    "users": [],
}
_module_targets: Optional[Dict[str, List[str]]] = None
_module_enable: Optional[bool] = None

try:  # backwards compatibility with legacy notification_config.py
    from notification_config import (  # type: ignore
        NOTIFICATION_GROUPS,
        NOTIFICATION_USERS,
        BOT_HTTP_URL as NOTIFICATION_BOT_HTTP_URL,
        BOT_ACCESS_TOKEN as NOTIFICATION_BOT_ACCESS_TOKEN,
        ENABLE_NOTIFICATION,
    )

    BOT_HTTP_URL = os.getenv("BOT_HTTP_URL", NOTIFICATION_BOT_HTTP_URL)
    BOT_ACCESS_TOKEN = os.getenv("BOT_ACCESS_TOKEN", NOTIFICATION_BOT_ACCESS_TOKEN)
    _module_targets = {
        "groups": list(NOTIFICATION_GROUPS),
        "users": list(NOTIFICATION_USERS),
    }
    _module_enable = bool(ENABLE_NOTIFICATION)
except ImportError:
    BOT_HTTP_URL = os.getenv("BOT_HTTP_URL")
    BOT_ACCESS_TOKEN = os.getenv("BOT_ACCESS_TOKEN")

if not BOT_HTTP_URL:
    BOT_HTTP_URL = "http://127.0.0.1:3000"
if BOT_ACCESS_TOKEN is None:
    BOT_ACCESS_TOKEN = ""

NOTIFICATION_TARGETS = _load_notification_targets(_module_targets or _default_notification_targets)
ENABLE_ORDER_NOTIFICATION = _env_bool(
    "SJA_ENABLE_NOTIFICATION",
    _module_enable if _module_enable is not None else ENVIRONMENT != "development",
)


# =============================================================================
# 默认预订目标配置 (BookingTarget)
# =============================================================================
# 此配置作为所有命令的默认基础设置，会被命令行参数覆盖
# 
# 使用场景：
# 1. slots 命令 - 查询时间段可用性的默认目标
#    python main.py slots  # 使用此默认配置
#    python main.py slots --preset 13  # 覆盖为预设13的配置
#
# 2. monitor 命令 - 监控可用性的默认目标  
#    python main.py monitor  # 使用此默认配置监控学生中心羽毛球
#    python main.py monitor --preset 5  # 覆盖为预设5的配置
#
# 3. book-now 命令 - 立即预订的默认目标
#    python main.py book-now  # 使用此默认配置尝试预订
#    python main.py book-now --preset 1  # 覆盖为预设1的配置
#
# 4. schedule 命令 - 定时预订的默认目标
#    python main.py schedule --hour 8 --minute 0  # 每天8:00使用此配置预订
#
# 5. service 模块 - 作为所有服务的默认参考目标
#    - list_slots() 函数使用此配置作为基础
#    - order_once() 函数使用此配置作为参考
#    - 当没有提供 base_target 参数时，回退到此配置
#
# 参数说明：
# - venue_id/venue_keyword: 场馆标识，优先使用ID，keyword用于搜索
# - field_type_id/field_type_keyword: 运动类型标识，优先使用ID，keyword用于搜索  
# - date_offset: 日期偏移量，7表示7天后（下周今天）
# - start_hour: 期望的开始时间（24小时制）
# - duration_hours: 预订时长（小时）
# =============================================================================
DEFAULT_TARGET = BookingTarget(
    venue_keyword="学生中心",          # 场馆关键词，用于搜索匹配
    field_type_keyword="羽毛球",       # 运动类型关键词，用于搜索匹配
    date_offset=7,                    # 日期偏移量：7天后（下周今天）
    start_hour=18,                    # 期望开始时间：18:00（下午6点）
    field_type_code=None,             # 运动类型代码（可选，用于特殊匹配）
    date_token=None,                  # 日期令牌（可选，用于特定日期查询）
    use_all_dates=False,              # 是否使用所有可用日期（False时使用date_offset）
    venue_id=None,                    # 场馆ID（优先使用，为None时使用keyword搜索）
    field_type_id=None,               # 运动类型ID（优先使用，为None时使用keyword搜索）
    fixed_dates=[],                   # 固定日期列表（优先级最高）
    duration_hours=1,                 # 预订时长：1小时
)

TARGET = _load_target(DEFAULT_TARGET)

# Default monitor behaviour for the `monitor` and `schedule` commands.
monitor_interval = int(os.getenv("SJA_MONITOR_INTERVAL", str(4 * 60)))
monitor_preferred_hours = _parse_int_list("SJA_MONITOR_PREFERRED_HOURS") or [19, 20]
monitor_preferred_days = _parse_int_list("SJA_MONITOR_PREFERRED_DAYS") or [0, 1, 2, 3, 4, 5, 6, 7, 8]

MONITOR_PLAN = MonitorPlan(
    enabled=_env_bool("SJA_MONITOR_ENABLED", True),
    interval_seconds=monitor_interval,
    auto_book=_env_bool("SJA_MONITOR_AUTO_BOOK", True),
    notify_stdout=_env_bool("SJA_MONITOR_NOTIFY_STDOUT", True),
    preferred_hours=monitor_preferred_hours,
    preferred_days=monitor_preferred_days,
    require_all_users_success=_env_bool("SJA_MONITOR_REQUIRE_ALL_SUCCESS", False),
    max_time_gap_hours=int(os.getenv("SJA_MONITOR_MAX_TIME_GAP_HOURS", "1")),
)

schedule_start_hours = _parse_int_list("SJA_SCHEDULE_START_HOURS") or [18]

SCHEDULE_PLAN = SchedulePlan(
    hour=int(os.getenv("SJA_SCHEDULE_HOUR", "12")),
    minute=int(os.getenv("SJA_SCHEDULE_MINUTE", "0")),
    second=int(os.getenv("SJA_SCHEDULE_SECOND", "0")),
    date_offset=int(os.getenv("SJA_SCHEDULE_DATE_OFFSET", "1")),
    start_hours=schedule_start_hours,
    duration_hours=int(os.getenv("SJA_SCHEDULE_DURATION", "1")),
    auto_start=_env_bool("SJA_SCHEDULE_AUTO_START", True),
)

AUTO_BOOKING_SETTINGS = {
    # 抢票前的预热提前量，确保在放票前完成登录、token、sign等准备
    "warmup_seconds": int(os.getenv("SJA_AUTOBOOK_WARMUP_SECONDS", "35")),
    # 默认抢票的日期偏移量（单位：天），默认为抢第7天
    "target_offset_days": int(os.getenv("SJA_AUTOBOOK_TARGET_OFFSET_DAYS", "7")),
    # 抢票失败后的刷新间隔和最大刷新次数，用于短时间内快速轮询库存
    "slot_refresh_interval_seconds": float(os.getenv("SJA_AUTOBOOK_REFRESH_INTERVAL", "0.35")),
    "slot_refresh_rounds": int(os.getenv("SJA_AUTOBOOK_REFRESH_ROUNDS", "6")),
    "slot_cache_ttl_seconds": float(os.getenv("SJA_AUTOBOOK_SLOT_CACHE_TTL", "25")),
    # 并发下单的最大数量（每轮尝试的slot数量）
    "max_parallel_orders": max(1, int(os.getenv("SJA_AUTOBOOK_PARALLEL_ORDERS", "6"))),
    # order manager 的超时时间，确保快速失败快速重试
    "order_request_timeout": float(os.getenv("SJA_AUTOBOOK_ORDER_TIMEOUT", "3.0")),
    # HTTP POST 节流配置（秒），0 表示取消节流
    "post_throttle_seconds": float(os.getenv("SJA_AUTOBOOK_POST_THROTTLE", "0.0")),
    # 单个时间段下单的最大重试次数
    "order_retry_attempts": max(1, int(os.getenv("SJA_AUTOBOOK_ORDER_RETRIES", "3"))),
    # 是否在首次尝试前强制刷新最新场地信息
    "order_refresh_before_attempt": _env_bool("SJA_AUTOBOOK_ORDER_REFRESH_FIRST", True),
    # 并发失败后的退避时间
    "retry_delay_seconds": float(os.getenv("SJA_AUTOBOOK_RETRY_DELAY", "0.8")),
}


# Default API endpoints discovered from the current platform version.
_JACCOUNT_CLIENT_ID = "mB5nKHqC00MusWAgnqSF"
_JACCOUNT_REDIRECT = f"{BASE_URL}/oauth2Login"
_JACCOUNT_AUTHORIZE = (
    "https://jaccount.sjtu.edu.cn/oauth2/authorize"
    f"?response_type=code&client_id={_JACCOUNT_CLIENT_ID}"
    f"&redirect_uri={quote_plus(_JACCOUNT_REDIRECT)}"
)
ENDPOINTS = EndpointSet(
    current_user="/system/user/currentUser",
    list_venues="/manage/venue/listOrderCount",
    venue_detail="/manage/venue/queryVenueById",
    field_situation="/manage/fieldDetail/queryFieldSituation",
    field_reserve="/manage/fieldDetail/queryFieldReserveSituationIsFull",
    order_submit="/venue/personal/orderImmediatelyPC",
    order_confirm="/venue/personal/ConfirmOrder",  # 新增下单确认端点
    appointment_overview="/appointment/disabled/getAppintmentAndSysUserbyUser",
    slot_summary="/manage/fieldDetail/queryFieldReserveSituationIsFull",
    ping="/",
    # jAccount credential login flow
    login_prepare=_JACCOUNT_AUTHORIZE,
    login_submit="https://jaccount.sjtu.edu.cn/jaccount/ulogin",
    login_captcha="https://jaccount.sjtu.edu.cn/jaccount/captcha",
)


# 加密相关配置
ENCRYPTION_CONFIG = {
    "rsa_public_key": """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEArKZOdKQAL+iYzJ4Q5EQzwv/yvVPnfdNVKRgNG19HbCYM4qIzFPEOFv28SVFQh+xqAj8tAfjpMSTihFwt6BQuWfZXWYpAqf4jF4cU7ez/VHJyzsn8Cb7Lf/1KsLpuz+MbqufrA57AysnLAnRXHOwik+QnpsXZYjTcjgxQ0iLMe5iJyo06CKFxH1rmgYMwS4E89kNg1VtYrFKs1MajApfhu9hTEXnm/lP24TPdefRXbf+z84p1GLue2HRhZs3wECH1HJWZOsrdL/M+wigWldY0fHoiaKsjD9rK1NyaPtk4bIYuwPsfQu5RN4hkEPpTvdw1nKzOdo77zNa5ovCY0uNLZwIDAQAB
-----END PUBLIC KEY-----""",
    "aes_key_length": 16,  # AES-128
    "return_url": os.getenv("SJA_ENCRYPTION_RETURN_URL", "https://sports.sjtu.edu.cn/#/paymentResult/1"),
}

# 场馆和运动类型映射表 - 用户可以通过序号选择
DEFAULT_PRESET_TARGETS = [
    PresetOption(
        index=1,
        venue_id="d784ad7c-cb24-4282-afd6-a67aec68c675",
        venue_name="学生中心",
        field_type_id="32c2a148-c828-4b15-a392-8c551195f596",
        field_type_name="交谊厅",
        field_type_code=None,
    ),
    PresetOption(
        index=2,
        venue_id="d784ad7c-cb24-4282-afd6-a67aec68c675",
        venue_name="学生中心",
        field_type_id="417dc5ed-aba7-4abb-bbdc-efef8446dbdb",
        field_type_name="台球",
        field_type_code=None,
    ),
    PresetOption(
        index=3,
        venue_id="d784ad7c-cb24-4282-afd6-a67aec68c675",
        venue_name="学生中心",
        field_type_id="7d46c0a4-3ae6-4398-822b-d4b7b37085fa",
        field_type_name="学生中心健身房",
        field_type_code=None,
    ),
    PresetOption(
        index=4,
        venue_id="d784ad7c-cb24-4282-afd6-a67aec68c675",
        venue_name="学生中心",
        field_type_id="f8e10d96-a3c9-425e-a0c0-e0cbbaf135c0",
        field_type_name="舞蹈",
        field_type_code=None,
    ),
    PresetOption(
        index=5,
        venue_id="3b10ff47-7e83-4c21-816c-5edc257168c1",
        venue_name="气膜体育中心",
        field_type_id="29942202-d2ac-448e-90b7-14d3c6be19ff",
        field_type_name="羽毛球",
        field_type_code=None,
    ),
    PresetOption(
        index=6,
        venue_id="3b10ff47-7e83-4c21-816c-5edc257168c1",
        venue_name="气膜体育中心",
        field_type_id="8dc0e52c-564a-4d9a-9cb2-08477f1a18d4",
        field_type_name="篮球",
        field_type_code=None,
    ),
    PresetOption(
        index=7,
        venue_id="768214ba-3b1c-4f29-ad00-15c0e376b000",
        venue_name="子衿街学生活动中心",
        field_type_id="019335a6-9d67-4d7d-923e-92ecea740c7b",
        field_type_name="舞蹈",
        field_type_code=None,
    ),
    PresetOption(
        index=8,
        venue_id="768214ba-3b1c-4f29-ad00-15c0e376b000",
        venue_name="子衿街学生活动中心",
        field_type_id="0a349309-1734-4507-98bd-4c30bf33c6bc",
        field_type_name="健身房",
        field_type_code=None,
    ),
    PresetOption(
        index=9,
        venue_id="768214ba-3b1c-4f29-ad00-15c0e376b000",
        venue_name="子衿街学生活动中心",
        field_type_id="151ba6a9-2cb1-489d-8cbd-2d2fe5e12f7c",
        field_type_name="桌游室",
        field_type_code=None,
    ),
    PresetOption(
        index=10,
        venue_id="768214ba-3b1c-4f29-ad00-15c0e376b000",
        venue_name="子衿街学生活动中心",
        field_type_id="57fbed57-d8b9-4247-a6ed-b2088a9e8a37",
        field_type_name="钢琴",
        field_type_code=None,
    ),
    PresetOption(
        index=11,
        venue_id="768214ba-3b1c-4f29-ad00-15c0e376b000",
        venue_name="子衿街学生活动中心",
        field_type_id="7bffbb9b-4999-49e4-9025-6012d3524da8",
        field_type_name="烘焙",
        field_type_code=None,
    ),
    PresetOption(
        index=12,
        venue_id="768214ba-3b1c-4f29-ad00-15c0e376b000",
        venue_name="子衿街学生活动中心",
        field_type_id="bbd8cc4b-f3b5-4714-af53-f61a8f1c2fba",
        field_type_name="琴房兼乐器",
        field_type_code=None,
    ),
    PresetOption(
        index=13,
        venue_id="73b17f69-6ed9-481f-b157-5e0606a55fd5",
        venue_name="南洋北苑健身房",
        field_type_id="dad366b3-7db9-4043-865c-7177aff83efa",
        field_type_name="健身房",
        field_type_code=None,
    ),
    PresetOption(
        index=14,
        venue_id="3f009fce-10b4-4df6-94b7-9d46aef77bb9",
        venue_name="南区体育馆",
        field_type_id="28d3bea9-541d-4efb-ae46-e739a5f78d72",
        field_type_name="乒乓球",
        field_type_code=None,
    ),
    PresetOption(
        index=15,
        venue_id="3f009fce-10b4-4df6-94b7-9d46aef77bb9",
        venue_name="南区体育馆",
        field_type_id="3770c0b3-1060-41f4-ae12-8df38d48c8b1",
        field_type_name="排球",
        field_type_code=None,
    ),
    PresetOption(
        index=16,
        venue_id="3f009fce-10b4-4df6-94b7-9d46aef77bb9",
        venue_name="南区体育馆",
        field_type_id="7f11b6af-cb2e-47ac-9a51-9cd0df885736",
        field_type_name="篮球",
        field_type_code=None,
    ),
    PresetOption(
        index=17,
        venue_id="8130b252-16a7-4066-9c30-c89bb1fac1e9",
        venue_name="胡法光体育场",
        field_type_id="a810f3f6-f5c8-4ab3-b57c-e9372f40649b",
        field_type_name="舞蹈",
        field_type_code=None,
    ),
    PresetOption(
        index=18,
        venue_id="9096787a-bc53-430a-9405-57dc46bc9e83",
        venue_name="霍英东体育中心",
        field_type_id="49629b20-71fb-4bae-8675-fdae0831e861",
        field_type_name="羽毛球",
        field_type_code=None,
    ),
    PresetOption(
        index=19,
        venue_id="9096787a-bc53-430a-9405-57dc46bc9e83",
        venue_name="霍英东体育中心",
        field_type_id="561d43a3-338e-4834-b35f-747bdc578366",
        field_type_name="篮球",
        field_type_code=None,
    ),
    PresetOption(
        index=20,
        venue_id="9096787a-bc53-430a-9405-57dc46bc9e83",
        venue_name="霍英东体育中心",
        field_type_id="b3dce013-3a0e-45e0-a0c2-425a364ac90f",
        field_type_name="健身房",
        field_type_code=None,
    ),
    PresetOption(
        index=21,
        venue_id="db75ba81-ae54-4f22-ad5e-84de039f5a89",
        venue_name="徐汇校区体育馆",
        field_type_id="0f71f5e1-2e24-4c15-b437-cc9f82a1343e",
        field_type_name="健身房",
        field_type_code=None,
    ),
    PresetOption(
        index=22,
        venue_id="db75ba81-ae54-4f22-ad5e-84de039f5a89",
        venue_name="徐汇校区体育馆",
        field_type_id="84e4aeaf-0c8c-431c-a64d-7ccd9cc381f6",
        field_type_name="羽毛球",
        field_type_code=None,
    ),
    PresetOption(
        index=23,
        venue_id="db75ba81-ae54-4f22-ad5e-84de039f5a89",
        venue_name="徐汇校区体育馆",
        field_type_id="92c28497-7437-4d5d-ab55-55721009db45",
        field_type_name="乒乓球",
        field_type_code=None,
    ),
    PresetOption(
        index=24,
        venue_id="cfd28228-bb2a-4a61-8c6a-4da6da3877e0",
        venue_name="致远游泳健身馆",
        field_type_id="8c229c55-6188-48b7-822f-477e5ddb3820",
        field_type_name="乒乓球",
        field_type_code=None,
    ),
    PresetOption(
        index=25,
        venue_id="165f97cc-ea52-42a3-aaaf-357b8c2569ae",
        venue_name="徐汇校区网球场",
        field_type_id="2353a4d7-7017-45f1-8cdf-4d857fc86dbe",
        field_type_name="网球",
        field_type_code=None,
    ),
    PresetOption(
        index=26,
        venue_id="1888c119-d7cd-4d56-8c63-94e818dc8a38",
        venue_name="徐汇校区足球场",
        field_type_id="150d21d9-13ed-4320-8ab1-1cfb14c52bef",
        field_type_name="足球",
        field_type_code=None,
    ),
    PresetOption(
        index=27,
        venue_id="93284352-aad3-4353-8448-aad2b1526da1",
        venue_name="张江校区体育运动中心",
        field_type_id="",
        field_type_name="无运动类型",
        field_type_code=None,
    ),
    PresetOption(
        index=28,
        venue_id="108d2783-6565-4efa-bf78-e0db8dd8acb6",
        venue_name="学创船建分中心",
        field_type_id="ea0c50b2-52b9-44ae-928d-6f59e5c63fb9",
        field_type_name="创新实践",
        field_type_code=None,
    ),
    PresetOption(
        index=29,
        venue_id="eeaa1c0f-8ec3-466e-b822-f2e47d747c9e",
        venue_name="学创空天分中心",
        field_type_id="878844e8-bd71-4c2e-ab54-b1464207da8d",
        field_type_name="创新实践",
        field_type_code=None,
    ),
    PresetOption(
        index=30,
        venue_id="84c5439f-fc02-488b-83d5-6026077b3094",
        venue_name="学创机动分中心",
        field_type_id="dc20c596-ebb5-4b84-87ec-5848f1ea0495",
        field_type_name="创新实践",
        field_type_code=None,
    ),
    PresetOption(
        index=31,
        venue_id="a41b3261-6fce-4073-b799-1e91ed19a7f3",
        venue_name="致远游泳馆东侧足球场",
        field_type_id="6a157dec-2f89-4f5c-ba10-dd28db67292b",
        field_type_name="足球",
        field_type_code=None,
    ),
    PresetOption(
        index=32,
        venue_id="3466293b-a7d8-45be-a918-8526e3bed4c5",
        venue_name="东区网球场",
        field_type_id="4dd7ae28-cf27-4369-9bc4-ee75b8e3cc76",
        field_type_name="网球",
        field_type_code=None,
    ),
    PresetOption(
        index=33,
        venue_id="2b528fa8-3ce8-4a7a-8f8b-83cc537901ed",
        venue_name="笼式足球场",
        field_type_id="ad666603-a47e-488d-b913-d5304a880ced",
        field_type_name="足球",
        field_type_code=None,
    ),
    PresetOption(
        index=34,
        venue_id="0c6edc93-87ac-41b0-9895-6b66fda93fe5",
        venue_name="胡晓明网球场",
        field_type_id="19f69e5c-872f-4fbb-b9fe-70d6337c2d93",
        field_type_name="网球",
        field_type_code=None,
    ),
]

PRESET_TARGETS = _load_presets(DEFAULT_PRESET_TARGETS)



__all__ = [
    "ENVIRONMENT",
    "CONFIG_ROOT",
    "BASE_URL",
    "AUTH",
    "ENDPOINTS",
    "TARGET",
    "MONITOR_PLAN",
    "SCHEDULE_PLAN",
    "AUTO_BOOKING_SETTINGS",
    "PRESET_TARGETS",
    "ENCRYPTION_CONFIG",
    "BOT_HTTP_URL",
    "BOT_ACCESS_TOKEN",
    "NOTIFICATION_TARGETS",
    "ENABLE_ORDER_NOTIFICATION",
]
