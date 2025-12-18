# SJTU Sports Auto-Booking 部署文档

## 📋 目录

1. [系统概述](#系统概述)
2. [服务器环境配置](#服务器环境配置)
3. [系统架构](#系统架构)
4. [服务配置与启动](#服务配置与启动)
5. [网络配置](#网络配置)
6. [监控与日志](#监控与日志)
7. [故障排查](#故障排查)
8. [性能优化](#性能优化)
9. [维护与更新](#维护与更新)

---

## 系统概述

### 服务组成

1. **后端 FastAPI 服务** (sja-api.service)
   - 端口: 8000
   - 功能: 提供 RESTful API，处理预订请求、定时任务、监控等
   - 工作目录: `/home/deploy/sJAutoSport`
   - 进程ID: 查看 `systemctl status sja-api.service`

2. **NoneBot QQ 机器人服务** (sja-bot.service)
   - 端口: 8080
   - 功能: QQ 消息接收与发送，与 NapCat 交互
   - WebSocket: `ws://172.17.0.1:8080/onebot/v11/ws`
   - 工作目录: `/home/deploy/sJAutoSport`

3. **NapCat Docker 容器** (napcat)
   - HTTP API: 3000 (需要 Bearer token: 123456)
   - WebUI: 6099
   - 功能: QQ 客户端，与 NoneBot 建立反向 WebSocket 连接
   - 容器名称: `napcat`

4. **Caddy 反向代理** (caddy.service)
   - 功能: HTTPS 终端，代理前端和后端 API
   - 配置文件: `/etc/caddy/Caddyfile`

---

## 服务器环境配置

### 系统信息

- 操作系统: Ubuntu 22.04
- Python 版本: 3.10.18
- 虚拟环境: `/root/miniconda3/envs/sJAutoSport`
- 工作目录: `/home/deploy/sJAutoSport`
- 部署用户: `deploy` (前端), `root` (系统服务)

### 环境变量配置

配置文件: `/etc/sja/env`

```bash
SJA_ENV=production
SJA_BASE_URL=https://sports.sjtu.edu.cn
BOT_HTTP_URL=http://127.0.0.1:3000
BOT_ACCESS_TOKEN=123456
SJA_NOTIFICATION_GROUPS=YOUR_GROUP_ID
SJA_NOTIFICATION_USERS=YOUR_QQ_ID
SJA_ENABLE_NOTIFICATION=true
SJABOT_CREDENTIAL_STORE=/home/deploy/sJAutoSport/data/credentials.json
SJA_USERS_FILE=/home/deploy/sJAutoSport/config/users.json
```

### Python 环境

```bash
# 激活虚拟环境
conda activate sJAutoSport

# 验证 Python 版本
python --version  # 应为 3.10.18

# 验证依赖
pip list
```

---

## 系统架构

### 服务架构图

```
┌─────────────────────────────────────────────────────────┐
│                    用户浏览器                            │
│                  (前端 React)                            │
└──────────────────────┬──────────────────────────────────┘
                       │ HTTPS (443)
                       ▼
┌─────────────────────────────────────────────────────────┐
│              Caddy 反向代理 (caddy.service)             │
│              /etc/caddy/Caddyfile                       │
└─────────┬────────────────────┬──────────────────────────┘
          │                    │
          │ API                │ 前端静态文件
          ▼                    ▼
┌─────────────────┐  ┌──────────────────────────────┐
│ FastAPI 后端    │  │ /opt/sja/frontend/dist/     │
│ Port: 8000      │  │                              │
│ sja-api.service │  │                              │
└────────┬────────┘  └──────────────────────────────┘
         │
         ├─┬──────────────────────────────────────┐
         │ │                                      │
         ▼ ▼                                      ▼
┌─────────────────┐         ┌──────────────────────────┐
│ NoneBot Bot      │────────│ NapCat Docker (napcat) │
│ Port: 8080       │ WS     │ HTTP: 3000, UI: 6099   │
│ sja-bot.service │        │ QQ 客户端               │
└─────────────────┘        └──────────────────────────┘
```

### 端口分配

| 服务 | 端口 | 协议 | 用途 |
|------|------|------|------|
| Caddy | 80, 443 | HTTP/HTTPS | 反向代理 |
| FastAPI | 8000 | HTTP | 后端 API |
| NoneBot | 8080 | WebSocket | QQ 机器人 |
| NapCat HTTP | 3000 | HTTP | NapCat API |
| NapCat WebUI | 6099 | HTTP | NapCat 管理界面 |

---

## 服务配置与启动

### 1. 后端 FastAPI 服务

**配置文件**: `/etc/systemd/system/sja-api.service`

```ini
[Unit]
Description=SJTU Sports FastAPI service
After=network.target

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=/home/deploy/sJAutoSport
EnvironmentFile=/etc/sja/env
ExecStart=/root/miniconda3/envs/sJAutoSport/bin/python -m uvicorn web_api.app:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
Environment="LOG_LEVEL=INFO"

[Install]
WantedBy=multi-user.target
```

**启动命令**:
```bash
systemctl daemon-reload
systemctl start sja-api.service
systemctl enable sja-api.service  # 设置开机自启
```

**状态检查**:
```bash
systemctl status sja-api.service
journalctl -u sja-api.service -f  # 实时日志
curl http://localhost:8000/api/system/health  # 健康检查
```

### 2. NoneBot QQ 机器人服务

**配置文件**: `/etc/systemd/system/sja-bot.service`

```ini
[Unit]
Description=SJTU Sports NoneBot service
After=network.target sja-api.service

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=/home/deploy/sJAutoSport
EnvironmentFile=/etc/sja/env
EnvironmentFile=/home/deploy/sJAutoSport/bot/.env
ExecStart=/root/miniconda3/envs/sJAutoSport/bin/python sjtu_sports.py bot
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
Environment="LOG_LEVEL=INFO"

[Install]
WantedBy=multi-user.target
```

**启动命令**:
```bash
systemctl daemon-reload
systemctl start sja-bot.service
systemctl enable sja-bot.service
```

**状态检查**:
```bash
systemctl status sja-bot.service
journalctl -u sja-bot.service -f
netstat -tlnp | grep :8080
```

### 3. NapCat Docker 容器

**配置文件**: `/etc/napcat/config/`

**启动命令**:
```bash
docker start napcat
docker logs -f napcat
```

**状态检查**:
```bash
docker ps | grep napcat
curl -H "Authorization: Bearer 123456" http://localhost:3000/
```

**NapCat WebSocket 配置**:
- 配置文件: `/etc/napcat/config/onebot11_*.json`
- 连接地址: `ws://172.17.0.1:8080/onebot/v11/ws`
- Token: 123456

---

## 网络配置

### 1. Docker 网络

**网关**: `172.17.0.1` (Docker 默认网桥)

```bash
# 查看 Docker 网络
docker network inspect bridge

# 重要: NapCat 容器必须使用 172.17.0.1 访问宿主机服务
# 不能使用 host.docker.internal (这是 Docker Desktop 的特性)
```

### 2. 防火墙规则

```bash
# 开放必要端口
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 8000/tcp
ufw allow 8080/tcp
ufw allow 3000/tcp
ufw allow 6099/tcp

# 检查状态
ufw status
```

### 3. 反向代理配置

**配置文件**: `/etc/caddy/Caddyfile`

```caddy
example.com {
    encode zstd gzip

    handle /api/* {
        reverse_proxy 127.0.0.1:8000
    }

    handle /webui* {
        reverse_proxy 127.0.0.1:6099
    }

    handle {
        root * /opt/sja/frontend/dist
        try_files {path} /index.html
        file_server
    }
}
```

**重载配置**:
```bash
caddy reload --config /etc/caddy/Caddyfile
systemctl restart caddy
```

---

## 监控与日志

### 服务日志

**查看所有服务状态**:
```bash
systemctl status sja-api.service sja-bot.service caddy.service
```

**实时日志**:
```bash
# API 服务日志
journalctl -u sja-api.service -f

# Bot 服务日志
journalctl -u sja-bot.service -f

# 所有服务日志
journalctl -u 'sja-*' -f
```

**查看历史日志**:
```bash
# 最近的日志
journalctl -u sja-api.service --no-pager -n 100

# 特定时间段的日志
journalctl -u sja-api.service --since "2025-10-26 12:00:00" --until "2025-10-26 12:05:00"

# 查找特定内容
journalctl -u sja-api.service | grep "抢气膜"
```

### NapCat 容器日志

```bash
docker logs napcat --tail 50
docker logs napcat -f
```

### 应用日志文件

```bash
/home/deploy/sJAutoSport/logs/bot.log
```

---

## 故障排查

### 1. 服务无法启动

**症状**: `systemctl status` 显示 `failed`

**排查步骤**:
```bash
# 查看详细错误
journalctl -u sja-api.service -n 50

# 常见错误:
# - Permission denied: 检查文件权限和用户配置
# - ModuleNotFoundError: 检查 Python 依赖
# - Port already in use: 端口被占用
```

**解决方案**:
```bash
# 权限问题
sudo chown -R root:root /home/deploy/sJAutoSport
sudo chmod -R 755 /home/deploy/sJAutoSport

# 端口占用
netstat -tlnp | grep :8000
kill <PID>

# 重新安装依赖
conda activate sJAutoSport
pip install -r requirements.txt
```

### 2. Bot 无法连接 NapCat

**症状**: Bot 日志显示连接失败

**排查步骤**:
```bash
# 检查 NapCat 容器状态
docker ps | grep napcat

# 检查 WebSocket 连接配置
docker exec napcat cat /app/napcat/config/onebot11_*.json | grep url

# 检查网络连接
docker exec napcat ping 172.17.0.1
```

**解决方案**:
```bash
# 重启 NapCat
docker restart napcat

# 检查 Bot 服务
systemctl restart sja-bot.service
```

### 3. 12点抢票失败

**症状**: 定时任务执行但未抢到票

**问题分析**:
- 系统在 12:00:00 开始执行
- 大量请求导致系统响应延迟
- 真正下单时已经是 12:00:01+

**优化方案** (已实施):
1. 提前 2 秒预热
2. 在 11:59:58 开始准备
3. 准点前 0.5 秒开始最后一次尝试
4. 并发多时间段抢票
5. 减少重试延迟（0.3 秒 vs 1 秒）

**验证**:
```bash
# 查看任务日志
journalctl -u sja-api.service | grep "schedule:抢气膜"
```

### 4. 前端构建失败

**症状**: `npm run build` 失败

**常见错误**: 找不到文件或模块

**排查步骤**:
```bash
cd /home/deploy/sJAutoSport/frontend
npm run build
```

**解决方案**:
```bash
# 清理并重新安装
rm -rf node_modules .vite .eslintcache
npm ci  # 或 npm install

# 重新构建
npm run build
```

---

## 性能优化

### 1. 12点抢票优化

**实施日期**: 2025-10-26

**优化内容**:
- ✅ 预热机制: 提前 2 秒准备
- ✅ 并发抢票: 同时抢多个时间段
- ✅ 减少延迟: 重试间隔 0.3 秒
- ✅ 减少重试: 12 点任务只试 3 次

**代码位置**: `sja_booking/service.py:1385-1550`

### 2. 系统资源监控

```bash
# CPU 和内存使用
top
htop

# 服务资源使用
systemctl status sja-api.service
# 查看 Tasks 和 Memory 信息

# 端口监听
netstat -tlnp | grep -E ":(8000|8080|3000|6099)"
```

### 3. 数据库性能

```bash
# SQLite 数据库位置
/home/deploy/sJAutoSport/data/

# 查看数据库大小
du -sh /home/deploy/sJAutoSport/data/*.db
```

---

## 维护与更新

### 1. 更新代码

```bash
# 进入项目目录
cd /home/deploy/sJAutoSport

# 拉取最新代码 (如果需要)
# git pull

# 重启服务
systemctl restart sja-api.service
systemctl restart sja-bot.service

# 验证
systemctl status sja-api.service sja-bot.service
```

### 2. 前端部署

```bash
cd /home/deploy/sJAutoSport/frontend

# 构建
npm run build

# 部署到 nginx
sudo cp -r dist/* /opt/sja/frontend/dist/
sudo chmod -R 755 /opt/sja/frontend/dist
sudo systemctl restart caddy
```

### 3. 备份

```bash
# 备份数据库
cp -r /home/deploy/sJAutoSport/data /backup/data_$(date +%Y%m%d)

# 备份配置
cp /etc/sja/env /backup/env_$(date +%Y%m%d)
cp /etc/systemd/system/sja-*.service /backup/services_$(date +%Y%m%d)/
```

### 4. 清理日志

```bash
# 清理 journald 日志 (保留最近 7 天)
journalctl --vacuum-time=7d

# 清理 Docker 日志
docker system prune -a
```

---

## 快速参考命令

### 服务管理

```bash
# 查看所有服务状态
systemctl status sja-api.service sja-bot.service caddy.service

# 重启服务
systemctl restart sja-api.service
systemctl restart sja-bot.service
systemctl restart caddy.service

# 查看日志
journalctl -u sja-api.service -f
journalctl -u sja-bot.service -f
```

### Docker 管理

```bash
# 容器状态
docker ps | grep napcat

# 查看日志
docker logs napcat -f

# 重启容器
docker restart napcat
```

### 网络检查

```bash
# 端口监听
netstat -tlnp | grep -E ":(8000|8080|3000)"

# 测试 API
curl http://localhost:8000/api/system/health
curl -H "Authorization: Bearer 123456" http://localhost:3000/
```

### 前端管理

```bash
# 构建前端
cd /home/deploy/sJAutoSport/frontend
npm run build

# 部署
sudo cp -r dist/* /opt/sja/frontend/dist/
sudo chmod -R 755 /opt/sja/frontend/dist
```

---

## 重要文件位置

```
配置文件:
  /etc/sja/env                    # 环境变量
  /etc/systemd/system/sja-api.service
  /etc/systemd/system/sja-bot.service
  /etc/caddy/Caddyfile
  
数据目录:
  /home/deploy/sJAutoSport/data/  # 数据库和凭证
  /home/deploy/sJAutoSport/logs/  # 应用日志
  /opt/sja/frontend/dist/         # 前端静态文件
  
代码目录:
  /home/deploy/sJAutoSport/       # 项目根目录
  /home/deploy/sJAutoSport/frontend/  # 前端代码
  
Docker:
  napcat                           # NapCat 容器名称
  /opt/napcat/                     # NapCat 配置目录
```

---

## 联系方式与支持

- **项目仓库**: GitHub (如果适用)
- **文档**: `/home/deploy/sJAutoSport/docs/`
- **问题反馈**: 查看日志文件

---

**最后更新**: 2025-10-26
**维护者**: SJTU Sports Auto-Booking Team

