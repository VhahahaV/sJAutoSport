# SJTU Sports CLI

Automation helpers for the Shanghai Jiao Tong University venue booking platform. The toolkit talks to the backend directly over HTTP, so you can query availability, monitor slots, and book without keeping a browser open.

## Features

- Pure HTTP workflow (no browser automation) with optional credential login automation.
- **🆕 多用户Token管理**：支持多个用户同时预订，智能切换避免频率限制
- **🆕 批量预订功能**：一次命令为多个用户预订场地
- **🆕 用户筛选功能**：可指定特定用户或排除某些用户
- Modular components for API access, monitoring, scheduling, and endpoint discovery.
- Multiple booking modes: one-off queries, continuous monitoring with optional auto-book, and daily scheduling.
- Configurable defaults and presets maintained in `config.py`.

## 🚀 快速开始

```bash
# 1. 克隆项目
git clone <repository-url>
cd sJAutoSport

# 2. 安装依赖（macOS）
brew install tesseract
conda create -n sJAutoSport python=3.10
conda activate sJAutoSport
pip install -r requirements.txt

# 3. 登录并开始使用
python main.py login
python main.py list  # 查看可用场馆
python main.py slots --preset 13  # 查看南洋北苑健身房时间段
```

## 📚 Documentation

所有文档已按功能分类整理到 `docs/` 目录中：

- **[使用指南](docs/guides/)** - 快速开始、自动抢票、机器人系统使用指南
- **[项目总结](docs/summaries/)** - 功能实施总结、技术架构说明
- **[API文档](docs/api/)** - 接口文档和开发指南
- **[示例代码](docs/examples/)** - 使用示例和代码片段

> 🚀 **全新 NapCatQQ 机器人适配**  
> 项目内置的 QQ 交互默认使用 NapCatQQ（基于官方 NTQQ 的 OneBot 适配器）。请按照以下指引部署并配置：
> - [Linux/Wine 部署指引](docs/guides/bot_setup_linux.md)
> - [macOS/Wine 部署指引](docs/guides/bot_setup_macos.md)
> - [Windows 部署指引](docs/guides/bot_setup_windows.md)
>
> NapCatQQ 启动后，验证码协同、余票查询、任务管理等功能即可通过 QQ 机器人直接完成。

## Repository Layout

```
sja_booking/
sja_booking/
|-- api.py          # SportsAPI: server endpoints and response parsing
|-- monitor.py      # SlotMonitor: polling and rendering logic
|-- scheduler.py    # schedule_daily wrapper around APScheduler
|-- discovery.py    # discover_endpoints helper
|-- models.py       # Shared dataclasses
|-- cli.py          # Command line entrypoints (argparse + rich)
|-- __init__.py
config.py           # Runtime configuration (credentials, endpoints, presets)
main.py             # CLI entrypoint
README.md           # This file
```

## Installation

### 1. 创建 Python 环境

```bash
conda create -n sJAutoSport python=3.10
conda activate sJAutoSport
```

### 2. 安装 Python 依赖

```bash
pip install httpx[http2] apscheduler rich tzlocal pycryptodome
# OCR 和加密支持（推荐）
pip install pytesseract opencv-python cryptography
```

### 3. 安装系统依赖

#### macOS
```bash
# 安装 Tesseract OCR
brew install tesseract

# 可选：安装中文语言包
brew install tesseract-lang
```

#### Ubuntu/Debian
```bash
# 安装 Tesseract OCR
sudo apt-get update
sudo apt-get install tesseract-ocr

# 可选：安装中文语言包
sudo apt-get install tesseract-ocr-chi-sim tesseract-ocr-chi-tra
```

#### Windows
1. 下载 Tesseract 安装包：https://github.com/UB-Mannheim/tesseract/wiki
2. 安装后将 Tesseract 路径添加到系统 PATH 环境变量
3. 或者设置环境变量：`set TESSDATA_PREFIX=C:\Program Files\Tesseract-OCR\tessdata`

### 4. 验证安装

```bash
# 验证 Tesseract 安装
tesseract --version

# 验证 Python 环境
python main.py --help
```

## Configuration (`config.py`)

