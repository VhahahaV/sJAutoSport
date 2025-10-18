# SJTU Sports CLI

面向上海交通大学体育场馆预约系统的 HTTP 自动化脚本。项目以“可配置+模块化”为核心，既能复用真实接口做极速抢票，也能提供余票监控、场馆信息检索、定时任务等配套能力。

---

## 功能概览
- **纯 HTTP**：直接请求后端接口，无需浏览器/模拟器，响应快、稳定性高。
- **模块化设计**：`sja_booking` 包含 API 客户端、余票监控器、计划调度器、端点发现、CLI 等组件，可按需扩展。
- **多模式下单**：
  - 手动查询：快速列出场馆、日期、时段余量，表格输出。
  - 实时监测：按指定间隔自动轮询，发现空位时提示或直接下单。
  - 定时抢票：依托 APScheduler，实现每天固定时间自动抢票。
- **灵活配置**：所有接口路径、默认目标、登录凭据都在 `config.py` 中可配置。
- **端点辅助**：提供轻量级 `discover`，从页面/静态 JS 中提取候选 API，方便比对。

---

## 目录结构
```
sja_booking/           # 核心模块
├── api.py             # SportsAPI：封装真实接口、数据解析
├── monitor.py         # SlotMonitor：余票轮询、自动下单
├── scheduler.py       # schedule_daily：APScheduler 封装
├── discovery.py       # discover_endpoints：端点扫描
├── models.py          # 数据模型/配置结构
├── cli.py             # 子命令解析与调度
└── __init__.py
config.py              # 站点配置/默认目标（需根据抓包结果维护）
main.py           # CLI 入口（解析命令，调用 run_cli）
README.md              # 文档（当前文件）
```

---

## 环境准备
```bash
python -m venv .venv && source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -U pip
pip install httpx[http2] apscheduler rich tzlocal
```
> 如需在 CI/服务器使用，确保系统时间正确且可访问学校内网。

---

## 配置指南（config.py）
1. **登录凭据**
   - 登录平台后打开 DevTools → Network，找到任意成功的 API 请求。
   - 复制 Request Headers 中整段 `Cookie:`（包含 `JSESSIONID`、监控埋点等字段），粘贴到 `AUTH.cookie`。
   - 若请求头中存在 `Authorization: Bearer ...` 等字段，请写入 `AUTH.token`。
2. **接口路径**
   - 根据抓包结果填写 `ENDPOINTS` 中各字段；示例已匹配当前平台版本：
     ```python
     ENDPOINTS = EndpointSet(
         current_user="/system/user/currentUser",
         list_venues="/manage/venue/listOrderCount",
         venue_detail="/manage/venue/queryVenueById",
         field_situation="/manage/fieldDetail/queryFieldSituation",
         field_reserve="/manage/fieldDetail/queryFieldReserveSituationIsFull",
         order_submit="/venue/personal/orderImmediatelyPC",
         appointment_overview="/appointment/disabled/getAppintmentAndSysUserbyUser",
         ping="/",
     )
     ```
3. **默认目标**
   - `TARGET` 里配置常用场馆关键字、项目关键字、日期策略（`date_offset` 或 `fixed_dates`）、起始小时等。
4. **监控计划**
   - `MONITOR_PLAN` 定义 `monitor` 命令默认轮询间隔、是否自动下单等。

配置完成后，建议先运行 `python main.py debug-login` 确认登录态无误。

---

## 命令速览
所有功能通过 `python main.py <命令>` 调用：

| 命令 | 功能 | 常用参数 |
| --- | --- | --- |
| `debug-login` | 校验登录态、输出用户信息 | 无 |
| `discover` | 扫描页面/静态 JS，生成候选 API | `--base`（覆盖基地址） |
| `venues` | 列出场馆 | `--keyword`（模糊匹配），`--page`，`--size` |
| `slots` | 查询余票并表格输出 | `--venue-id/--venue-keyword`，`--field-type-id/--field-type-keyword`，`--date`，`--date-offset`，`--show-full` |
| `monitor` | 定时轮询，发现空位可自动下单 | 同 `slots`，外加 `--interval`、`--auto-book` |
| `book-now` | 立即抢票（按配置筛选优先空位） | 同 `slots` |
| `schedule` | 每天固定时间执行 `book-now` | 同 `slots`，外加 `--hour`、`--minute`、`--second` |

示例：
```bash
# 1. 检查登录态
python main.py debug-login

# 2. 列出含“学生”的场馆
python main.py venues --keyword 学生

# 3. 查看学生中心羽毛球 7 天后的余票（含已满时段）
python main.py slots --venue-keyword 学生 --field-type-keyword 羽毛球 --date-offset 7 --show-full

# 4. 每 30 秒轮询一次，发现空位即自动下单
python main.py monitor --venue-keyword 学生 --field-type-keyword 羽毛球 --auto-book --interval 30

# 5. 每天 11:59 预热 & 12:00 自动抢票
python main.py schedule --venue-keyword 学生 --field-type-keyword 羽毛球 --hour 12 --minute 0 --second 0
```

---

## 余票监控与自动下单
- `SlotMonitor` 会在第一次运行时解析场馆/项目（支持 ID 或关键字），随后按配置日期请求 `/manage/fieldDetail/queryFieldSituation`。
- 输出基于 `rich`，表格包含日期、起止时间、状态、剩余、容量、价格等列。
- 若开启 `--auto-book` / `MONITOR_PLAN.auto_book`，会寻找时段返回里的 `orderId`（或其它可用标识）调用 `/venue/personal/orderImmediatelyPC`。
- 若接口改版导致字段缺失，可在 `SlotMonitor._attempt_booking` 或 `SportsAPI.query_slots` 中扩展解析。

---

## 端点发现（可选）
```bash
python main.py discover
python main.py discover --base https://sports.sjtu.edu.cn/pc/
```
命令会：
1. 下载首页 HTML，提取内联 `"/api/..."` 字符串。
2. 扫描 `<script src="...js">` 引用，追加外链 JS 中的 `"/pc/api/..."` 候选。
3. 输出前 50 个结果，并写入 `endpoints.auto.json` 供对照。

> 若返回空数组，说明页面内无明显 API 字面量，此时需继续靠 Network 抓包确认。

---

## 常见问题
- **debug-login 404 / HTML**：`ENDPOINTS.current_user` 写错或 Cookie 失效。请重登平台后复制最新 Cookie。
- **venues/slots 空表**：接口返回结构可能有变，打印 `slots` 命令结果时加 `--show-full` 看 raw 信息；必要时调整 `SportsAPI.query_slots` 中的字段映射。
- **自动下单失败**：检查监控输出日志是否显示“缺少 orderId”。这通常意味着接口不直接返回订单号，需要额外请求（例如锁定接口）或参数。
- **discover 无结果**：部分页面通过动态接口返回路径，静态扫描无法捕获。请继续使用浏览器抓包或阅读前端源码。

---

## 开发扩展
- 模块化设计便于自定义命令：在 `sja_booking/cli.py` 添加子命令并调用相应 API/Monitor。
- 需要更多字段时，可在 `sja_booking/models.py` 扩充数据类（例如增加价格策略、场馆标签等）。
- 若要支持多用户/多计划，可考虑在外层脚本中循环调用 `SportsAPI` 并传入不同配置。

---

## 免责声明
本项目仅供学习/个人实验。使用过程中请遵守学校平台规则，避免高频/恶意请求所造成的账号封禁或其它后果。作者不对脚本使用造成的任何影响负责。
