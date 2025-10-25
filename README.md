# SJTU Sports 预约系统

上海交通大学体育场馆预约的自动化/可视化解决方案，整合了后端服务、Web 前端以及 QQ Bot，适合多人协作抢场地、监控空位、自动下单。

---

## ✨ 功能亮点

- **多终端入口**：命令行、可视化控制台、QQ 机器人三端同步。
- **多用户协同**：支持导入多名体育系统账号，自动切换与并行抢场地。
- **任务调度**：内置监控、定时预约、自动抢票任务管理。
- **实时通知**：通过 OneBot/Napcat 推送群消息和私聊提醒，含订单详情。
- **前端门户保护**：内置门户密码页，可再叠加 Web 服务器 Basic Auth/VPN。
- **环境可移植**：所有敏感信息均来自环境变量或外部 JSON，方便部署到不同环境。

---

## ⚙️ 架构速览

| 模块 | 技术栈 | 说明 |
| --- | --- | --- |
| 后端 API | FastAPI + asyncio | 提供登录、抢场地、监控、任务调度等 REST 接口。 |
| 任务 Worker | 内置异步任务引擎 | 执行监控/定时/自动抢票任务，写入本地持久化。 |
| Web 前端 | React + Vite + TypeScript | 提供表单化操作、任务面板、用户管理等 UI。 |
| 通知服务 | NoneBot + OneBot (Napcat/Go-CQHTTP) | 接收下单事件并推送群聊/私聊通知。 |
| 配置 & 凭据 | 环境变量 + JSON 文件 + `data/credentials.json` | 支持 development / production 等多套环境。 |

目录结构：

```
sJAutoSport/
├── config.py            # 运行时配置加载（环境变量/JSON）
├── sja_booking/         # 核心业务逻辑（登录、下单、任务等）
├── web_api/             # FastAPI 路由
├── frontend/            # React 前端（Vite）
├── bot/                 # NoneBot 插件、集成代码
├── data/                # 默认凭据存储目录（可通过环境变量覆盖）
├── scripts/             # 部署辅助脚本
└── docs/                # 说明文档
```

---

## ✅ 前置条件

- 操作系统：macOS / Linux（Windows 建议使用 WSL2）
- Python 3.10+
- Node.js 18+（用于构建前端）
- Tesseract OCR（`brew install tesseract` 或按系统安装）
- QQ Bot：任意 OneBot v11 实现（Napcat、Go-CQHTTP 等）
- 访问 HTTPS 体育系统的网络环境

---

## 🚀 从 0 开始的部署流程

### 1. 克隆代码并安装依赖

```bash
git clone <your-repo-url> sJAutoSport
cd sJAutoSport

# Python 虚拟环境
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 前端依赖
cd frontend
npm install
cd ..
```

### 2. 运行一键配置脚本

脚本会引导你设置环境变量、创建 `.env` 文件以及默认配置（不会覆盖已有文件）。

```bash
chmod +x scripts/setup_env.sh     # 首次执行需要赋权
./scripts/setup_env.sh
```

脚本会生成以下文件（如已存在会提示是否覆盖）：

- `deploy.env` – 后端/任务/Bot 通用的环境变量（`source deploy.env` 即可加载）
- `frontend/.env.production` – 前端构建所需变量（API 地址、门户密码等）
- `bot/.env` – NoneBot 运行配置
- `config/users.json` – 体育系统账号模板（需手动填写用户名/密码后保存）
- `data/credentials.json` – 登录成功后写入 Cookie 的默认路径

> ⚠️ **记得编辑 `config/users.json`**：至少填写 1 个用户的 `username`/`password`。建议将 `deploy.env` 和 `config/users.json` 存入安全的 Secret 管理系统。

### 3. 装填体育账号 & 凭据

1. 编辑 `config/users.json`，填入至少一个体育系统账号：
   ```json
   [
     {
       "nickname": "czq",
       "username": "czq@sjtu.edu.cn",
       "password": "your-password"
     }
   ]
   ```
2. 确保 `deploy.env` 中的关键变量已填好（参见下文【环境变量一览】）。

### 4. 启动服务

```bash
source deploy.env           # 加载环境变量

# 一键启动（后端 + 前端 + Bot）
python start_integrated.py

# 或者分别启动：
# 1) 后端 API
uvicorn web_api.app:app --host 0.0.0.0 --port 8000
# 2) 前端开发模式
cd frontend && npm run dev
# 3) Bot / OneBot 适配器
python sjtu_sports.py bot
```

访问地址：
- 前端门户：`http://localhost:5173`（上线后替换为你的域名）
- 后端 API：`http://localhost:8000/api`
- QQ Bot：根据 `bot/.env` 配置链接 OneBot/Napcat

### 5. 验证

1. 浏览器访问门户，输入门户密码（`VITE_PORTAL_PASSWORD`）。
2. 在 “会话管理” 页面尝试登录体育系统账号。
3. 查询场馆、创建监控或定时任务。
4. 手动下单一次确认通知是否从 Bot 推送成功。

