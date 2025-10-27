# SJTU Sports Auto-Booking 部署总览

## 📚 文档索引

本文档系统包含以下文档：

1. **DEPLOYMENT_GUIDE.md** (14KB) - 完整部署文档
   - 系统架构详解
   - 服务配置说明
   - 网络配置
   - 监控与日志
   - 故障排查
   - 性能优化

2. **QUICK_REFERENCE.md** - 快速参考卡片
   - 常用命令
   - 快速故障排查
   - 服务管理
   - 日志查看

## 🎯 文档使用指南

### 新手部署
1. 阅读 `DEPLOYMENT_GUIDE.md` 的"系统概述"和"服务器环境配置"章节
2. 按照"服务配置与启动"章节配置和启动服务
3. 使用"故障排查"章节解决常见问题

### 日常维护
1. 使用 `QUICK_REFERENCE.md` 快速查找命令
2. 定期检查日志
3. 必要时参考 `DEPLOYMENT_GUIDE.md` 的详细说明

### 紧急故障处理
1. 直接查看 `QUICK_REFERENCE.md` 的"故障排查"部分
2. 检查服务状态和日志
3. 参考 `DEPLOYMENT_GUIDE.md` 的故障排查章节

## 📝 文档位置

所有文档位于: `/home/deploy/sJAutoSport/docs/`

```
docs/
├── DEPLOYMENT_GUIDE.md     # 完整部署文档 (14KB)
├── QUICK_REFERENCE.md       # 快速参考卡片
└── README_DEPLOYMENT.md    # 本文档
```

## 🚀 快速开始

### 查看服务状态
```bash
systemctl status sja-api.service sja-bot.service
```

### 查看日志
```bash
journalctl -u sja-api.service -f
```

### 重启服务
```bash
systemctl restart sja-api.service sja-bot.service
```

---

**创建日期**: 2025-10-26
**适用环境**: Ubuntu 22.04, Python 3.10.18
**维护者**: SJTU Sports Auto-Booking Team
