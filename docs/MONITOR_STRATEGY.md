# 监控任务策略说明

## 📋 概述

本文档详细说明监控任务的预订策略、优先时间段、多用户处理等机制。

---

## 🎯 核心问题解答

### Q1: 如果不指定优先时间段，机器人会怎么预订？

**答案**: 会预订**所有发现的有余量的场次**

#### 具体逻辑 (参考代码: `service.py:151-168`)

```python
def _filter_slots_by_preferences_dict(slots, monitor_info):
    preferred_hours = monitor_info.get("preferred_hours") or []
    preferred_days = monitor_info.get("preferred_days") or []
    
    # 关键逻辑：如果没有指定优先时间段和优先天数
    if not preferred_hours and not preferred_days:
        return list(slots)  # 返回所有场次
    
    # 如果有过滤条件，才进行过滤
    filtered = []
    for slot in slots:
        hour = _slot_dict_hour(slot)
        day_offset = _slot_dict_day_offset(slot)
        
        if preferred_hours and (hour is None or hour not in preferred_hours):
            continue  # 跳过不在优先时间段的场次
        if preferred_days and (day_offset is None or day_offset not in preferred_days):
            continue  # 跳过不在优先天数的场次
        
        filtered.append(slot)
    return filtered
```

#### 流程图

```
┌─────────────────────────────────────┐
│  监控发现可用场次                   │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  是否有优先时间段设置？             │
└────────┬─────────────────┬───────────┘
         │ 否              │ 是
         ▼                 ▼
┌─────────────────┐  ┌─────────────────┐
│ 预订所有场次    │  │ 只预订优先时段  │
│ (默认策略)      │  │ 的场次          │
└─────────────────┘  └─────────────────┘
```

#### 实际案例

**场景1**: 未指定优先时间段
- 监控发现: 明天 15:00-16:00, 16:00-17:00, 20:00-21:00 三个时段有余量
- **行为**: 会尝试预订这**三个时段**
- **风险**: 可能预订到你不想要的时间

**场景2**: 指定优先时间段 [18, 20]
- 监控发现: 明天 15:00-16:00, 18:00-19:00, 20:00-21:00
- **行为**: 只预订 18:00-19:00, 20:00-21:00
- **好处**: 只预订你想要的时间段

---

### Q2: 如果选择了两个用户，一个人订成功了，另一个还会继续吗？

**答案**: **不会**，只要有一个人预订成功，任务就完成了

#### 具体逻辑 (参考代码: `service.py:1296-1355`)

```python
# 逐个用户尝试预订
for user_index, user in enumerate(user_sequence, 1):
    success_for_user = False
    
    for slot_index, slot in enumerate(slots, 1):
        if not slot.get("available", False):
            continue
        
        result = await order_once(...)
        
        if result.success:
            monitor_info["successful_bookings"] += 1
            monitor_info["status"] = "completed"  # 任务标记为完成
            success_for_user = True
            break  # 跳出slot循环
        
        await asyncio.sleep(min(6.0, 2.0 + slot_index * 1.5))
    
    # 关键：如果当前用户成功了，不继续下一个用户
    if success_for_user:
        monitor_info["last_booking_results"].append({
            "user": user.nickname,
            "success": True,
            "message": result.message,
        })
        # 不会继续下一个用户
```

#### 执行流程图

```
┌─────────────────────────────────┐
│  监控发现可用场次              │
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────┐
│  用户1: USER_A                     │
└────────┬───────────────────────┘
         │
         ├─ 尝试 时段1 → 失败
         ├─ 尝试 时段2 → 失败  
         ├─ 尝试 时段3 → ✅ 成功
         │
         ▼
┌─────────────────────────────────┐
│  status = "completed"           │
└─────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│  任务结束，不再尝试用户2       │
└─────────────────────────────────┘
```

#### 多用户行为说明

| 场景 | 行为 | 结果 |
|------|------|------|
| 用户1订成功 | 任务完成，不尝试用户2 | ✅ 用户1有订单 |
| 用户1失败 | 继续尝试用户2 | 用户2可能成功 |
| 两个用户都失败 | 任务标记失败，继续监控 | 下次监控时重新尝试 |

