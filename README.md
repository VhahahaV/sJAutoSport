# sJAutoSport

交大运动场馆预约工具：**一个 core，CLI 与网页两个入口**。仅使用当前登录的一个账号。支持密码与人工验证码登录、扫码登录、场地查询、预约、订单取消、余位监控和会话保活。无需 QQ Bot、OCR、浏览器自动化或大模型 API；不包含定时预约。

## 安装与启动

需要 Linux、Python 3.11+。仅使用 CLI 时无需安装 Node.js。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -c constraints.txt -e .
.venv/bin/sja
.venv/bin/sja daemon start
.venv/bin/sja schema
```

`data/` 默认在项目根目录，首次使用会初始化数据库。可用 `SJA_DATA_DIR` 指定其他目录；CLI、API 和 core 必须使用同一目录。后台进程仅通过私有 Unix socket 通信，负责保存登录流程、监控及保活。`daemon start` 可重复调用，不会启动第二个 core。

### 启动网页

```bash
.venv/bin/python -m pip install -c constraints.txt -e '.[web]'
.venv/bin/python -m uvicorn web_api.app:app --host 127.0.0.1 --port 8000
# 另一个终端
cd frontend
npm ci
npm run dev
```

打开 http://127.0.0.1:5173 。开发服务器将 `/api` 转发到本机 8000；API 启动时会确保 core 在线，关闭网页/API 不会停止后台监控。

## 网页操作逻辑

未登录先显示登录界面；已有有效会话则直接进入总览。

| 模块 | 职责 |
| --- | --- |
| 总览 | 自定义场馆运动卡片，查看未来 1–7 天的余位柱状图和完整场次明细 |
| 场地预约 | 选择场馆和运动 → 自动加载开放日期 → 选择时段 → 核对信息 → 提交预约 |
| 我的订单 | 核对预约、支付和使用状态，取消订单；状态筛选作用于当前页 |
| 余位监控 | 设置期望的未来日期和开始小时，持续检查余位；自动预约默认关闭 |
| 账号与会话 | 当前账号、退出登录、自动保活设置、立即检查会话 |

预约成功后进入“我的订单”核对支付状态。没有余位可携带场馆选择进入监控创建。监控创建表单默认收起，高级选项包含自动预约和每日检查范围；最近发现的场次可在监控列表中展开。监控页面每 30 秒刷新状态，后台实际检查频率由任务配置决定。

总览卡片选择场馆、运动和含今天的未来 1–7 天，配置保存在数据库中。每次进入总览自动刷新，也可单张或全部刷新。先请求日期余位摘要，仅对开放且未满的日期查询详情。柱状图展示每天的可预约场次数（场地 × 时段）；点击日期后，卡片内部可滚动查看全部场次、剩余量和价格，固定 560px 高度不随数据量变化。查询错误会单独标记，区别于已满和未开放。卡片不是后台监控任务。

订单列表返回 `can_cancel` 作为取消按钮的唯一判断条件：只有预订成功且校园接口未禁止取消的订单显示按钮。上游的 `cancelOrder=true` 表示禁止取消。

监控结果记录在本地数据库；目前没有外部消息推送。自动预约会创建真实订单。退出登录会暂停监控并关闭保活；重新登录后需自行恢复任务。

## Agent / CLI：先登录

`schema` 是操作协议的唯一来源：

```bash
.venv/bin/sja schema auth.start
.venv/bin/sja schema monitors.create
```

所有业务命令接受 `--json '{...}'`、`--json @FILE` 或 `--json -`（stdin）。输出 JSON：`{ok,result}` 或 `{ok:false,error}`。退出码 0 成功，1 业务/参数错误，2 连接/命令行错误。帮助信息是普通终端文本。

### 密码与人工验证码

```bash
.venv/bin/sja auth start --username USER_NAME --password-stdin
# 从受控标准输入提供一行密码；交互终端也可省略 --password-stdin 隐藏输入。
.venv/bin/sja auth verify --session-id SESSION_ID --code USER_ENTERED_CODE
.venv/bin/sja auth status
```

开始登录会返回 `session_id` 和 `captcha_path` / `captcha_mime` / `captcha_base64`。Agent 应将图片展示或发送给用户，等待用户填写后提交；不要自动识别。验证码错误可返回更新图片和 `retry` 状态，使用同一会话重新提交。会话在 core 内存中，重启或超时后重新开始。只有运动网站验证通过后才保存凭证，登录失败不会覆盖已有凭证。

密码不要放在命令行参数或 shell 历史。不要打印/上传凭证文件或完整调试响应。

### 扫码登录

```bash
.venv/bin/sja auth qr-start
.venv/bin/sja auth qr-status --json '{"session_id":"SESSION_ID"}'
.venv/bin/sja auth qr-cancel --json '{"session_id":"SESSION_ID"}'
```

将返回的 `qr_path` 或 `qr_base64` 图片展示给用户，使用交我办或微信扫码确认。每 2–3 秒轮询 `qr-status`，图片版本变化时重新展示；`success` 才表示运动网站会话已验证并保存。`expired` / `error` 时重新开始。二维码、UUID、签名均从 jAccount 实时获取，不固定保存。最多保留一个待完成的登录流程，开始另一种登录会取消旧流程。返回的图片文件是私有临时文件，轮询、取消或结束后可能被替换/删除，应及时读取。

### 查询、预约与订单

```bash
.venv/bin/sja presets list
.venv/bin/sja dates list --json '{"preset":5}'
.venv/bin/sja slots list --json '{"preset":5,"date":"1","show_full":true}'
.venv/bin/sja orders list --json '{"page_no":1,"page_size":20}'
.venv/bin/sja orders create --json '{"preset":5,"date":"YYYY-MM-DD","start_time":"19:00","end_time":"20:00"}'
.venv/bin/sja orders cancel --json '{"order_id":"ORDER_ID"}'
```

`date` 可以为真实日期或天数偏移（`0` 今天、`1` 明天）。命令示例中的日期和 ID 需替换。查询空列表不会替换为其他日期。提交预约/取消前应取得用户对具体操作的授权。预约只提交一次，不会失败后换接口、换时段或自动重试；网络超时后先查订单，确认结果再决定是否重新提交。

### 总览卡片

```bash
.venv/bin/sja dashboard add --json '{"preset":5,"days":7}'
.venv/bin/sja dashboard list
.venv/bin/sja dashboard availability --json '{"card_id":"CARD_ID"}'
.venv/bin/sja dashboard delete --json '{"card_id":"CARD_ID"}'
```

CLI 与网页共享同一份卡片配置；卡片查询为只读，不预约场地。

### 监控与保活

```bash
.venv/bin/sja monitors create --json '{"monitor_id":"badminton-evening","preset":5,"preferred_days":[1,2],"preferred_hours":[19,20],"interval_seconds":240,"auto_book":false}'
.venv/bin/sja monitors list
.venv/bin/sja monitors pause --json '{"monitor_id":"badminton-evening"}'
.venv/bin/sja monitors resume --json '{"monitor_id":"badminton-evening"}'
.venv/bin/sja monitors delete --json '{"monitor_id":"badminton-evening"}'
.venv/bin/sja keep-alive configure --json '{"enabled":true,"interval_minutes":15}'
.venv/bin/sja keep-alive run
.venv/bin/sja keep-alive status
.venv/bin/sja history list
.venv/bin/sja events list
```

`preferred_hours` 是期望开始小时；日期偏移随每天滚动。保活只有一份设置。监控/保活状态持久化，core 重启后恢复；关闭 CLI 或网页不影响它们。

### 会话恢复

密码与扫码登录都会保存完整 Cookie jar，保留运动站和 jAccount 各自的域名、路径、有效期。业务操作前、后台监控检查前和定期保活时，core 验证运动站登录；失效后使用保存的 jAccount 会话重新走官方授权跳转。只有账号一致且用户资料校验通过，才原子更新凭据并继续任务。并发检查共用一把恢复锁，恢复期间的退出登录或新登录不会被旧请求覆盖。

旧版本保存的运动站 Cookie 仍可使用，但没有 jAccount 会话。**更新后重新完成一次密码或扫码登录，才能启用自动恢复。** 服务器有效期未知，`expires_at` 返回 `null`；`verified_at` 为最近验证时间，`renewed_at` 为最近自动恢复时间。

`auth status` 返回 `status=online/renewed/login_required`。`keep-alive run` 额外可返回 `error`（网络/校园服务异常，保留凭据稍后重试）或 `session_changed`（检查期间凭据已变更，重新查询）；失败时 CLI 退出码为 1。`keep-alive status` 和配置、立即检查、`events list` 操作在未登录时也可用。`session.sso_available` 表示保存了未被本地判定失效的 SSO Cookie，不保证校园服务器仍接受它。

需要验证码、扫码或其他认证时，返回 `login_required` 并记录本地事件，停止自动授权重试；重新登录后继续验证。网络故障不会直接标记需要登录。成功恢复记录 `session_renewed` 事件；目前无外部推送。jAccount 会话也可能过期，不能保证永久免登录。恢复只发生在操作前，不会自动重发预约或取消请求；提交结果不明时仍应先查订单。

## 部署、数据与维护

```bash
.venv/bin/sja daemon status
.venv/bin/sja daemon logs
.venv/bin/sja daemon stop
```

生产环境建议 systemd 托管。`deploy/sja-sport.service` 默认路径为 `%h/Code/sJAutoSport`，按实际安装路径修改后放入 `~/.config/systemd/user/`，先停止已有手动启动的 core，再运行 `systemctl --user daemon-reload` 和 `systemctl --user enable --now sja-sport`。SSH 断开后继续运行需服务器管理员允许该用户 linger。Web API 可单独托管，浏览器访问建议通过 SSH 转发本机 5173/8000；该单人控制台没有额外的网站访问认证，不应直接公开到互联网。

`data/credentials.json` 是单账号凭证，`data/state.db` 保存任务、设置、预约记录和事件。目录及运行数据已忽略，凭证/图片以私有权限保存。可安装 `.[secure]` 并配置稳定的 `SJA_SECRET` 加密凭证；丢失密钥将无法读取已有凭证。代理环境默认忽略，需要使用代理时设 `SJA_TRUST_ENV=true`。

`./scripts/deploy.sh` 安装 Python Web 依赖并构建前端，不会替你重启服务。生产静态文件在 `frontend/dist`，反向代理 `/api` 到本机 8000，并为前端路由配置回退到 `index.html`。

## 验证与结构

```bash
.venv/bin/python -m pip install -c constraints.txt -e '.[web,test]'
.venv/bin/python -m pytest -q
cd frontend && npm run build
```

`sja_booking/` 是协议与业务 core；`web_api/` 只转发同一套操作；`frontend/` 是浏览器入口。CLI 命令也通过同一个后台实例执行。参见 [AGENTS.md](AGENTS.md)。

`tests/test_cli.py` 以独立 CLI 进程逐一执行 `sja schema` 中的全部命令，外部 HTTP / WebSocket 使用隔离模拟，实际运行登录协议、加密下单、退款、监控、卡片和保活逻辑，并检查退出码、图片权限和凭证脱敏。另有真实进程的后台启停、重启恢复及双入口共享状态测试。测试不连接真实预约或退款接口，不能代替真人扫码确认或真实订单支付验证。
