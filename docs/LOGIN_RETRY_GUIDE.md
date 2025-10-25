# 🔄 登录重试功能说明

## 概述

为了提高登录成功率，系统现在支持自动重试机制。当登录失败时，系统会自动重试最多5次，每次间隔2秒。

## 🚀 功能特性

### ✅ 重试机制
- **最大重试次数**: 5次
- **重试间隔**: 2秒
- **智能错误识别**: 区分验证码错误、账号错误等不同类型
- **详细日志**: 显示每次重试的状态和结果

### 📊 错误类型识别
- **验证码错误**: 验证码识别错误或输入错误
- **账号信息错误**: 用户名或密码错误
- **其他错误**: 网络问题、服务器错误等

## 🔧 实现位置

### 1. CLI登录 (`sja_booking/cli.py`)
```python
result = await perform_login(
    cfg.BASE_URL,
    cfg.ENDPOINTS,
    cfg.AUTH,
    username,
    password,
    solver=None if args.no_ocr else solve_captcha_async,
    fallback=fallback_local,
    max_retries=5,  # 最多重试5次
    retry_delay=2.0,  # 每次重试间隔2秒
)
```

### 2. Bot登录 (`sja_booking/service.py`)
- `submit_login_session_code` 函数支持验证码重试
- 最多重试5次，每次间隔2秒
- 自动重新获取验证码

### 3. 核心登录逻辑 (`sja_booking/auth.py`)
```python
async def perform_login(
    base_url: str,
    endpoints: EndpointSet,
    auth_config: AuthConfig,
    username: str,
    password: str,
    *,
    solver: Optional[CaptchaSolver] = None,
    fallback: Optional[HumanFallback] = None,
    threshold: float = 0.3,
    max_retries: int = 5,      # 最大重试次数
    retry_delay: float = 2.0,  # 重试间隔（秒）
) -> AuthResult:
```

## 📝 使用示例

### CLI登录重试
```bash
python main.py login
# 如果登录失败，系统会自动重试5次
```

### Bot登录重试
```bash
# 发送 !login 命令
# 如果验证码错误，系统会自动重试
```

### Web 控制台登录
- 打开前端的「会话管理」页面，输入用户名与密码后点击「开始登录」
- 如需验证码，页面会自动展示图片并支持重复提交
- 登录成功后会立即刷新后端保存的 Cookie 列表

## 🔍 重试日志示例

```
[blue]验证码图片已保存到: ~/.sja/debug/captcha_20251022_112100.png[/blue]
[green]验证码识别成功，置信度: 0.50, 结果: rmwmk[/green]
[yellow]⚠️  账号信息错误（第1次尝试）: 登录失败：Missing your account[/yellow]
[blue]⏳ 等待 2.0 秒后重试...[/blue]
[blue]验证码图片已保存到: ~/.sja/debug/captcha_20251022_112102.png[/blue]
[green]验证码识别成功，置信度: 0.78, 结果: rsiom[/green]
[yellow]⚠️  账号信息错误（第2次尝试）: 登录失败：Missing your account[/yellow]
[blue]⏳ 等待 2.0 秒后重试...[/blue]
[yellow]⚠️  账号信息错误（第3次尝试）: 登录失败：Missing your account[/yellow]
[red]❌ 登录失败，已尝试 5 次[/red]
```

## ⚙️ 配置选项

### 环境变量（可选）
```bash
# 可以通过环境变量调整重试参数
export LOGIN_MAX_RETRIES=5
export LOGIN_RETRY_DELAY=2.0
```

### 代码配置
```python
# 在调用 perform_login 时可以自定义参数
result = await perform_login(
    base_url,
    endpoints,
    auth_config,
    username,
    password,
    max_retries=3,    # 自定义重试次数
    retry_delay=1.5,  # 自定义重试间隔
)
```

## 🎯 适用场景

1. **验证码识别失败**: OCR识别错误时自动重试
2. **网络波动**: 网络不稳定导致登录失败
3. **服务器繁忙**: 服务器临时不可用时重试
4. **账号信息错误**: 用户名或密码错误时重试

## ⚠️ 注意事项

1. **重试间隔**: 每次重试间隔2秒，避免过于频繁的请求
2. **最大重试次数**: 最多5次，避免无限重试
3. **错误类型**: 系统会智能识别错误类型并给出相应提示
4. **资源消耗**: 重试会增加验证码图片的生成和OCR处理

## 🔧 故障排除

### 问题1：重试不工作
**解决方案：**
1. 检查是否正确调用了 `perform_login` 函数
2. 确认 `max_retries` 参数大于0
3. 查看控制台日志确认重试状态

### 问题2：重试次数过多
**解决方案：**
1. 调整 `max_retries` 参数
2. 检查账号信息是否正确
3. 确认网络连接稳定

### 问题3：重试间隔过长
**解决方案：**
1. 调整 `retry_delay` 参数
2. 考虑网络延迟因素
3. 平衡重试频率和成功率

## 📈 性能影响

- **时间成本**: 每次重试增加2秒延迟
- **资源消耗**: 重试会增加验证码生成和OCR处理
- **成功率提升**: 显著提高登录成功率
- **用户体验**: 减少手动重试的需要

## 🚀 未来改进

1. **智能重试**: 根据错误类型调整重试策略
2. **动态间隔**: 根据网络状况调整重试间隔
3. **重试统计**: 记录重试成功率和失败原因
4. **用户配置**: 允许用户自定义重试参数
