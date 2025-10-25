# 🔥 热加载功能使用指南

## 概述

热加载功能允许你在修改代码后自动重新加载插件，无需手动重启机器人。这大大提高了开发效率。

## 🚀 启动方式

### 方式1：使用环境变量（推荐）

```bash
# 设置热加载环境变量
export HOT_RELOAD=true

# 启动机器人
python bot/run.py
```

### 方式2：使用专用启动脚本

```bash
# 使用NoneBot内置热加载
python start_bot_dev.py

# 或使用自定义热加载
python start_bot_hot_reload.py
```

### 方式3：修改.env文件

在 `bot/.env` 文件中添加：
```
HOT_RELOAD=true
```

## 📁 监控目录

热加载会监控以下目录的文件变化：
- `bot/plugins/` - 机器人插件目录
- `sja_booking/` - 核心业务逻辑目录

## ⚡ 功能特性

### ✅ 支持的热加载
- 修改插件文件（.py）
- 修改业务逻辑文件
- 添加新的插件文件
- 修改插件配置

### ⚠️ 限制
- 某些修改可能需要完全重启（如修改NoneBot配置）
- 2秒冷却时间，避免频繁重载
- 只监控Python文件（.py）

## 🔧 配置选项

### 环境变量
- `HOT_RELOAD`: 启用热加载（true/false）
- `LOG_LEVEL`: 日志级别（DEBUG/INFO/WARNING/ERROR）

### 配置文件
在 `bot/env.example` 中：
```
# 热加载配置
HOT_RELOAD=false
```

## 📝 使用示例

### 1. 开发新插件
```bash
# 启动热加载模式
export HOT_RELOAD=true
python bot/run.py

# 在另一个终端中修改插件
echo 'print("Hello from hot reload!")' >> bot/plugins/test.py
# 机器人会自动重新加载插件
```

### 2. 修改现有插件
```bash
# 修改 bot/plugins/login.py
# 保存文件后，机器人会自动重新加载
```

### 3. 修改业务逻辑
```bash
# 修改 sja_booking/auth.py
# 保存文件后，相关功能会自动更新
```

## 🐛 故障排除

### 问题1：热加载不工作
**解决方案：**
1. 检查是否安装了watchdog：`pip install watchdog`
2. 确认设置了环境变量：`echo $HOT_RELOAD`
3. 检查文件权限

### 问题2：重新加载失败
**解决方案：**
1. 查看控制台错误信息
2. 检查Python语法错误
3. 必要时完全重启机器人

### 问题3：性能问题
**解决方案：**
1. 调整冷却时间（在代码中修改`reload_cooldown`）
2. 减少监控目录数量
3. 使用更精确的文件过滤

## 💡 最佳实践

1. **开发时使用热加载**：提高开发效率
2. **生产环境关闭热加载**：避免意外重载
3. **定期重启**：长时间运行后建议重启
4. **监控日志**：注意重载成功/失败信息

## 🔄 与普通模式的对比

| 特性 | 普通模式 | 热加载模式 |
|------|----------|------------|
| 启动速度 | 快 | 稍慢 |
| 开发效率 | 低 | 高 |
| 资源占用 | 低 | 稍高 |
| 稳定性 | 高 | 中等 |
| 适用场景 | 生产环境 | 开发环境 |

## 📚 相关文件

- `bot/run.py` - 主启动脚本
- `bot/nb_config.py` - 配置文件
- `start_bot_dev.py` - 开发模式启动脚本
- `start_bot_hot_reload.py` - 自定义热加载启动脚本
- `bot/env.example` - 环境变量示例
