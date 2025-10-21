# 多用户Token管理使用指南

## 🚀 功能概述

本系统现在支持多用户Token管理，可以同时管理多个用户的认证信息，并支持智能切换和批量预订功能。

## 📋 主要特性

- **多用户管理**：支持配置多个用户的认证信息
- **智能切换**：当某个用户遇到频率限制时，自动切换到下一个用户
- **批量预订**：支持为多个用户同时预订场地
- **用户筛选**：可以指定特定用户进行预订，或排除某些用户
- **向后兼容**：完全兼容原有的单用户模式

## 🔧 配置方法

### 1. 在config.py中配置多用户

```python
from sja_booking.models import AuthConfig, UserAuth

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
        UserAuth(
            nickname="用户3",
            cookie="JSESSIONID=第三个用户的cookie",
            token=None,
            username=None,
            password=None,
        ),
    ]
)
```

### 2. 用户认证信息获取

每个用户需要以下认证信息之一：
- **Cookie**：从浏览器开发者工具中复制JSESSIONID
- **Token**：Authorization头信息
- **用户名+密码**：用于自动登录

## 🎯 使用方法

### 1. 用户管理命令

```bash
# 列出所有配置的用户
python main.py list-users

# 验证用户配置
python main.py validate-users

# 切换到指定用户
python main.py switch-user 用户1
```

### 2. 单用户预订

```bash
# 使用第一个用户预订
python main.py order --preset 13 --date 1 --st 17

# 切换到指定用户后预订
python main.py switch-user 用户1
python main.py order --preset 13 --date 1 --st 17
```

### 3. 多用户预订

```bash
# 为所有用户预订
python main.py order --preset 13 --date 1 --st 17

# 为指定用户预订
python main.py order --preset 13 --date 1 --st 17 --users "用户1,用户2"

# 排除特定用户
python main.py order --preset 13 --date 1 --st 17 --exclude-users "用户3"
```

### 4. 监控模式多用户支持

```bash
# 为所有用户监控并自动预订
python main.py monitor --preset 13 --interval 300 --date 2 --auto-book

# 为指定用户监控
python main.py monitor --preset 13 --interval 300 --date 2 --auto-book --users "用户1,用户2"

# 排除特定用户
python main.py monitor --preset 13 --interval 300 --date 2 --auto-book --exclude-users "用户3"
```

## 📊 输出示例

### 多用户预订结果

```
为 3 个用户进行预订: ['用户1', '用户2', '用户3']

--- 为用户 用户1 预订 ---
使用用户: 用户1
Order succeeded
Message: 下单成功，订单ID: 966086566571413504

--- 为用户 用户2 预订 ---
使用用户: 用户2
Order succeeded
Message: 下单成功，订单ID: 966086566571413505

--- 为用户 用户3 预订 ---
使用用户: 用户3
Order failed: 该时间段已不可用

📊 多用户预订结果汇总
✅ 成功: 2/3
  用户1: 下单成功，订单ID: 966086566571413504
    订单ID: 966086566571413504
  用户2: 下单成功，订单ID: 966086566571413505
    订单ID: 966086566571413505
  用户3: 该时间段已不可用
    错误: 该时间段已不可用
```

### 智能切换示例

```
使用用户: 用户1
检测到频率限制，切换到用户: 用户2
使用用户: 用户2
Order succeeded
```

## 🔄 智能切换机制

当遇到以下情况时，系统会自动切换到下一个用户：
- 请求过于频繁（500错误）
- 频率限制错误
- 其他服务器错误

切换顺序按照config.py中users列表的顺序，循环切换。

## ⚙️ 高级配置

### 1. 用户优先级

在config.py中，users列表的顺序就是用户优先级。系统会按照这个顺序：
1. 首先尝试第一个用户
2. 遇到限制时切换到第二个用户
3. 以此类推

### 2. 用户筛选

- `--users`：只使用指定的用户
- `--exclude-users`：排除指定的用户
- 两者可以同时使用，系统会取交集

### 3. 监控模式

监控模式支持所有多用户功能：
- 自动为所有用户监控可用时间段
- 智能切换避免频率限制
- 批量预订提高成功率

## 🛠️ 故障排除

### 1. 用户配置无效

```bash
python main.py validate-users
```

### 2. 检查用户状态

```bash
python main.py list-users
```

### 3. 测试单个用户

```bash
python main.py switch-user 用户1
python main.py userinfo
```

## 📝 注意事项

1. **Cookie有效期**：定期更新用户的Cookie信息
2. **频率限制**：避免同时使用过多用户，建议3-5个用户
3. **网络稳定性**：确保网络连接稳定，避免频繁切换
4. **资源管理**：系统会自动管理HTTP连接，无需手动关闭

## 🎉 最佳实践

1. **用户数量**：建议配置3-5个用户，平衡成功率和资源消耗
2. **时间错开**：不同用户预订不同时间段，避免冲突
3. **监控策略**：使用监控模式时，建议设置较长的间隔时间
4. **备份配置**：定期备份config.py文件，避免配置丢失

通过多用户管理功能，您可以大大提高预订成功率，特别是在高峰期或热门时间段！🎯
