# SJTU Sports CLI

Automation helpers for the Shanghai Jiao Tong University venue booking platform. The toolkit talks to the backend directly over HTTP, so you can query availability, monitor slots, and book without keeping a browser open.

## Features

- Pure HTTP workflow (no browser automation).
- Modular components for API access, monitoring, scheduling, and endpoint discovery.
- Multiple booking modes: one-off queries, continuous monitoring with optional auto-book, and daily scheduling.
- Configurable defaults and presets maintained in `config.py`.

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

```bash
conda create -n sJAutoSport python=3.10
pip install httpx[http2] apscheduler rich tzlocal pycryptodome
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

## CLI Commands

All functionality is exposed through `python main.py <command> [options]`.

| Command       | Description                                             | Common options |
| ------------- | ------------------------------------------------------- | -------------- |
| `list`        | 显示场馆和运动类型的序号映射表（推荐使用）                | – |
| `presets`     | Show the preset table defined in `config.PRESET_TARGETS`| – |
| `catalog`     | Enumerate venues and field types with generated indices | `--pages`, `--size` |
| `debug-login` | Validate the current cookies/token and show account info| – |
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
   python main.py order --preset 13 --date 0 --st 21
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

## Monitoring & Auto-booking

- `SlotMonitor` resolves the venue/field (using IDs, keywords, or presets), fetches all available dates, and aggregates slot availability by time.
- Output tables list venue, date, time, total remaining capacity, and price. Slots with zero remaining capacity are omitted by default.
- With `--auto-book`, the monitor attempts to submit the order immediately once a qualifying slot is found.

## Tips

- Start with `python main.py debug-login` to ensure cookies/tokens are still valid.
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




