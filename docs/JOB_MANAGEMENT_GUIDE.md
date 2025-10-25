# 🚀 任务管理系统使用指南

## 概述

任务管理系统允许你将 monitor 和 schedule 等长期运行的功能作为独立的后台进程运行，并提供完整的任务查询和管理接口。

## 🏗️ 系统架构

### 核心组件
- **JobManager**: 任务管理器，负责创建、启动、停止、删除任务
- **独立进程**: 每个任务运行在独立的子进程中
- **持久化存储**: 任务信息保存在 `~/.sja/jobs/jobs.json`
- **日志系统**: 每个任务有独立的日志文件

### 任务类型
- **MONITOR**: 监控任务，持续监控场馆可用性
- **SCHEDULE**: 定时任务，在指定时间执行预订
- **AUTO_BOOKING**: 自动抢票任务（预留）

## 🚀 CLI 命令

### 任务管理
```bash
# 列出所有任务
python main.py jobs

# 清理已死亡的任务
python main.py jobs-cleanup

# 启动任务
python main.py job-start <job_id>

# 停止任务
python main.py job-stop <job_id>

# 删除任务
python main.py job-delete <job_id>

# 查看任务日志
python main.py job-logs <job_id> [--lines 50]
```

### 创建任务
```bash
# 创建监控任务
python main.py create-monitor --name "监控任务名称" --preset 13 --interval 300 --auto-book

# 创建定时任务
python main.py create-schedule --name "定时任务名称" --preset 13 --hour 12 --minute 0
```

## 🤖 Bot 命令

### 任务管理
```
!任务列表          # 显示所有任务
!启动任务 <job_id>  # 启动指定任务
!停止任务 <job_id>  # 停止指定任务
!删除任务 <job_id>  # 删除指定任务
!任务日志 <job_id>  # 查看任务日志
!清理任务          # 清理已死亡的任务
```

### 创建任务
```
!创建监控 任务名称                    # 创建监控任务
!创建定时 任务名称 12:00              # 创建定时任务（12:00执行）
```

## 📊 任务状态

| 状态 | 说明 | 图标 |
|------|------|------|
| PENDING | 等待启动 | ⏳ |
| RUNNING | 运行中 | 🟢 |
| STOPPED | 已停止 | 🔴 |
| FAILED | 失败 | ❌ |
| COMPLETED | 已完成 | ✅ |

## 🔧 使用示例

### 1. 创建监控任务
```bash
# CLI方式
python main.py create-monitor \
  --name "南洋北苑健身房监控" \
  --preset 13 \
  --interval 300 \
  --auto-book \
  --pt "18,19,20" \
  --users "czq,sty"

# Bot方式
!创建监控 南洋北苑健身房监控
```

### 2. 创建定时任务
```bash
# CLI方式
python main.py create-schedule \
  --name "每日预订任务" \
  --preset 13 \
  --hour 8 \
  --minute 0 \
  --users "czq"

# Bot方式
!创建定时 每日预订任务 08:00
```

### 3. 管理任务
```bash
# 查看任务列表
python main.py jobs

# 启动任务
python main.py job-start 1e95803d

# 查看日志
python main.py job-logs 1e95803d --lines 20

# 停止任务
python main.py job-stop 1e95803d

# 删除任务
python main.py job-delete 1e95803d
```

## 📁 文件结构

```
~/.sja/jobs/
├── jobs.json          # 任务列表
├── 1e95803d.log       # 任务日志
├── 9739515f.log       # 任务日志
└── ...
```

## 🔍 任务配置

### 监控任务配置
```json
{
  "target": {
    "venue_keyword": "学生中心",
    "field_type_keyword": "羽毛球",
    "date_offset": 7,
    "start_hour": 18,
    "duration_hours": 1
  },
  "plan": {
    "enabled": true,
    "interval_seconds": 300,
    "auto_book": false,
    "preferred_hours": [18, 19, 20]
  }
}
```

### 定时任务配置
```json
{
  "target": {
    "venue_keyword": "学生中心",
    "field_type_keyword": "羽毛球",
    "date_offset": 1,
    "start_hour": 18,
    "duration_hours": 1
  },
  "schedule": {
    "hour": 12,
    "minute": 0,
    "second": 0,
    "preset": 13,
    "date_offset": 1,
    "start_hour": 18
  }
}
```

## ⚙️ 高级功能

### 1. 进程管理
- 每个任务运行在独立的子进程中
- 支持优雅停止（SIGTERM）和强制终止（SIGKILL）
- 自动检测已死亡的进程

### 2. 日志系统
- 每个任务有独立的日志文件
- 支持实时日志查看
- 日志轮转和清理

### 3. 任务持久化
- 任务信息保存在JSON文件中
- 支持任务状态恢复
- 自动清理过期任务

## 🐛 故障排除

### 问题1：任务启动失败
**解决方案：**
1. 检查任务配置是否正确
2. 确认相关脚本文件存在
3. 查看错误日志

### 问题2：任务无法停止
**解决方案：**
1. 检查进程是否存在
2. 尝试强制终止：`kill -9 <pid>`
3. 使用清理命令：`python main.py jobs-cleanup`

### 问题3：日志文件过大
**解决方案：**
1. 定期清理日志文件
2. 调整日志级别
3. 使用日志轮转

## 📈 性能优化

### 1. 资源管理
- 限制同时运行的任务数量
- 监控内存和CPU使用
- 定期清理过期任务

### 2. 网络优化
- 调整请求间隔
- 使用连接池
- 实现重试机制

### 3. 存储优化
- 压缩日志文件
- 定期清理临时文件
- 使用数据库存储（可选）

## 🔮 未来改进

1. **Web界面**: 提供Web管理界面
2. **任务调度**: 支持更复杂的调度策略
3. **监控告警**: 任务异常时发送通知
4. **集群支持**: 支持多机器任务分发
5. **API接口**: 提供REST API接口

## 📚 相关文档

- [热加载功能指南](HOT_RELOAD_GUIDE.md)
- [登录重试功能指南](LOGIN_RETRY_GUIDE.md)
- [机器人命令指南](bot_command_guide.md)