---

## 📄 环境变量一览

下表列出部署时常用的环境变量。所有变量均可写入 `deploy.env` 或在部署平台的 Secret 中设置。

### 后端 & 任务（加载顺序：环境变量 > JSON 文件 > 默认值）

| 变量 | 说明 | 示例 / 默认 |
| --- | --- | --- |
| `SJA_ENV` | 运行环境 | `development` / `production` |
| `SJA_BASE_URL` | 体育系统地址 | `https://sports.sjtu.edu.cn` |
| `SJA_USERS_JSON` / `SJA_USERS_FILE` | 用户账号列表（JSON 数组） | `config/users.json` |
| `SJABOT_CREDENTIAL_STORE` | Cookie 持久化文件路径 | `data/credentials.json` |
| `BOT_HTTP_URL` | OneBot HTTP 接口地址 | `http://127.0.0.1:6099` |
| `BOT_ACCESS_TOKEN` | OneBot 接口访问令牌（可选） | `your-token` |
| `SJA_NOTIFICATION_GROUPS` | 下单通知 QQ 群 ID（逗号分隔） | `1071889524` |
| `SJA_NOTIFICATION_USERS` | 下单通知 QQ 号（逗号分隔） | `2890095056` |
| `SJA_ENABLE_NOTIFICATION` | 是否启用通知 | `true` / `false` |
| `SJA_MONITOR_INTERVAL` | 监控任务间隔（秒） | `300` |
| `SJA_MONITOR_PREFERRED_HOURS` | 监控优先时间段 | `18,19,20` |
| `SJA_MONITOR_PREFERRED_DAYS` | 监控优先天数（offset） | `0,1,2` |
| `SJA_SCHEDULE_HOUR` | 定时任务小时 | `12` |
| `SJA_SCHEDULE_START_HOURS` | 定时任务尝试时间段 | `18` |
| `SJA_ENCRYPTION_RETURN_URL` | 下单支付回跳地址 | 体育系统默认值 |

> 更多可覆盖项可在 `config.py` 中搜索 `os.getenv("SJA_...")`。

### Bot（`bot/.env`）

| 变量 | 说明 |
| --- | --- |
| `DRIVER` | NoneBot 驱动，默认 `~fastapi` |
| `NTQQ_WS_URL` / `NTQQ_HTTP_URL` | Napcat/QQ 频道的 WS/HTTP 地址 |
| `BOT_COMMAND_PREFIX` | 机器人命令前缀，默认 `!` |
| `LOG_LEVEL` | Bot 日志级别 |

### 前端（`frontend/.env.production`）

| 变量 | 说明 |
| --- | --- |
| `VITE_API_BASE_URL` | 指向后端 API 的完整 URL，例如 `https://your-domain.com/api` |
| `VITE_PORTAL_PASSWORD` | 门户密码页的口令 |

---

## 🔐 凭据与安全建议

- **双重入口保护**：推荐在反向代理（Nginx/Caddy）再加一层 Basic Auth 或 VPN/IP 白名单，配合前端门户密码双重防护。
- **HTTPS 强制**：生产环境务必使用证书（Let’s Encrypt 等），并开启 HSTS。
- **日志脱敏**：不要在日志中打印用户密码/Cookie。`deploy.env`、`config/users.json` 应存储在受限目录并定期备份。
- **Bot 接口安全**：若 Bot 与后端不在同一台机器上，建议配置 `BOT_ACCESS_TOKEN` 并在反向代理层做 IP 白名单。

---

## 🛠️ 常用命令

```bash
# 检查必要依赖（OCR、Node 等）
python sjtu_sports.py --check-deps

# CLI 登录 / 查询
python sjtu_sports.py cli login
python sjtu_sports.py cli slots --preset 13

# 启动 Bot（含热加载）
python sjtu_sports.py bot --hot-reload

# Web 控制台开发模式
cd frontend && npm run dev

# Web 控制台打包
cd frontend && npm run build
```

更多命令详见 `python sjtu_sports.py --help`。

---

## 📚 更多资料

- [docs/BOT_INTEGRATION_GUIDE.md](docs/BOT_INTEGRATION_GUIDE.md) – Bot/Napcat 集成说明
- [docs/guides/QUICK_START.md](docs/guides/QUICK_START.md) – 原始快速上手指南
- [docs/HOT_RELOAD_GUIDE.md](docs/HOT_RELOAD_GUIDE.md) – 热加载说明
- [docs/LOGIN_RETRY_GUIDE.md](docs/LOGIN_RETRY_GUIDE.md) – 登录重试机制

欢迎按照上述步骤部署，并结合自己的基础设施（Docker、systemd、CI/CD 等）扩展更稳定的上线流程。若遇到问题，查看 `deploy.env`、`config/users.json` 是否正确配置，或重新运行 `scripts/setup_env.sh` 生成新的配置模板。
