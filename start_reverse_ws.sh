#!/bin/bash

# 反向 WebSocket 模式完整启动脚本
# 1. 启动 NapCat Docker 容器
# 2. 启动 NoneBot（反向 WS 服务端）

echo "🎯 启动反向 WebSocket 模式"
echo "================================"

# 检查 Docker 是否运行
if ! docker info >/dev/null 2>&1; then
    echo "❌ Docker 未运行，请先启动 Docker"
    exit 1
fi

# 1. 启动 NapCat 容器
echo "🐳 启动 NapCat 容器..."
./start_napcat.sh

# 等待 NapCat 启动
echo "⏳ 等待 NapCat 启动..."
sleep 5

# 检查 NapCat 是否启动成功
if ! docker ps | grep -q napcat; then
    echo "❌ NapCat 容器启动失败"
    exit 1
fi

echo "✅ NapCat 容器启动成功"
echo ""

# 2. 启动 NoneBot
echo "🤖 启动 NoneBot（反向 WS 服务端）..."
echo "📋 配置信息："
echo "   - WS 服务端地址: ws://0.0.0.0:8080/onebot/v11/ws"
echo "   - Access Token: 123456"
echo "   - NapCat 将连接到: ws://127.0.0.1:8080/onebot/v11/ws?access_token=123456"
echo ""

# 启动 NoneBot
cd "$(dirname "$0")"
python sjtu_sports.py bot

echo ""
echo "🎉 反向 WebSocket 模式启动完成！"
echo "📱 请在 NapCat WebUI 中配置反向 WebSocket 客户端"
