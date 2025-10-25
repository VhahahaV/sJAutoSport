# Bot集成使用指南

## 概述

本系统已成功集成了bot机器人功能，实现了订单成功后的自动通知。当用户通过前端或CLI成功下单时，系统会自动向指定的QQ群组或用户发送通知消息，提醒用户及时支付。

## 功能特性

### 🎯 核心功能
- **自动通知**：订单成功后自动发送通知到QQ群组或私聊
- **多目标支持**：支持群组和用户两种通知目标
- **详细信息**：通知包含订单ID、用户、场馆、时间等完整信息
- **支付提醒**：自动提醒用户前往支付页面完成支付

### 🔧 技术特性
- **端口管理**：自动处理端口冲突问题
- **集成启动**：一键启动所有服务（API + Bot + 前端）
- **配置管理**：灵活的配置文件管理
- **错误处理**：完善的错误处理和重试机制

## 快速开始

### 1. 配置通知目标

在 `config.py` 中调整通知相关配置：

```python
# Bot接口配置
BOT_HTTP_URL = "http://127.0.0.1:3000"
BOT_ACCESS_TOKEN = ""  # 如需鉴权可填写令牌

# 通知对象（支持群组与个人）
NOTIFICATION_TARGETS = {
    "groups": ["123456789", "987654321"],  # QQ群ID
    "users": ["123456", "789012"],        # QQ号
}

# 全局通知开关与重试策略
ENABLE_NOTIFICATION = True
NOTIFICATION_DELAY = 1
NOTIFICATION_RETRY_COUNT = 3
NOTIFICATION_RETRY_DELAY = 5

# 可选：自定义消息模板
NOTIFICATION_TEMPLATE = {
    "success_title": "🎉 订单预订成功！",
    "payment_reminder": "💡 请及时前往支付页面完成支付！",
    "payment_link": "https://sports.sjtu.edu.cn/pc/order/list",
}
```

### 2. 启动集成服务

```bash
# 启动所有服务（API + Bot + 前端）
python start_integrated.py

# 只启动API和Bot（不启动前端）
python start_integrated.py --no-frontend

# 只启动API服务
python start_integrated.py --api-only

# 只启动Bot服务
python start_integrated.py --bot-only
```

### 3. 测试通知功能

```bash
# 测试通知功能
python test_notification.py

# 测试完整订单流程
python test_order_with_notification.py
```

## 服务架构

### 端口分配
- **8000**: 后端API服务
- **6700**: Bot HTTP接收服务（NoneBot，`BOT_HTTP_SERVER_PORT` 默认值）
- **6099**: NapCat OneBot HTTP/WebSocket 服务
- **5173**: 前端开发服务器（可选，`FRONTEND_PORT` 默认值）

### 服务组件
1. **后端API** (`web_api/`): 处理订单请求
2. **Bot机器人** (`bot/`): 发送通知消息
3. **前端界面** (`frontend/`): 用户操作界面
4. **通知服务** (`sja_booking/notification.py`): 通知逻辑

## 通知消息格式

### 成功通知示例
```
🎉 订单预订成功！

📋 订单信息：
🆔 订单ID: 967326491262324736
👤 用户: czq
🏟️ 场馆: 南洋北苑健身房
🏃 项目: 健身房
📅 日期: 2024-01-02
⏰ 时间: 18:00 - 19:00

💡 请及时前往支付页面完成支付！
🔗 支付链接: https://sports.sjtu.edu.cn/pc/order/list

下单成功，订单ID: 967326491262324736
```

## Bot命令

### 通知管理命令
- `测试通知`: 发送测试通知消息
- `设置通知 群组=123456789 用户=123456`: 设置通知目标
- `通知状态`: 查看当前通知配置状态

### 使用示例
```
# 在QQ群中发送
测试通知

# 设置通知目标
设置通知 群组=1071889524

# 查看通知状态
通知状态
```

## 配置说明

