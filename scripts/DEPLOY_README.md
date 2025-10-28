# 部署脚本使用说明

## 脚本位置

```bash
/home/deploy/sJAutoSport/scripts/deploy.sh
```

## 使用方法

### 完整部署（默认）

执行完整部署流程：更新代码、依赖、前端，并重启所有服务。

```bash
sudo /home/deploy/sJAutoSport/scripts/deploy.sh
# 或
sudo /home/deploy/sJAutoSport/scripts/deploy.sh full
```

**执行内容**：
- ✅ 检查系统环境
- ✅ 检查服务状态
- ✅ 更新代码（如果使用 Git）
- ✅ 更新 Python 依赖
- ✅ 构建前端
- ✅ 部署前端到生产环境
- ✅ 重启所有服务（sja-api, sja-bot, caddy, napcat）
- ✅ 验证部署状态
- ✅ 显示服务日志

### 仅重启服务

源代码或配置改动后的快速重启。

```bash
sudo /home/deploy/sJAutoSport/scripts/deploy.sh restart
```

**执行内容**：
- ✅ 重新加载 systemd
- ✅ 重启 sja-api.service
- ✅ 重启 sja-bot.service
- ✅ 重启 caddy.service
- ✅ 重启 NapCat 容器
- ✅ 验证部署状态

### 仅更新前端

适用于前端代码修改后的部署。

```bash
sudo /home/deploy/sJAutoSport/scripts/deploy.sh frontend
```

**执行内容**：
- ✅ 构建前端（npm run build）
- ✅ 备份旧版本
- ✅ 部署到 /opt/sja/frontend/dist
- ✅ 重启 caddy.service

### 仅更新依赖

适用于 requirements.txt 更新后的部署。

```bash
sudo /home/deploy/sJAutoSport/scripts/deploy.sh deps
```

**执行内容**：
- ✅ 更新 pip
- ✅ 安装/更新 requirements.txt 中的依赖
- ✅ 重启所有服务

### 验证部署状态

检查所有服务是否正常运行。

```bash
sudo /home/deploy/sJAutoSport/scripts/deploy.sh verify
```

**检查内容**：
- ✅ 服务运行状态（sja-api, sja-bot, caddy, napcat）
- ✅ 端口监听状态（8000, 8080, 3000, 443）
- ✅ API 健康检查
- ✅ 显示服务详细状态

### 查看服务状态

快速查看所有服务的当前状态。

```bash
sudo /home/deploy/sJAutoSport/scripts/deploy.sh status
```

### 查看日志

显示最近的服务日志。

```bash
sudo /home/deploy/sJAutoSport/scripts/deploy.sh logs
```

## 使用场景示例

### 日常维护

```bash
# 查看当前服务状态
sudo /home/deploy/sJAutoSport/scripts/deploy.sh status

# 查看服务日志
sudo /home/deploy/sJAutoSport/scripts/deploy.sh logs
```

### 前端更新

```bash
# 修改前端代码后
sudo /home/deploy/sJAutoSport/scripts/deploy.sh frontend
```

### 后端代码更新

```bash
# 修改后端代码后
sudo /home/deploy/sJAutoSport/scripts/deploy.sh restart

# 如果需要更新依赖
sudo /home/deploy/sJAutoSport/scripts/deploy.sh deps
```

### 完整更新

```bash
# 更新所有内容
sudo /home/deploy/sJAutoSport/scripts/deploy.sh full
```

## 脚本配置

脚本中的主要配置变量（在 `/home/deploy/sJAutoSport/scripts/deploy.sh` 中）：

```bash
PROJECT_DIR="/home/deploy/sJAutoSport"                    # 项目目录
VENV_PYTHON="/root/miniconda3/envs/sJAutoSport/bin/python" # Python 环境
FRONTEND_DIR="${PROJECT_DIR}/frontend"                    # 前端目录
FRONTEND_DEPLOY_DIR="/opt/sja/frontend/dist"              # 前端部署目录
ENV_FILE="/etc/sja/env"                                   # 环境变量文件
```

## 故障排查

### 查看实时日志

```bash
# API 服务
journalctl -u sja-api.service -f

# Bot 服务
journalctl -u sja-bot.service -f

# NapCat 容器
docker logs napcat -f
```

### 手动重启服务

```bash
systemctl restart sja-api.service
systemctl restart sja-bot.service
systemctl restart caddy.service
docker restart napcat
```

### 检查端口占用

```bash
netstat -tlnp | grep -E ':(8000|8080|3000|443)'
```

### 检查服务状态

```bash
systemctl status sja-api.service sja-bot.service caddy.service
docker ps | grep napcat
```

## 注意事项

1. ⚠️ **必须使用 root 用户**运行此脚本
2. ⚠️ **执行完整部署前**请确保已经备份重要数据
3. ⚠️ **前端部署会备份旧版本**到 `/opt/sja/frontend/dist.bak.*`
4. ⚠️ **部署过程中**服务会短暂中断（重启期间）
5. ⚠️ **验证部署失败时**请查看日志定位问题

## 相关文档

- [完整部署文档](../docs/DEPLOYMENT_GUIDE.md)
- [服务管理参考](../docs/QUICK_REFERENCE.md)
- [API 文档](../docs/api/)

## 最后更新

2025-10-27
