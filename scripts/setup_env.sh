#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
CONFIG_DIR="$ROOT_DIR/config"
DATA_DIR="$ROOT_DIR/data"
FRONTEND_DIR="$ROOT_DIR/frontend"
BOT_DIR="$ROOT_DIR/bot"

timestamp() {
  date +"%Y-%m-%d %H:%M:%S"
}

prompt() {
  local __resultvar=$1
  local __prompt=$2
  local __default=$3
  local __input
  read -r -p "${__prompt} [${__default}]: " __input
  if [[ -z "${__input}" ]]; then
    printf -v "$__resultvar" '%s' "$__default"
  else
    printf -v "$__resultvar" '%s' "$__input"
  fi
}

confirm_overwrite() {
  local file=$1
  if [[ -f "$file" ]]; then
    read -r -p "文件 ${file} 已存在，是否覆盖？[y/N]: " answer
    if [[ ! "$answer" =~ ^[Yy]$ ]]; then
      return 1
    fi
  fi
  return 0
}

random_password() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -base64 18
  else
    # fallback
    date +%s | sha256sum | head -c 24
  fi
}

echo "== SJTU Sports 环境配置向导 =="
echo "工作目录: ${ROOT_DIR}"
echo

mkdir -p "$CONFIG_DIR" "$DATA_DIR"

default_env="${SJA_ENV:-development}"
default_frontend_domain="http://localhost:5173"
default_base_url="${SJA_BASE_URL:-https://sports.sjtu.edu.cn}"
default_bot_http="${BOT_HTTP_URL:-http://127.0.0.1:6099}"
default_ws_url="${NTQQ_WS_URL:-ws://127.0.0.1:6700/onebot/v11/ws}"
default_command_prefix="${BOT_COMMAND_PREFIX:-!}"
default_groups="${SJA_NOTIFICATION_GROUPS:-1071889524}"
default_users="${SJA_NOTIFICATION_USERS:-2890095056}"
default_interval="${SJA_MONITOR_INTERVAL:-240}"
default_credentials="${SJABOT_CREDENTIAL_STORE:-$DATA_DIR/credentials.json}"

prompt environment "运行环境 (development/production)" "$default_env"
environment=$(echo "$environment" | tr '[:upper:]' '[:lower:]')

if [[ "$environment" == "production" ]]; then
  default_api_base="${SJA_API_BASE_URL:-/api}"
else
  default_api_base="${SJA_API_BASE_URL:-http://localhost:8000/api}"
fi

prompt base_url "体育系统地址" "$default_base_url"
prompt api_base "前端访问的后端 API 地址" "$default_api_base"

default_password=$(random_password)
prompt portal_password "前端门户访问密码" "$default_password"

prompt bot_http_url "Bot HTTP 地址 (OneBot)" "$default_bot_http"
prompt bot_ws_url "Bot WebSocket 地址 (OneBot)" "$default_ws_url"
prompt bot_access_token "Bot Access Token (可选, 可留空)" "${BOT_ACCESS_TOKEN:-}"

prompt notify_groups "通知群组 ID (逗号分隔)" "$default_groups"
prompt notify_users "通知用户 ID (逗号分隔)" "$default_users"

prompt monitor_interval "监控任务间隔（秒）" "$default_interval"
prompt credential_store "凭据存储文件路径" "$default_credentials"
prompt command_prefix "机器人命令前缀" "$default_command_prefix"

deploy_env="$ROOT_DIR/deploy.env"
frontend_env="$FRONTEND_DIR/.env.production"
bot_env="$BOT_DIR/.env"
users_json="$CONFIG_DIR/users.json"

echo
echo "[1/4] 写入 ${deploy_env}"
if confirm_overwrite "$deploy_env"; then
  cat >"$deploy_env" <<EOF
# Generated at $(timestamp)
export SJA_ENV=${environment}
export SJA_BASE_URL=${base_url}
export BOT_HTTP_URL=${bot_http_url}
export BOT_ACCESS_TOKEN=${bot_access_token}
export SJA_NOTIFICATION_GROUPS=${notify_groups}
export SJA_NOTIFICATION_USERS=${notify_users}
export SJA_ENABLE_NOTIFICATION=true
export SJA_MONITOR_INTERVAL=${monitor_interval}
export SJABOT_CREDENTIAL_STORE=${credential_store}

# 可选：按需取消注释并覆盖默认值
# export SJA_MONITOR_PREFERRED_HOURS=18,19,20
# export SJA_MONITOR_PREFERRED_DAYS=0,1,2
# export SJA_SCHEDULE_HOUR=12
# export SJA_SCHEDULE_START_HOURS=18
# export SJA_USERS_FILE=${users_json}
EOF
  echo "已生成 deploy.env，请使用 'source deploy.env' 加载变量。"
else
  echo "跳过写入 deploy.env。"
fi

echo
echo "[2/4] 写入 ${frontend_env}"
if confirm_overwrite "$frontend_env"; then
  cat >"$frontend_env" <<EOF
# Generated at $(timestamp)
VITE_API_BASE_URL=${api_base}
VITE_PORTAL_PASSWORD=${portal_password}
EOF
  echo "已生成 frontend/.env.production。"
else
  echo "跳过写入 frontend/.env.production。"
fi

frontend_dev_env="$FRONTEND_DIR/.env"
if [[ ! -f "$frontend_dev_env" ]]; then
  cat >"$frontend_dev_env" <<EOF
VITE_API_BASE_URL=${api_base}
VITE_PORTAL_PASSWORD=${portal_password}
EOF
  echo "已创建前端开发环境配置 frontend/.env。"
fi

echo
echo "[3/4] 写入 ${bot_env}"
if confirm_overwrite "$bot_env"; then
  cat >"$bot_env" <<EOF
# Generated at $(timestamp)
DRIVER=~fastapi
NTQQ_WS_URL=${bot_ws_url}
NTQQ_HTTP_URL=${bot_http_url}
ONEBOT_WS_URL=${bot_ws_url}
ONEBOT_HTTP_URL=${bot_http_url}
ONEBOT_ACCESS_TOKEN=${bot_access_token}
BOT_COMMAND_PREFIX=${command_prefix}
LOG_LEVEL=INFO
HOT_RELOAD=false
EOF
  echo "已生成 bot/.env。"
else
  echo "跳过写入 bot/.env。"
fi

echo
echo "[4/4] 准备用户配置 ${users_json}"
if [[ ! -f "$users_json" ]]; then
  cat >"$users_json" <<'EOF'
[
  {
    "nickname": "demo",
    "username": "your-account@example.com",
    "password": "请替换为体育系统密码"
  }
]
EOF
  echo "已创建模板文件 ${users_json}，请编辑后填入真实账号。"
else
  echo "文件已存在，未覆盖。"
fi

touch "$credential_store"
echo "凭据将存储在: $credential_store"

cat <<EOF

=== 配置完成 ===
1. 请编辑 ${users_json}，替换示例账号/密码。
2. 部署或运行前执行：
   source ${deploy_env}
3. 首次构建前端：
   cd frontend && npm run build

祝使用愉快！
EOF