### 主配置文件 (`config.py`)
```python
# 通知配置（节选）
BOT_HTTP_URL = "http://127.0.0.1:3000"
BOT_ACCESS_TOKEN = ""
NOTIFICATION_TARGETS = {
    "groups": ["1071889524"],
    "users": ["2890095056"],
}
ENABLE_NOTIFICATION = True
ENABLE_ORDER_NOTIFICATION = True
NOTIFICATION_DELAY = 1
NOTIFICATION_RETRY_COUNT = 3
NOTIFICATION_RETRY_DELAY = 5
NOTIFICATION_TEMPLATE = {
    "success_title": "🎉 订单预订成功！",
    "payment_reminder": "💡 请及时前往支付页面完成支付！",
    "payment_link": "https://sports.sjtu.edu.cn/pc/order/list",
}
```

> ⚙️ `BOT_HTTP_SERVER_PORT` 用于配置 NoneBot HTTP 接收服务监听端口，默认 `6700`。若使用 NapCat 的 WebSocket 模式且不需要 HTTP 接收，可将 `BOT_HTTP_SERVER_ENABLED` 设为 `false`。

### 与 NapCat Docker 协同

若通过 Docker 运行 NapCat（如 `docker run -p 3000:3000 -p 3001:3001 -p 6099:6099 ...`），请确保：
- NapCat 占用的 `3000/3001/6099` 与项目端口不冲突；
- 项目前端和 Bot HTTP 默认分别监听 `5173` 与 `6700`，无需额外调整；
- 如需自定义端口，可在执行 `python start_integrated.py` 前设置：
  ```bash
  export BOT_HTTP_SERVER_PORT=6701      # 自定义 Bot HTTP 端口
  export FRONTEND_PORT=5174             # 自定义前端端口
  export INTEGRATED_FRONTEND_ENABLED=0  # 如无需前端可禁用
  ```
  重新启动集成脚本即可生效。

## 故障排除

### 常见问题

1. **通知未发送**
   - 检查 `ENABLE_ORDER_NOTIFICATION` 是否为 `True`
   - 检查 `NOTIFICATION_TARGETS` 是否配置了目标
   - 检查Bot HTTP API是否正常运行

2. **端口冲突**
   - 使用 `python start_integrated.py` 自动处理端口冲突
   - 手动检查端口占用：`lsof -i :8000 -i :6700 -i :6099 -i :5173`

3. **Bot连接失败**
   - 检查Bot HTTP API地址是否正确
   - 检查访问令牌是否配置正确
   - 使用模拟Bot API进行测试：`python mock_bot_api.py`

### 调试工具

1. **模拟Bot API**
   ```bash
   python mock_bot_api.py
   ```

2. **测试通知**
   ```bash
   python test_notification.py
   ```

3. **查看服务状态**
   ```bash
   lsof -i :8000 -i :6700 -i :6099 -i :5173
   ```

## 开发说明

### 添加新的通知类型

1. 在 `sja_booking/notification.py` 中添加新的通知方法
2. 在订单处理流程中调用新的通知方法
3. 更新Bot插件以支持新的通知类型

### 自定义通知消息

修改 `sja_booking/notification.py` 中的 `_build_success_message` 方法：

```python
def _build_success_message(self, notification: OrderNotification) -> str:
    """构建成功消息"""
    message = f"""🎉 订单预订成功！

📋 订单信息：
🆔 订单ID: {notification.order_id}
👤 用户: {notification.user_nickname}
🏟️ 场馆: {notification.venue_name}
🏃 项目: {notification.field_type_name}
📅 日期: {notification.date}
⏰ 时间: {notification.start_time} - {notification.end_time}

💡 请及时前往支付页面完成支付！
🔗 支付链接: https://sports.sjtu.edu.cn/pc/order/list

{notification.message}"""
    return message
```

## 总结

Bot集成功能已成功实现，提供了完整的订单成功通知解决方案。系统支持多种启动方式、灵活的配置管理和完善的错误处理，能够满足不同场景下的使用需求。

通过简单的配置和命令，用户可以轻松设置通知目标，实现订单成功后的自动提醒功能，大大提升了用户体验和系统的实用性。