---

## 📊 完整预订策略

### 过滤层级

```
所有可用场次
    ↓
【1. 优先时间段过滤】
    ├─ 如果有 preferred_hours: 只保留符合时间段的
    └─ 如果没有: 保留所有
    ↓
【2. 优先天数过滤】
    ├─ 如果有 preferred_days: 只保留符合天数的
    └─ 如果没有: 保留所有
    ↓
【3. 自动预订】
    ├─ 如果有 auto_book=True: 开始预订流程
    └─ 如果 auto_book=False: 只发送通知
    ↓
按用户顺序尝试预订
    ↓
只要一个用户成功 → 任务完成
```

### 用户顺序逻辑

```python
# 确定用户顺序
if target_users:
    # 如果指定了目标用户
    user_sequence = [满足条件的用户]
else:
    # 排除被排除的用户
    user_sequence = [所有用户 - 排除用户]

# 如果没有可用用户，使用第一个
if not user_sequence:
    user_sequence = available_users[:1]
```

---

## 🔍 实际案例分析

### 案例1: 无优先时间段 + 两个用户

**配置**:
- auto_book: True
- preferred_hours: [] (未设置)
- target_users: [USER_A, USER_B]

**监控结果**:
- 发现 18:00-19:00 有余量

**执行过程**:
```
1. 尝试用户 USER_A → 成功 ✅
2. 任务完成，不再尝试用户 USER_B
3. 用户 USER_B 不会收到预订
```

### 案例2: 有优先时间段 + 两个用户

**配置**:
- auto_book: True
- preferred_hours: [18, 20]
- target_users: [USER_A, USER_B]

**监控结果**:
- 发现 15:00-16:00 有余量 (不在优先时间段)
- 发现 18:00-19:00 有余量 (在优先时间段)

**执行过程**:
```
1. 过滤后只保留 18:00-19:00
2. 尝试用户 USER_A → 成功 ✅
3. 任务完成
4. 不会预订 15:00-16:00 (不在优先时间段)
```

### 案例3: 无优先时间段，第一个用户失败

**配置**:
- auto_book: True
- preferred_hours: [] (未设置)
- target_users: [USER_A, USER_B]

**监控结果**:
- 发现 18:00-19:00 有余量

**执行过程**:
```
1. 尝试用户 USER_A → 失败 (余量不足)
2. 尝试用户 USER_B → 成功 ✅
3. 任务完成
```

---

## ⚙️ 配置建议

### 推荐配置1: 精确预订

```yaml
auto_book: true
preferred_hours: [18, 19, 20]  # 只预订晚上
preferred_days: [0, 1]  # 只查询今天和明天
target_users: [你的用户名]
```

**优点**: 
- 精确控制时间段
- 避免预订到不想要的时间

### 推荐配置2: 宽泛预订

```yaml
auto_book: true
preferred_hours: []  # 不限制
preferred_days: []  # 不限制
target_users: []  # 所有用户
```

**优点**:
- 容易抢到任何场次
- 成功率高

**缺点**:
- 可能预订到不想要的时间

### 推荐配置3: 时段优先

```yaml
auto_book: true
preferred_hours: [12, 13, 14, 18, 19, 20]
preferred_days: [1, 2, 3]
target_users: [用户名1, 用户名2]
```

**优点**:
- 多个时间段备选
- 多个账号提高成功率
- 限制在想要的时间

---

## 📝 关键代码位置

| 功能 | 文件 | 行数 |
|------|------|------|
| 优先时间段过滤 | `service.py` | 151-168 |
| 自动预订逻辑 | `service.py` | 1274-1355 |
| 多用户处理 | `service.py` | 1284-1355 |
| 监控循环 | `service.py` | 1084-1223 |

---

## ⚠️ 注意事项

1. **第一个用户成功即停**: 不会因为指定了多个用户而重复预订
2. **优先时间段强烈建议**: 避免预订到不想要的时间
3. **监控间隔**: 默认 4 分钟，不要设置太频繁
4. **任务完成状态**: 一旦预订成功，监控状态会变为 "completed"

---

**创建日期**: 2025-10-26
**文档版本**: 1.0.0

