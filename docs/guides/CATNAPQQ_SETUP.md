# CatNapQQ 配置指南

## 📋 概述

本指南将帮助您配置机器人连接到 CatNapQQ（基于 OneBot 协议的 QQ 机器人框架）。

## 🔧 前置要求

### 1. 安装 CatNapQQ

#### 方法一：使用官方安装脚本
```bash
# 下载并运行安装脚本
curl -sSL https://raw.githubusercontent.com/0x5c/catnapqq/main/install.sh | bash

# 或者手动下载
wget https://github.com/0x5c/catnapqq/releases/latest/download/catnapqq-linux-amd64.tar.gz
tar -xzf catnapqq-linux-amd64.tar.gz
```

#### 方法二：使用 Docker
```bash
docker run -d --name catnapqq \
  -p 6099:6099 \
  -v ./data:/app/data \
  -e QQ_NUMBER=your_qq_number \
  -e QQ_PASSWORD=your_qq_password \
  0x5c/catnapqq:latest
```

### 2. 安装 Python 依赖

```bash
# 进入项目目录
cd sJAutoSport

# 安装机器人依赖
cd bot
pip install -r requirements.txt

# 或者使用 Poetry
poetry install
```

## ⚙️ 配置步骤

### 1. 创建环境配置文件

在 `bot/` 目录下创建 `.env` 文件：

```bash
cd bot
cp env.example .env
```

### 2. 配置 CatNapQQ 连接

编辑 `bot/.env` 文件：

```env
# CatNapQQ 连接配置
NTQQ_WS_URL=ws://127.0.0.1:6099/onebot/v11/ws
NTQQ_HTTP_URL=http://127.0.0.1:6099
NTQQ_ACCESS_TOKEN=your_access_token_here

# 机器人基础配置
BOT_NICKNAME=体育预订助手
BOT_COMMAND_PREFIX=!

# 日志配置
LOG_LEVEL=INFO
LOG_FILE=logs/bot.log

# 数据库配置
DATABASE_URL=sqlite:///data/bot.db

# 服务层配置
SERVICE_BASE_URL=https://sports.sjtu.edu.cn
SERVICE_AUTH_COOKIE=your_sjtu_cookie_here

# 监控配置
DEFAULT_MONITOR_INTERVAL=240
DEFAULT_AUTO_BOOK=false

# 定时任务配置
DEFAULT_SCHEDULE_HOUR=8
DEFAULT_SCHEDULE_MINUTE=0

# 安全配置
SUPERUSERS=your_qq_number
COMMAND_WHITELIST=
```

### 3. 配置 CatNapQQ

#### 创建 CatNapQQ 配置文件

在 CatNapQQ 安装目录下创建 `config.yaml`：

```yaml
# CatNapQQ 配置文件
qq:
  number: "your_qq_number"  # 你的QQ号
  password: "your_qq_password"  # 你的QQ密码

# OneBot 协议配置
onebot:
  ws:
    enabled: true
    host: "0.0.0.0"
    port: 6099
    path: "/onebot/v11/ws"
  http:
    enabled: true
    host: "0.0.0.0"
    port: 6099
    access_token: "your_access_token_here"  # 与 .env 中的一致

# 日志配置
log:
  level: "info"
  file: "logs/catnapqq.log"

# 数据库配置
database:
  type: "sqlite"
  path: "data/catnapqq.db"
```

### 4. 获取 SJTU 认证信息

#### 方法一：手动获取 Cookie

1. 打开浏览器，访问 https://sports.sjtu.edu.cn
2. 登录你的 SJTU 账号
3. 打开开发者工具 (F12)
4. 在 Network 标签页中找到任意请求
5. 复制 Cookie 值

#### 方法二：使用脚本获取

```python
# 创建 get_cookie.py 脚本
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
import time

def get_sjtu_cookie():
    driver = webdriver.Chrome()
    try:
        driver.get("https://sports.sjtu.edu.cn")
        
        # 等待登录
        input("请手动登录，然后按回车继续...")
        
        # 获取 Cookie
        cookies = driver.get_cookies()
        cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
        
        print(f"Cookie: {cookie_str}")
        return cookie_str
    finally:
        driver.quit()

if __name__ == "__main__":
    get_sjtu_cookie()
```

## 🚀 启动步骤

### 1. 启动 CatNapQQ

```bash
# 方法一：直接运行
./catnapqq

# 方法二：使用配置文件
./catnapqq --config config.yaml

# 方法三：Docker
docker start catnapqq
```

### 2. 启动机器人

```bash
# 进入机器人目录
cd bot

# 启动机器人
python bot.py

# 或者使用 Poetry
poetry run python bot.py

# 或者使用启动脚本
python run.py
```

### 3. 验证连接

启动成功后，你应该看到类似输出：

```
[INFO] NoneBot 初始化完成
[INFO] 正在连接到 CatNapQQ...
[INFO] WebSocket 连接已建立
[INFO] 机器人已上线
```

## 🔍 故障排除

### 常见问题

#### 1. 连接失败

**问题**: `WebSocket connection failed`

**解决方案**:
- 检查 CatNapQQ 是否正在运行
- 确认端口 6099 未被占用
- 检查防火墙设置
- 验证 `NTQQ_WS_URL` 配置是否正确

#### 2. 认证失败

**问题**: `Authentication failed`

**解决方案**:
- 检查 `NTQQ_ACCESS_TOKEN` 是否与 CatNapQQ 配置一致
- 确认 QQ 账号密码正确
- 检查 CatNapQQ 日志中的错误信息

#### 3. 插件加载失败

**问题**: `Plugin load failed`

**解决方案**:
- 检查 Python 依赖是否安装完整
- 确认插件文件路径正确
- 查看详细错误日志

#### 4. SJTU 认证失败

**问题**: `SJTU authentication failed`

**解决方案**:
- 更新 `SERVICE_AUTH_COOKIE`
- 检查 Cookie 是否过期
- 确认 SJTU 账号状态正常

### 调试模式

启用详细日志：

```env
LOG_LEVEL=DEBUG
```

查看日志文件：

```bash
tail -f logs/bot.log
tail -f logs/catnapqq.log
```

## 📱 使用机器人

### 基本命令

```
!查询 preset=13
!预订 preset=13 time=18
!开始监控 preset=13
!抢票状态
!系统状态
```

### 管理员命令

```
!管理帮助
!清理 all
!验证码
```

## 🔒 安全建议

1. **保护敏感信息**:
   - 不要将 `.env` 文件提交到版本控制
   - 定期更新访问令牌
   - 使用强密码

2. **权限控制**:
   - 设置 `SUPERUSERS` 限制管理员权限
   - 使用 `COMMAND_WHITELIST` 限制命令使用

3. **网络安全**:
   - 使用 HTTPS 连接
   - 定期更新依赖包
   - 监控异常活动

## 📞 技术支持

如果遇到问题，请：

1. 查看日志文件
2. 检查配置文件
3. 参考 [故障排除](#故障排除) 部分
4. 提交 Issue 到项目仓库

## 🎉 完成

配置完成后，你的机器人就可以通过 QQ 接收命令并执行体育预订相关操作了！