1. Copy the complete `Cookie` header (and optional `Authorization`) from DevTools after a successful request, and paste it into `AUTH`.
2. Adjust `ENDPOINTS` if the platform deploys a different path structure.
3. Fill in `TARGET` with your favourite venue/field and scheduling preferences. Set `date_offset=None` to fetch all available dates automatically.
4. Edit `MONITOR_PLAN` if you prefer a different polling interval or default auto-book behaviour.
5. Maintain `PRESET_TARGETS` with frequently used venue/field combinations so users can rely on the simpler `--preset` flag.

Example preset entry:

```python
PRESET_TARGETS = [
    PresetOption(
        index=1,
        venue_id="73b17f69-6ed9-481f-b157-5e0606a55fd5",
        venue_name="南洋北苑健身房",
        field_type_id="dad366b3-7db9-4043-865c-7177aff83efa",
        field_type_name="健身房",
    ),
]
```

## 🆕 多用户Token管理

### 配置多用户

在 `config.py` 中配置多个用户的认证信息：

```python
AUTH = AuthConfig(
    users=[
        UserAuth(
            nickname="用户1",
            cookie="JSESSIONID=第一个用户的cookie",
            token=None,
            username=None,
            password=None,
        ),
        UserAuth(
            nickname="用户2", 
            cookie="JSESSIONID=第二个用户的cookie",
            token=None,
            username="用户名2",
            password="密码2",
        ),
    ]
)
```

### 多用户命令

```bash
# 列出所有用户
python main.py list-users

# 验证用户配置
python main.py validate-users

# 切换到指定用户
python main.py switch-user 用户1

# 为所有用户预订
python main.py order --preset 13 --date 1 --st 17

# 为指定用户预订
python main.py order --preset 13 --date 1 --st 17 --users "用户1,用户2"

# 多用户监控
python main.py monitor --preset 13 --interval 300 --date 2 --auto-book --users "用户1,用户2"
```

### 智能切换机制

- 当遇到频率限制时，自动切换到下一个用户
- 支持批量预订，提高成功率
- 简洁的配置结构，只需配置users列表

详细使用指南请参考：[多用户管理指南](MULTI_USER_GUIDE.md)

## Credential Management & Login

Use the dedicated login/logout commands to maintain a valid session without manually copying cookies every day.

1. **Supply credentials** via environment variables (`SJABOT_USER`, `SJABOT_PASS`) or CLI flags (`--username`, `--password`). Missing values trigger interactive prompts (password uses `getpass`).
2. **Run the login flow**:
   ```bash
   python main.py login
   python main.py login --username 2022xxxx --no-ocr  # 手动输入验证码
   ```
3. **Captcha resolution**
   - **OCR 首选**：需要安装 `pytesseract` 和系统 Tesseract OCR（配合 `opencv-python` 提升效果）
   - **系统依赖**：macOS 使用 `brew install tesseract`，Ubuntu 使用 `sudo apt-get install tesseract-ocr`
   - **兜底方案**：当 OCR 置信度不足时，CLI 会将验证码保存至临时文件并提示手动输入
   - **外部协同**：传入 `--no-prompt` 可改为外部协同（如 QQ 机器人）
4. **持久化 Cookie**
   - 登录成功后，Cookie 会（在提供 `SJABOT_SECRET` 且安装 `cryptography` 时）加密存储于 `~/.sja/credentials.json`。
   - 其他命令自动加载该 Cookie；执行 `python main.py logout` 可清理持久化会话。

> **重要**：`pytesseract`、`opencv-python` 和 `cryptography` 是实现自动验证码识别和安全存储的关键依赖，强烈建议安装以获得完整功能。

## CLI Commands

All functionality is exposed through `python main.py <command> [options]`.

