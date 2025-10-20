# 快速启动指南

## 🚀 快速开始

### 1. 环境准备

确保已安装 Python 3.10+ 和 Poetry：

```bash
# 安装 Poetry (如果未安装)
curl -sSL https://install.python-poetry.org | python3 -

# 或使用 pip
pip install poetry
```

### 2. 安装依赖

```bash
# 安装核心项目依赖
pip install httpx[http2] rich apscheduler tzlocal pycryptodome

# 安装机器人依赖
cd bot
poetry install
```

### 3. 配置环境

```bash
# 复制环境配置
cp bot/env.example bot/.env

# 编辑配置文件
nano bot/.env
```

配置 OneBot 连接信息：
```env
ONEBOT_WS_URL=ws://127.0.0.1:6700/ws
ONEBOT_HTTP_URL=http://127.0.0.1:6700
SERVICE_AUTH_COOKIE=your_cookie_here
```

### 4. 运行测试

```bash
# 测试服务层功能
python test_service_cli.py

# 测试机器人集成
cd bot
python test_integration.py
```

### 5. 启动机器人

```bash
cd bot
python run.py
```

## 📋 使用示例

### CLI 命令
```bash
# 查询时间段
python main.py slots --preset 13

# 立即预订
python main.py book-now --preset 13

# 直接下单
python main.py order --preset 13 --date 0 --st 18
```

### 机器人命令
```
查询 preset=13
查询 venue=学生中心 sport=羽毛球
帮助
```

## 🔧 开发调试

### 查看日志
```bash
tail -f bot/logs/bot.log
```

### 调试模式
```bash
# 设置调试日志级别
export LOG_LEVEL=DEBUG
cd bot
python run.py
```

## 📚 更多信息

- 详细文档: [bot/README.md](bot/README.md)
- 实施总结: [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md)
- 项目配置: [config.py](config.py)

## 🆘 常见问题

### Q: 机器人无法连接 OneBot？
A: 检查 `.env` 文件中的 `ONEBOT_WS_URL` 和 `ONEBOT_HTTP_URL` 配置

### Q: 查询失败？
A: 检查 `SERVICE_AUTH_COOKIE` 是否有效

### Q: 插件不工作？
A: 确保插件文件在 `bot/plugins/` 目录下，且文件名正确

## 🎯 下一步

1. 完善更多插件功能
2. 添加用户权限管理
3. 实现自动预订功能
4. 部署到生产环境
