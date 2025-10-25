# Windows 平台 NapCatQQ 机器人部署指北

NapCatQQ 基于官方 NTQQ 客户端扩展 OneBot V11 协议，是在 Windows 上部署 QQ 机器人的主流方案。本指南介绍如何安装 NapCatQQ 并与体育预订项目联动，实现验证码协同、余票查询、自动抢票等指令。

---

## 1. 环境准备

1. **安装官方 NTQQ**  
   - 下载最新安装包（例如 `QQ9.9.9_x64.exe`）  
   - 安装并登录一次，确保能正常使用且已完成设备验证

2. **下载 NapCatQQ**  
   - 访问 <https://github.com/NapNeko/NapCatQQ/releases>  
   - 下载最新的 `NapCat-CLI.zip`（包含 NapCat CLI 工具）

3. **准备工作目录**  
   ```powershell
   mkdir C:\Bots\NapCat
   cd C:\Bots\NapCat
   tar -xf NapCat-CLI.zip   # 或使用解压软件解压
   ```

---

## 2. 安装 NapCatQQ

在 PowerShell 或 CMD 中执行（请将 `QQNT_PATH` 替换为真实路径，默认 `C:\Program Files\Tencent\QQNT`）：

```powershell
cd C:\Bots\NapCat
NapCat-CLI.exe install --qq-path "C:\Program Files\Tencent\QQNT"
```

成功后，NapCat 会在 QQNT 安装目录生成 `napcat\config.json`。

### 配置 OneBot 接口

编辑 `C:\Program Files\Tencent\QQNT\napcat\config.json`，保持 HTTP/WebSocket 开启（示例）：

```json
{
  "onebot": {
    "enable": true,
    "access_token": "",
    "http": {
      "enable": true,
      "host": "0.0.0.0",
      "port": 6099
    },
    "websocket": {
      "enable": true,
      "port": 6099,
      "access_token": ""
    }
  }
}
```

> 如需鉴权，可在 `access_token` 中填写自定义令牌，并在机器人 `.env` 中保持一致。

### 启动 NapCat

```powershell
cd C:\Program Files\Tencent\QQNT\napcat
NapCat-CLI.exe start
```

- 首次启动会唤起 QQ，按提示使用手机 QQ 扫码或短信确认。  
- 控制台输出 “NapCat 启动成功” 后，HTTP/WebSocket 接口即可使用。

> 提示：退出登录时请使用 `NapCat-CLI.exe stop`，避免残留进程。

---

## 3. 接入体育预订机器人

1. **配置环境变量**
   ```powershell
   cd C:\Path\To\sJAutoSport\bot
   copy env.example .env
   notepad .env
   ```

   `.env` 示例：
   ```ini
   NTQQ_WS_URL=ws://127.0.0.1:6099/onebot/v11/ws
   NTQQ_HTTP_URL=http://127.0.0.1:3000
   NTQQ_ACCESS_TOKEN=        # 若在 NapCat 中设置了 token，这里也需填写
   ```

2. **安装依赖并启动机器人**
   ```powershell
   pip install -r ..\requirements.txt
   python run.py
   ```

3. **常用 QQ 指令**
   - `登录` → 机器人下发验证码图片，回复 `验证码 123456` 完成 Cookie 登录
   - `登录状态` / `系统状态` / `任务列表` / `取消任务`
   - `查询 preset=13`、`预订 preset=13 date=0 time=18`
   - `监控 preset=5 time=21 auto`

---

## 4. 注册为 Windows 服务（可选）

使用 [NSSM](https://nssm.cc/download) 将 NapCat 和机器人托管为服务：

1. 安装 NapCat 服务：
   ```powershell
   nssm install NapCatQQ "C:\Program Files\Tencent\QQNT\napcat\NapCat-CLI.exe" start
   nssm set NapCatQQ Start SERVICE_AUTO_START
   nssm start NapCatQQ
   ```

2. 安装机器人服务（假设使用 `python`）：
   ```powershell
   nssm install SJAutoSportBot "C:\Path\To\python.exe" "C:\Path\To\sJAutoSport\bot\run.py"
   nssm set SJAutoSportBot Start SERVICE_AUTO_START
   nssm start SJAutoSportBot
   ```

---

## 5. 常见问题

| 现象 | 解决方案 |
| ---- | -------- |
| NapCat 运行报错 | 以管理员模式运行 CLI；在 QQ 目录执行；确认磁盘无只读限制 |
| 接口无响应 | 检查 `config.json`、`.env` 的端口/token 是否一致；查看 NapCat CLI 日志 |
| 频繁要求验证 | 在手机 QQ 的“设备管理”中将该设备设为常用设备；避免频繁换 IP |
| 机器人不响应指令 | 确认 NapCat 服务在线；查看 `bot/logs/bot.log` |

完成以上步骤后，Windows 环境即可通过 NapCatQQ 提供 OneBot 接口，与体育预订机器人协同工作，实现验证码协同、余票查询与自动化抢票等全流程。  