| Command       | Description                                             | Common options |
| ------------- | ------------------------------------------------------- | -------------- |
| `login`       | 执行账号密码登录，持久化 Cookie（默认使用 OCR+命令行兜底）  | `--username`, `--password`, `--no-ocr` |
| `logout`      | 清理本地持久化 Cookie                                       | – |
| `list`        | 显示场馆和运动类型的序号映射表（推荐使用）                | – |
| `presets`     | Show the preset table defined in `config.PRESET_TARGETS`| – |
| `catalog`     | Enumerate venues and field types with generated indices | `--pages`, `--size` |
| `userinfo`    | Validate saved cookies/tokens and show account info | – |
| `discover`    | Scan the base page and JS assets for candidate API paths| `--base` |
| `venues`      | List venues from the official API                       | `--keyword`, `--page`, `--size` |
| `slots`       | Query slot availability and render a table              | `--preset`, `--date`, `--start-hour`, `--show-full` |
| `monitor`     | Continuously poll for availability (optionally autobook)| `--preset`, `--date`, `--interval`, `--auto-book` |
| `book-now`    | Single booking attempt using the target filters         | `--preset`, `--date`, `--start-hour`, `--duration-hours` |
| `order`       | 直接下单预订指定时间段（推荐使用）                      | `--preset`, `--date`, `--st`, `--end-time` |
| `schedule`    | Daily scheduled booking attempt                         | `--preset`, `--hour`, `--minute`, `--second` |

### 快速开始 - 使用序号选择

1. 运行 `python main.py list` 查看所有可用的场馆和运动类型及其序号
2. 使用序号进行预约，例如：

   ```bash
   # 查看南洋北苑健身房的可用时间段
   python main.py slots --preset 13
   
   # 查看明天的可用时间段
   python main.py slots --preset 13 --date 1
   
   # 查看今天14:00-15:00的时间段
   python main.py slots --preset 13 --date 0 --start-hour 14
   
   # 监控霍英东体育馆羽毛球场地
   python main.py monitor --preset 5 --interval 30 --auto-book
   
   # 立即预约学生中心篮球场
   python main.py book-now --preset 1
   
   # 直接下单预订指定时间段（简化格式）
   python main.py order --preset 13 --date 0 --st 20
   python main.py order --preset 14 --date 1 --st 17
   ```

这样就不需要记住复杂的 `--venue-id` 或 `--field-type-id` 了！

### 🚀 简化命令格式

为了提升用户体验，所有命令都支持简化的参数格式：

#### 📅 日期格式
- **数字格式**：`0-8` 表示日期偏移量
  - `0` = 今天
  - `1` = 明天  
  - `7` = 下周今天
  - `8` = 下周明天
- **标准格式**：`YYYY-MM-DD`（如 `2025-01-15`）

#### ⏰ 时间格式
- **数字格式**：`0-23` 表示小时
  - `14` = 14:00
  - `21` = 21:00
- **标准格式**：`HH:MM`（如 `14:00`）

#### 🎯 命令示例对比

| 功能 | 传统格式 | 简化格式 |
|------|----------|----------|
| 查看今天时间段 | `--date 2025-10-19` | `--date 0` |
| 查看明天时间段 | `--date 2025-10-20` | `--date 1` |
| 指定开始时间 | `--start-time 14:00` | `--st 14` |
| 下单预订 | `--date 2025-10-19 --start-time 14:00 --end-time 15:00` | `--date 0 --st 14` |

#### ✨ 自动功能
- **自动计算结束时间**：如果不指定 `--end-time`，系统会自动设置为开始时间+1小时
- **智能时间解析**：支持数字和标准格式混合使用

### 传统工作流程

1. Run `python main.py catalog` to discover the latest venue/field combinations and their generated indices.
2. Run `python main.py presets` to view the numbered venue/sport list that you maintain in `config.py`.
3. Use the sequence number with other commands, for example:

   ```bash
   python main.py slots --preset 1 --show-full
   python main.py monitor --preset 1 --interval 30 --auto-book
   ```

This removes the need to memorise UUID-style `--venue-id` or `--field-type-id` values.

### QQ 机器人交互速查

部署 NapCatQQ 后，可直接在 QQ（私聊或群聊）使用以下指令与系统交互：

- `登录` → 根据提示回复 `验证码 123456` 完成 Cookie 登录  
- `登录状态` / `系统状态` / `任务列表` / `取消任务`：查看与管理后台任务  
- `查询 preset=13` / `预订 preset=13 date=0 time=18`：查询并预订场馆  
- `监控 preset=5 time=21 auto`：启动余票监控，可选 `auto` 自动抢票  
- `管理帮助` / `系统帮助`：查看机器人全部命令说明

