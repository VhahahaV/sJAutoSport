# 快速参考卡片

## 🚀 服务管理

### 查看状态
```bash
systemctl status sja-api.service sja-bot.service
```

### 启动服务
```bash
systemctl start sja-api.service
systemctl start sja-bot.service
```

### 重启服务
```bash
systemctl restart sja-api.service
systemctl restart sja-bot.service
```

### 停止服务
```bash
systemctl stop sja-api.service
systemctl stop sja-bot.service
```

---

## 📋 日志查看

### 实时日志
```bash
# API 服务
journalctl -u sja-api.service -f

# Bot 服务
journalctl -u sja-bot.service -f

# 所有服务
journalctl -u 'sja-*' -f
```

### 最近日志
```bash
journalctl -u sja-api.service -n 50
```

### 搜索特定内容
```bash
journalctl -u sja-api.service | grep "抢气膜"
```

---

## 🐳 Docker 管理

### NapCat 容器
```bash
docker ps | grep napcat
docker logs napcat -f
docker restart napcat
```

---

## 🌐 网络检查

### 端口监听
```bash
netstat -tlnp | grep -E ":(8000|8080|3000)"
```

### API 健康检查
```bash
curl http://localhost:8000/api/system/health
```

### NapCat API 测试
```bash
curl -H "Authorization: Bearer 123456" http://localhost:3000/
```

---

## 🔧 故障排查

### 权限问题
```bash
sudo chown -R root:root /home/deploy/sJAutoSport
sudo chmod -R 755 /home/deploy/sJAutoSport
```

### 端口占用
```bash
netstat -tlnp | grep :8000
kill <PID>
```

### 重新加载配置
```bash
systemctl daemon-reload
systemctl restart sja-api.service
```

---

## 📦 前端部署

### 构建前端
```bash
cd /home/deploy/sJAutoSport/frontend
npm run build
```

### 部署前端
```bash
sudo cp -r dist/* /opt/sja/frontend/dist/
sudo chmod -R 755 /opt/sja/frontend/dist
sudo systemctl restart caddy
```

---

## 🔑 关键信息

### 环境变量文件
```bash
/etc/sja/env
```

### 服务配置文件
```bash
/etc/systemd/system/sja-api.service
/etc/systemd/system/sja-bot.service
```

### 工作目录
```bash
/home/deploy/sJAutoSport
```

### Python 环境
```bash
/root/miniconda3/envs/sJAutoSport/bin/python
```

---

## 🎯 常用组合命令

### 查看所有服务状态
```bash
systemctl status sja-api.service sja-bot.service caddy.service
```

### 查看最近的错误日志
```bash
journalctl -u sja-api.service --since "1 hour ago" | grep ERROR
```

### 查看任务执行情况
```bash
journalctl -u sja-api.service | grep "schedule:"
```

### 重启所有服务
```bash
systemctl restart sja-api.service sja-bot.service && docker restart napcat
```

---

## 📊 监控命令

### CPU 和内存
```bash
top
htop
```

### 服务资源使用
```bash
systemctl status sja-api.service  # 查看 Tasks 和 Memory
```

### 磁盘使用
```bash
df -h
du -sh /home/deploy/sJAutoSport/*
```

