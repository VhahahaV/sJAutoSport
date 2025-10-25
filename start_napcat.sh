#!/bin/bash

# NapCat Docker 启动脚本 - 反向 WebSocket 模式
# NoneBot 作为 WS 服务端，NapCat 作为客户端连接

echo "🚀 启动 NapCat Docker 容器（反向 WebSocket 模式）"

# 停止并删除现有容器
echo "🛑 停止现有容器..."
docker rm -f napcat 2>/dev/null

# 创建必要的目录
echo "📁 创建配置目录..."
mkdir -p /opt/napcat/qq
mkdir -p /opt/napcat/config

# 启动 NapCat 容器（使用 host 网络模式）
echo "🐳 启动 NapCat 容器..."
docker run -d --name napcat --restart=always \
  --network host \
  -e NAPCAT_UID=$(id -u) -e NAPCAT_GID=$(id -g) \
  -v /opt/napcat/qq:/app/.config/QQ \
  -v /opt/napcat/config:/app/napcat/config \
  mlikiowa/napcat-docker:latest

echo "✅ NapCat 容器已启动"
echo ""
echo "📋 配置说明："
echo "1. 访问 NapCat WebUI: http://localhost:6099"
echo "2. 配置反向 WebSocket 客户端："
echo "   - URL: ws://127.0.0.1:8080/onebot/v11/ws?access_token=123456"
echo "   - 消息格式: Array"
echo "   - 上报自身消息: 关闭"
echo "3. 配置 HTTP Server（可选）:"
echo "   - 地址: 0.0.0.0:3000"
echo "   - Token: 123456"
echo ""
echo "🔍 检查容器状态："
docker ps | grep napcat
echo ""
echo "📊 查看容器日志："
echo "docker logs -f napcat"
