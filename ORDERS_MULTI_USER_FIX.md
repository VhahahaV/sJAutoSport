# ✅ 订单管理多用户修复

## 📅 完成日期
2025-10-26 22:30

## 🐛 问题
订单管理依旧只有一个用户的订单

## ✅ 修复方案

### 问题分析
原来 `get_user_orders()` 函数只调用 `_create_api()` 获取当前活跃用户的订单。

### 解决方案
修改 `get_user_orders()` 函数，遍历所有用户并获取他们的订单：

```python
def get_user_orders(page_no: int = 1, page_size: int = 10) -> Dict[str, Any]:
    """获取所有用户的订单列表"""
    cookies_map, _ = _auth_manager.load_all_cookies()
    all_orders: List[Dict[str, Any]] = []
    total = 0
    
    for key, record in cookies_map.items():
        try:
            username = record.get("username")
            nickname = record.get("nickname")
            api = _create_api(active_user=key)
            response = api.list_orders(page_no=1, page_size=100)  # 获取更多订单
            
            orders = response.get("records", [])
            # 为每个订单添加用户信息
            for order in orders:
                order["userId"] = username or key
                order["name"] = nickname or username or key
            
            all_orders.extend(orders)
            api.close()
        except Exception as e:
            logger.warning("Failed to get orders for user %s: %s", key, str(e))
            continue
    
    # 按创建时间倒序排序
    all_orders.sort(key=lambda x: x.get("ordercreatement", ""), reverse=True)
    
    total = len(all_orders)
    
    # 分页
    start = (page_no - 1) * page_size
    end = start + page_size
    paginated_orders = all_orders[start:end]
    
    return {"success": True, "orders": paginated_orders, "total": total}
```

### 关键改进

1. **遍历所有用户**:
   ```python
   for key, record in cookies_map.items():
       api = _create_api(active_user=key)
   ```

2. **为订单添加用户信息**:
   ```python
   order["userId"] = username or key
   order["name"] = nickname or username or key
   ```

3. **合并所有订单并按时间排序**:
   ```python
   all_orders.sort(key=lambda x: x.get("ordercreatement", ""), reverse=True)
   ```

4. **分页处理**:
   ```python
   start = (page_no - 1) * page_size
   end = start + page_size
   paginated_orders = all_orders[start:end]
   ```

## 🔧 技术细节

### 数据流程

```
获取所有用户Cookie
    ├─ 遍历每个用户
    │  ├─ 创建该用户的API客户端
    │  ├─ 获取该用户的订单（最多100条）
    │  ├─ 为订单添加用户信息
    │  └─ 合并到总订单列表
    ├─ 按创建时间倒序排序
    ├─ 分页处理
    └─ 返回分页后的订单
```

### 修改文件

- `sja_booking/service.py`:
  - 添加 `logging` 导入
  - 重写 `get_user_orders()` 函数

## 🚀 部署状态

✅ 后端服务已重启
✅ 订单管理现在显示所有用户的订单

## 📊 预期效果

- ✅ 显示所有用户的订单
- ✅ 按用户分组显示
- ✅ 按创建时间倒序排序
- ✅ 支持分页
- ✅ 每个订单包含用户信息

---

**状态**: ✅ 已完成
**版本**: 1.3.2