## Monitoring & Auto-booking

- `SlotMonitor` resolves the venue/field (using IDs, keywords, or presets), fetches all available dates, and aggregates slot availability by time.
- Output tables list venue, date, time, total remaining capacity, and price. Slots with zero remaining capacity are omitted by default.
- With `--auto-book`, the monitor attempts to submit the order immediately once a qualifying slot is found.

## Tips

- Start with `python main.py userinfo` to ensure cookies/tokens are still valid.
- When you add a new venue/sport pair to `PRESET_TARGETS`, rerun `python main.py presets` (and update the table below) so everyone can reference the latest indices.
- Use `python main.py catalog` to export the full venue/sport list directly from the platform when building or verifying presets.

## 场馆和运动类型映射表

| 序号 | 场馆名称 | 运动类型 | 使用示例 |
|------|----------|----------|----------|
| 1 | 学生中心 | 交谊厅 | `python main.py slots --preset 1` |
| 2 | 学生中心 | 台球 | `python main.py slots --preset 2` |
| 3 | 学生中心 | 学生中心健身房 | `python main.py slots --preset 3` |
| 4 | 学生中心 | 舞蹈 | `python main.py slots --preset 4` |
| 5 | 气膜体育中心 | 羽毛球 | `python main.py slots --preset 5` |
| 6 | 气膜体育中心 | 篮球 | `python main.py slots --preset 6` |
| 7 | 子衿街学生活动中心 | 舞蹈 | `python main.py slots --preset 7` |
| 8 | 子衿街学生活动中心 | 健身房 | `python main.py slots --preset 8` |
| 9 | 子衿街学生活动中心 | 桌游室 | `python main.py slots --preset 9` |
| 10 | 子衿街学生活动中心 | 钢琴 | `python main.py slots --preset 10` |
| 11 | 子衿街学生活动中心 | 烘焙 | `python main.py slots --preset 11` |
| 12 | 子衿街学生活动中心 | 琴房兼乐器 | `python main.py slots --preset 12` |
| 13 | 南洋北苑健身房 | 健身房 | `python main.py slots --preset 13` |
| 14 | 南区体育馆 | 乒乓球 | `python main.py slots --preset 14` |
| 15 | 南区体育馆 | 排球 | `python main.py slots --preset 15` |
| 16 | 南区体育馆 | 篮球 | `python main.py slots --preset 16` |
| 17 | 胡法光体育场 | 舞蹈 | `python main.py slots --preset 17` |
| 18 | 霍英东体育中心 | 羽毛球 | `python main.py slots --preset 18` |
| 19 | 霍英东体育中心 | 篮球 | `python main.py slots --preset 19` |
| 20 | 霍英东体育中心 | 健身房 | `python main.py slots --preset 20` |
| 21 | 徐汇校区体育馆 | 健身房 | `python main.py slots --preset 21` |
| 22 | 徐汇校区体育馆 | 羽毛球 | `python main.py slots --preset 22` |
| 23 | 徐汇校区体育馆 | 乒乓球 | `python main.py slots --preset 23` |
| 24 | 致远游泳健身馆 | 乒乓球 | `python main.py slots --preset 24` |
| 25 | 徐汇校区网球场 | 网球 | `python main.py slots --preset 25` |
| 26 | 徐汇校区足球场 | 足球 | `python main.py slots --preset 26` |
| 27 | 张江校区体育运动中心 | 无运动类型 | `python main.py slots --preset 27` |
| 28 | 学创船建分中心 | 创新实践 | `python main.py slots --preset 28` |
| 29 | 学创空天分中心 | 创新实践 | `python main.py slots --preset 29` |
| 30 | 学创机动分中心 | 创新实践 | `python main.py slots --preset 30` |
| 31 | 致远游泳馆东侧足球场 | 足球 | `python main.py slots --preset 31` |
| 32 | 东区网球场 | 网球 | `python main.py slots --preset 32` |
| 33 | 笼式足球场 | 足球 | `python main.py slots --preset 33` |
| 34 | 胡晓明网球场 | 网球 | `python main.py slots --preset 34` |

> **提示**: 运行 `python main.py list` 可以查看最新的映射表和使用示例。
