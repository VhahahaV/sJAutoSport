# macOS 平台 NapCatQQ 机器人部署指北

NapCatQQ 依赖官方 Windows NTQQ 客户端。本指南提供在 macOS 上通过 Wine/CrossOver/Whisky 等工具运行 NTQQ + NapCat 的通用流程，实现与体育预订机器人协同工作。

---

## 1. 环境准备

| 组件 | 建议选择 | 说明 |
| ---- | -------- | ---- |
| macOS | 12 Monterey 及以上 | 需开启 Rosetta（Apple Silicon） |
| Wine 兼容层 | Whisky / CrossOver / WineHQ | 用于运行 Windows 程序 |
| Windows NTQQ 安装包 | 最新版 | 从 QQ 官网获取 |
| NapCatQQ | 最新 release | <https://github.com/NapNeko/NapCatQQ> |
| QQ 小号 | 独立账号 | 建议开启设备锁、安全验证 |

推荐使用 [Whisky](https://github.com/Whisky-App/Whisky)（免费且基于 Wine），以下步骤以 Whisky + Wine64 为例，其他工具可自行调整。

1. 安装 Whisky（或 WineHQ/CrossOver），创建 64-bit 容器（prefix）。
2. 在容器内安装依赖运行库（Whisky “高级设置” → 添加组件），建议包含：
   - Visual C++ 2015-2022
   - .NET 4.8
   - corefonts

---

## 2. 安装 NTQQ 与 NapCatQQ

1. 下载 Windows 版 NTQQ（例如 `QQ9.9.9_x64.exe`），在 Whisky 容器中运行安装：
   - 打开 Whisky 容器 → “运行 EXE” → 选择 NTQQ 安装包
   - 完成向导后，记录安装目录（通常位于 `drive_c/Program Files/Tencent/QQNT`）

2. 下载 NapCat-CLI：
   ```bash
   mkdir -p ~/Bots/NapCat && cd ~/Bots/NapCat
   curl -L -o NapCat-CLI.zip https://github.com/NapNeko/NapCatQQ/releases/latest/download/NapCat-CLI.zip
   unzip NapCat-CLI.zip
   ```

3. 在同一容器内运行 NapCat 安装命令：
   ```bash
   # 假设容器路径挂载在 ~/Library/Application Support/com.whiskyapp.Whisky/Containers/QQ
   export WINEPREFIX="~/Library/Application Support/com.whiskyapp.Whisky/Containers/QQ/prefix"
   wine NapCat-CLI.exe install --qq-path "C:\Program Files\Tencent\QQNT"
   ```
   安装成功后，QQNT 目录会生成 `napcat/config.json`。

4. 编辑 `napcat/config.json` 使 OneBot HTTP/WebSocket 启用：
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

5. 启动 NapCat：
   ```bash
   export WINEPREFIX="~/Library/Application Support/com.whiskyapp.Whisky/Containers/QQ/prefix"
   wine NapCat-CLI.exe start
   ```
   首次运行会弹出 QQ 窗口，使用手机 QQ 扫码或短信验证完成登录。

---

## 3. 配置体育预订机器人

1. 设置环境变量：
   ```bash
   cd ~/Code/sJAutoSport/bot
   cp env.example .env
   ```
   `.env` 示例：
   ```ini
   NTQQ_WS_URL=ws://127.0.0.1:6099/onebot/v11/ws
   NTQQ_HTTP_URL=http://127.0.0.1:6099
   NTQQ_ACCESS_TOKEN=              # 若 NapCat 设置了 token，这里也需填写
   ```

2. 安装依赖并运行机器人：
   ```bash
   pip install -r ../requirements.txt
   python run.py
   ```

3. 常见 QQ 指令：
   - `登录` → 按机器人提示回复 `验证码 123456` 完成 Cookie 登录
   - `登录状态` / `系统状态` / `任务列表` / `取消任务`
   - `查询 preset=13`、`预订 preset=13 date=0 time=18`
   - `监控 preset=5 time=21 auto`

---

## 4. 启动与守护

- Whisky/CrossOver 支持“开机启动容器”，可自动运行 NapCat。
- 机器人可使用 `launchctl` 或 `pm2` 守护：
  ```bash
  python bot/run.py    # 手动
  ```
  或创建 `~/Library/LaunchAgents/com.napcat.bot.plist` 托管。

---

## 5. 常见问题

| 现象 | 处理建议 |
| ---- | -------- |
| 容器启动 NapCat 时报错 | 确认运行库已安装；清理前缀后重新安装 NTQQ 与 NapCat |
| NTQQ 登录反复要求验证 | 在手机 QQ 中将该设备标记为“常用设备”；避免频繁换 IP |
| OneBot 接口不可用 | 检查 `config.json`、`.env` 的端口/token 是否一致；查看 NapCat CLI 日志 |
| macOS 休眠导致掉线 | 在“节能”中关闭自动睡眠，或使用 `caffeinate` 常驻 |

完成以上步骤后，macOS 环境即可运行 NapCatQQ 并与体育预订机器人联动，实现验证码协同、余票查询与自动抢票的完整指令链路。  
