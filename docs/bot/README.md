# SJTU Sports Booking Bot

体育预订机器人 - OneBot 适配器

## 功能特性

- 🏓 查询体育场馆可用时间段
- 🎯 支持预设场馆快速查询
- 📅 灵活的日期和时间参数
- 🤖 友好的聊天机器人界面
- 🔄 实时监控和自动预订（计划中）

## 安装和运行

### 1. 安装依赖

```bash
cd bot
pip install poetry
poetry install
```

### 2. 配置环境

复制环境配置文件：
```bash
cp env.example .env
```

编辑 `.env` 文件，配置 OneBot 连接信息：
```env
ONEBOT_WS_URL=ws://127.0.0.1:6700/ws
ONEBOT_HTTP_URL=http://127.0.0.1:6700
SERVICE_AUTH_COOKIE=your_cookie_here
```

### 3. 运行机器人

```bash
poetry run python -m bot
```

或者使用脚本：
```bash
poetry run sja-bot
```

## 使用说明

### 基本命令

- `查询` - 显示帮助信息
- `查询 preset=13` - 查询预设场馆13的时间段
- `查询 venue=学生中心 sport=羽毛球` - 查询指定场馆和运动类型
- `查询 preset=5 date=1 time=21` - 查询明天21点的预设场馆5

### 参数说明

- `preset=数字` - 使用预设场馆（推荐）
- `venue=场馆名` - 指定场馆名称
- `sport=运动类型` - 指定运动类型
- `date=数字` - 指定日期（0=今天，1=明天）
- `time=数字` - 指定开始时间（24小时制）

### 常用预设

| 序号 | 场馆 | 运动类型 |
|------|------|----------|
| 1 | 学生中心 | 交谊厅 |
| 2 | 学生中心 | 台球 |
| 3 | 学生中心 | 健身房 |
| 4 | 学生中心 | 舞蹈 |
| 5 | 气膜体育中心 | 羽毛球 |
| 6 | 气膜体育中心 | 篮球 |
| 13 | 南洋北苑健身房 | 健身房 |
| 18 | 霍英东体育中心 | 羽毛球 |
| 19 | 霍英东体育中心 | 篮球 |
| 20 | 霍英东体育中心 | 健身房 |

## 开发说明

### 项目结构

```
bot/
├── bot.py              # 主程序
├── nb_config.py        # NoneBot 配置
├── pyproject.toml      # 项目配置
├── env.example         # 环境配置示例
├── plugins/            # 插件目录
│   ├── __init__.py
│   └── query_slots.py  # 查询时间段插件
└── README.md
```

### 添加新插件

1. 在 `plugins/` 目录下创建新的 Python 文件
2. 使用 NoneBot 的装饰器定义命令处理器
3. 调用 `sja_booking.service` 模块的服务层接口

### 服务层集成

机器人通过 `sja_booking.service` 模块与核心业务逻辑交互：

```python
from sja_booking.service import list_slots, order_once, start_monitor

# 查询时间段
result = await list_slots(preset=13)

# 执行预订
result = await order_once(preset=13, date="0", start_time="18")

# 启动监控
result = await start_monitor("monitor_1", preset=13, auto_book=True)
```

## 许可证

MIT License
