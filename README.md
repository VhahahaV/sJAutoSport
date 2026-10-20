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
.venv/bin/sja orders create --json '{"preset":5,"date":"YYYY-MM-DD","start_time":"19:00","end_time":"20:00","request_id":"UNIQUE_REQUEST_ID"}'
.venv/bin/sja orders reconcile --json '{"request_id":"UNIQUE_REQUEST_ID"}'
.venv/bin/sja orders cancel --json '{"order_id":"ORDER_ID"}'
```

`date` 可以为真实日期或天数偏移（`0` 今天、`1` 明天）。命令示例中的日期和 ID 需替换。查询空列表不会替换为其他日期。提交预约/取消前应取得用户对具体操作的授权。`orders.create` 每个新请求最多发送一次预约 POST，不会失败后换场次或自动重发。重复的 `request_id` 和相同参数返回已保存结果；改变参数必须使用新 ID。

返回状态包括 `success`、`not_submitted`、`rejected`、`login_required`、`challenge_required` 和 `unknown`。超时、响应损坏、响应缺少订单号会进入 `unknown`；core 在发出请求前保存记录，因此重启后也会阻止新的预约。`orders.reconcile` 只查询订单，找到目标有效订单才确认成功；空列表不能证明预约失败。只有用户在官方页面核实未生成订单并明确确认后，才能传 `confirm_not_created: true` 解除阻止，agent 不得自行根据空列表设置此参数。网页提供相同的核对流程。人工验证码须由用户完成。监控遇到结果未知、登录失效或人工验证时自动暂停。

#### 复用查询与候选预约

`slots.list` 返回 `snapshot_id`、`expires_at` 和不包含签名的 `slot_id`。真实 `dateId`、`sign` 只留在 core 内存中。快照绑定账号、会话、场馆和运动，从查询开始最多保留 60 秒；core 重启、会话改变或快照过期后需重新查询。这是本地保守上限，不是校园服务器承诺的 token 有效期。核心复用 HTTP 连接和最多十分钟的场馆配置；日期和场次仍在每次新查询时刷新。

```bash
# 查询一次；从结果中选择日期、时段和 snapshot_id
.venv/bin/sja slots list --json '{"preset":5,"date":"YYYY-MM-DD","show_full":true}'
# 直接使用快照，跳过重复的日期/场次查询；candidate_id 可选，指定某个 slot_id
.venv/bin/sja orders create --json '{"preset":5,"date":"YYYY-MM-DD","start_time":"19:00","end_time":"20:00","snapshot_id":"SNAPSHOT_ID","request_id":"UNIQUE_REQUEST_ID"}'
# 有序候选：同一场馆、运动、日期；最多成功一笔。省略 snapshot_id 时只查询一次。
.venv/bin/sja orders cascade --json '{"preset":5,"date":"YYYY-MM-DD","preferences":[{"start_time":"19:00"},{"start_time":"20:00"}],"max_price":50,"max_attempts":3,"snapshot_id":"SNAPSHOT_ID","request_id":"UNIQUE_CASCADE_ID"}'
```

候选按 `preferences` 顺序筛选，单个偏好可指定 `end_time` 和 `candidate_id`。无余位或超出价格上限的候选不发请求；成功即停止，最多 5 次提交。默认 `continue_on_codes: []`，服务端拒绝后停止。只有独立验证某业务码明确表示“没有创建订单、可以换候选”后，调用者才可显式填写该码；不得猜测，也不得根据空订单列表认定某码安全。500、认证、验证码、限流和资料补全代码禁止加入。超时或结果未知始终停止。此设计保留单次 `orders.create` 的一次 POST 契约，且不承诺满场失败后一定能继续。

下单结果的 `response_info` 保留 `http_status`、`business_code`、`received_at` 和脱敏的 `server_message`；网络异常只保留异常类型。原始提示限制为 500 字符，屏蔽已知账号、凭据、签名，以及邮箱、长数字和疑似 token。不会保存任意响应正文、请求头或加密载荷。该信息随预约尝试持久化，在同一请求重放及结果核对后保留；候选预约的每次提交也分别记录。错误提示只是诊断证据，不是允许重新下单的凭据。

2026-10-20 的受控协议实验：

| 接口与条件 | HTTP 状态 | 业务码 | 服务器提示 / 结果 |
| --- | --- | --- | --- |
| 场次查询，使用刚获取的 `dateId` | 200 | 0 | 返回 240 个场次 |
| 同一查询，省略 `dateId` | 200 | 500 | 非法请求 |
| 同一查询，仅修改 `dateId` 一个字节 | 200 | 500 | 非法请求 |
| 单次下单，仅修改 `sign` 一个字节 | 200 | 500 | 服务器错误，请联系管理员 |
| 单次下单，保留真实签名，选择查询结果中余量为 0 的场次 | 200 | 500 | 场地…已被预定，请重新选择时段。 |
| 旧 sign 保留约 121 秒，期间刷新场次，再使用旧 sign 下单 | 200 | 500 | 场地信息已过期，请刷新页面重新下单 |
| 刷新场次后立即使用旧 sign（约 3 秒）下单 | 200 | 0 | 成功，订单已取消并核对，未付款 |
| 不刷新场次，只等待约 120 秒后使用旧 sign 下单 | 200 | 500 | 场地信息已过期，请刷新页面重新下单 |

这些结果确认业务码 500 被参数校验失败、签名异常、凭据过期和场次冲突共用。界面及 CLI 展示脱敏的原始提示，避免把所有 500 都描述为服务器故障；状态仍为 `unknown`。不能仅凭数字码、错误文字或空订单列表证明服务端没有创建订单。改动签名和满场两次实验均已由用户在官方页面核实未新增订单，并按人工确认流程解除阻止。满场实验使用专用实验脚本模拟查询后余位被占用的冲突分支，生产代码仍在本地拦截不可预约场次；只提交一次，未自动尝试其他候选，也未支付。此前未保留原始提示的满场记录不用于判断具体拒绝原因。

日期凭据的只读对照实验（南区体育馆乒乓球）：10 月 27 日同一个 `dateId` 在获取后 10、30、60、120 秒均能查询；生成新 `dateId` 后，旧值仍能查询。把它用于 10 月 26 日返回“非法请求”，该日自己的 token 查询正常，支持日期绑定的判断。这里只测得这次样本至少可查询 120 秒，没有测得有效期上限。

同账号跨会话只读对照：通过正常 jAccount 授权取得不同的运动站 Cookie 后，旧 `dateId` 在新旧两个会话中均返回 240 个场次，新会话自己的 token 也查询正常，原会话仍有效。这支持该样本不严格绑定单个运动站会话；未验证跨账号或下单签名的会话绑定。core 仍在会话变化时清除预约快照，不能把查询层实验推广为允许跨会话提交旧签名。

下单签名的对照实验：10 月 26 日的旧 `sign` 在刷新场次后约 3 秒仍能成功预约；不刷新、仅等待约 120 秒则被提示已过期。此前同时等待和刷新的约 121 秒实验也被提示过期。这支持签名存在时效限制，而非每次新查询立即使旧签名失效；尚未测得精确阈值，不能推广为所有场馆或账号的固定规则。生产快照仍限 60 秒，这是本地保守设置而非已验证的服务端有效期；延迟实验仅在隔离脚本中临时放宽本地限制，未更改 core 默认值。日期 token 的查询有效期不能直接用于设置下单签名的缓存时间。

官网公开 PC 脚本中，下单页明确处理 0（成功）、1002（人工验证）、10001（完善资料），其他错误通常只显示提示；未发现完整拒绝码表或按客户端请求编号核对下单结果的用法。`/venue/personal/checkRule` 用于展示预约频次信息，不是订单事务查询。现阶段没有已确认可自动继续的校园拒绝码；验证需要结合具体接口、HTTP 状态、业务原因，以及服务端关于未创建订单的可靠证据，不能把不同接口的同号错误混用。

网页预约复用刚展示的查询结果，过期后提示刷新并重新选择。CLI 与 HTTP `/api/core/orders.cascade` 共享同一契约；高级候选参数可通过 `sja schema` 查询。`timings_ms` 区分 core 排队、认证、元数据、日期、场次、加密和确认请求；查询时间包含本地节流。总览等独立只读请求可以并行运行，不占用下单命令锁。以上均不改变校园开放时间、取消次数或支付规则。

取消流程按官方返回分支处理：未支付订单返回码 4 时已取消，不再发送退款后续请求；已支付订单按 1 → 2 → 3 提交退款流程。待支付状态 0/9 可以取消；状态 1 还需校园取消标志允许。已取消、已使用订单不显示取消按钮。

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
