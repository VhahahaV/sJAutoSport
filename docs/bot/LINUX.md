# Linux（含 Wine）平台 NapCatQQ 机器人部署指北

NapCatQQ 基于官方 NTQQ 客户端提供 OneBot V11 接口，可直接与本项目的 QQ 机器人配合，实现验证码协同、余票查询、自动化抢票等功能。本文介绍如何在 Linux 环境下（原生或通过 Wine）部署 NapCatQQ。

---

## 1. 环境准备

| 组件 | 建议版本 | 说明 |
| ---- | -------- | ---- |
| 操作系统 | Ubuntu 20.04+/Debian 11+/CentOS 8+ | 其他发行版需自行调整命令 |
| Wine & Winetricks | Wine 8.x+ | NapCat 依赖 Windows 版 NTQQ，需要 Wine 环境 |
| QObject | 官方 Windows NTQQ 安装包 | 在 Wine 前缀中安装 |
| NapCatQQ | 最新 release | <https://github.com/NapNeko/NapCatQQ> |
| QQ 小号 | 独立帐号 | 建议启用设备锁、短信验证 |

安装 Wine（以 Ubuntu 为例）：

```bash
sudo dpkg --add-architecture i386
sudo apt update
sudo apt install -y wine64 wine32 winetricks unzip wget git
```

初始化 Wine 前缀：
```bash
export WINEPREFIX=$HOME/.wine-ntqq
winecfg                         # 首次运行创建前缀，可在弹窗中选择 Windows 10
winetricks corefonts            # 建议安装常用运行库
```

---

## 2. 安装 NTQQ 与 NapCatQQ

1. 下载 Windows 版 NTQQ 安装包并运行（路径仅供参考）：
   ```bash
   wget -O $HOME/Downloads/QQNT.exe https://installer.qq.com/qqnt/QQ9.9.9_x64.exe
   WINEPREFIX=$HOME/.wine-ntqq wine $HOME/Downloads/QQNT.exe
   ```
   安装完成后记住目录（默认 `C:\Program Files\Tencent\QQNT`）。

2. 下载 NapCatQQ CLI：
   ```bash
   mkdir -p $HOME/Bots/NapCat && cd $HOME/Bots/NapCat
   wget https://github.com/NapNeko/NapCatQQ/releases/latest/download/NapCat-CLI.zip
   unzip NapCat-CLI.zip
   ```

3. 在 Wine 环境中注入 NapCat：
   ```bash
   export WINEPREFIX=$HOME/.wine-ntqq
   wine NapCat-CLI.exe install --qq-path "C:\Program Files\Tencent\QQNT"
   ```
   成功后，QQNT 目录会生成 `napcat/config.json`。

4. 修改 `napcat/config.json` 以启用 OneBot HTTP/WebSocket：
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

5. 启动 NapCat 和 QQ：
   ```bash
   export WINEPREFIX=$HOME/.wine-ntqq
   wine NapCat-CLI.exe start
   ```
   - 首次启动会弹出 QQ 窗口，请使用手机 QQ 扫码或短信验证。
   - 终端提示 NapCat 已挂载后，HTTP/WebSocket 服务会监听在 6099 端口。

---

## 3. 配置体育预订机器人

1. 配置环境变量：
   ```bash
   cd ~/Code/sJAutoSport/bot
   cp env.example .env
   ```
   `.env` 示例：
   ```ini
   NTQQ_WS_URL=ws://127.0.0.1:6099/onebot/v11/ws
   NTQQ_HTTP_URL=http://127.0.0.1:6099
   NTQQ_ACCESS_TOKEN=              # 若 NapCat 启用了 token，请保持一致
   ```

2. 安装依赖并启动机器人：
   ```bash
   pip install -r ../requirements.txt
   python run.py
   ```

3. 常见 QQ 指令（私聊/群聊均可）：
   - `登录` → NapCat 下发验证码图片，回复 `验证码 123456` 完成 Cookie 登录
   - `登录状态` / `系统状态` / `任务列表` / `取消任务`
   - `查询 preset=13`、`预订 preset=13 date=0 time=18`
   - `监控 preset=5 time=21 auto`：启动余票监控并自动抢票

---

## 4. 可选：systemd 守护 NapCat

```bash
sudo tee /etc/systemd/system/napcat.service <<'EOF'
[Unit]
Description=NapCatQQ via Wine
After=network.target

[Service]
Type=simple
User=YOUR_USER
Environment=WINEPREFIX=/home/YOUR_USER/.wine-ntqq
WorkingDirectory=/home/YOUR_USER/Bots/NapCat
ExecStart=/usr/bin/wine NapCat-CLI.exe start
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now napcat.service
```

若需守护 Python 机器人，可另建 `bot.service`（或使用 `tmux`/`screen`）。

---

## 5. 常见问题

| 现象 | 排查建议 |
| ---- | -------- |
| NapCat CLI 报缺少运行库 | 按 NapCat 文档安装 .NET/VC 依赖，或 `winetricks dotnet48 vcrun2022` |
| QQ 启动黑屏或崩溃 | 检查显卡驱动、Wine 版本，必要时在 `winecfg` 勾选虚拟桌面 |
| OneBot 接口无响应 | 检查 `config.json`、`.env` 端口与 token；查看 NapCat log |
| 频繁掉线 | 避免频繁更换 IP，开启 QQ 安全设备信任；在 NapCat CLI 中启用自动重连 |

完成以上步骤后，Linux 环境即可通过 NapCatQQ 向机器人提供稳定的 OneBot 接口，与体育预订系统实现全流程 QQ 交互。  
