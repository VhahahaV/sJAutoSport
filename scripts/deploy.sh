#!/bin/bash

################################################################################
# SJTU Sports Auto-Booking 部署脚本
# 
# 功能：
# - 检查系统环境
# - 更新代码（如果需要）
# - 安装/更新依赖
# - 构建前端
# - 重启所有服务
# - 验证部署状态
################################################################################

set -e  # 遇到错误立即退出

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 日志函数
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 脚本配置
PROJECT_DIR="/home/deploy/sJAutoSport"
VENV_PYTHON="/root/miniconda3/envs/sJAutoSport/bin/python"
FRONTEND_DIR="${PROJECT_DIR}/frontend"
FRONTEND_DEPLOY_DIR="/opt/sja/frontend/dist"
ENV_FILE="/etc/sja/env"

# 检查是否为 root 用户
check_root() {
    if [ "$EUID" -ne 0 ]; then
        log_error "请使用 root 用户运行此脚本"
        exit 1
    fi
}

# 检查环境
check_environment() {
    log_info "检查系统环境..."
    
    # 检查项目目录
    if [ ! -d "$PROJECT_DIR" ]; then
        log_error "项目目录不存在: $PROJECT_DIR"
        exit 1
    fi
    
    # 检查 Python 环境
    if [ ! -f "$VENV_PYTHON" ]; then
        log_error "Python 环境不存在: $VENV_PYTHON"
        exit 1
    fi
    
    # 检查环境变量文件
    if [ ! -f "$ENV_FILE" ]; then
        log_error "环境变量文件不存在: $ENV_FILE"
        exit 1
    fi
    
    log_success "环境检查通过"
}

# 检查服务状态
check_services_status() {
    log_info "检查服务状态..."
    
    local services=("sja-api.service" "sja-bot.service" "caddy.service")
    local napcat_running=false
    
    for service in "${services[@]}"; do
        if systemctl is-active --quiet "$service"; then
            log_success "$service 正在运行"
        else
            log_warning "$service 未运行"
        fi
    done
    
    # 检查 NapCat 容器
    if docker ps | grep -q napcat; then
        log_success "NapCat 容器正在运行"
        napcat_running=true
    else
        log_warning "NapCat 容器未运行"
    fi
    
    return 0
}

# 更新代码（如果使用 git）
update_code() {
    log_info "更新代码..."
    
    cd "$PROJECT_DIR"
    
    # 检查是否为 git 仓库
    if [ -d .git ]; then
        log_info "从 Git 拉取最新代码..."
        git pull || log_warning "Git pull 失败或没有远程仓库"
    else
        log_warning "不是 Git 仓库，跳过代码更新"
    fi
}

# 更新 Python 依赖
update_dependencies() {
    log_info "更新 Python 依赖..."
    
    cd "$PROJECT_DIR"
    
    if [ -f requirements.txt ]; then
        log_info "安装/更新依赖包..."
        "$VENV_PYTHON" -m pip install --upgrade pip
        "$VENV_PYTHON" -m pip install -r requirements.txt
        log_success "依赖安装完成"
    else
        log_error "requirements.txt 不存在"
        return 1
    fi
}

# 构建前端
build_frontend() {
    log_info "构建前端..."
    
    if [ ! -d "$FRONTEND_DIR" ]; then
        log_error "前端目录不存在: $FRONTEND_DIR"
        return 1
    fi
    
    cd "$FRONTEND_DIR"
    
    # 检查是否需要安装 npm 依赖
    if [ ! -d "node_modules" ]; then
        log_info "安装 npm 依赖..."
        npm install
    fi
    
    # 构建
    log_info "开始构建前端..."
    npm run build
    
    if [ -d "dist" ]; then
        log_success "前端构建完成"
    else
        log_error "前端构建失败"
        return 1
    fi
}

# 部署前端
deploy_frontend() {
    log_info "部署前端到生产环境..."
    
    # 创建部署目录
    mkdir -p "$FRONTEND_DEPLOY_DIR"
    
    # 备份旧版本
    if [ -d "$FRONTEND_DEPLOY_DIR" ] && [ "$(ls -A $FRONTEND_DEPLOY_DIR)" ]; then
        log_info "备份旧版本..."
        mv "$FRONTEND_DEPLOY_DIR" "${FRONTEND_DEPLOY_DIR}.bak.$(date +%Y%m%d_%H%M%S)"
        mkdir -p "$FRONTEND_DEPLOY_DIR"
    fi
    
    # 复制新版本
    log_info "复制新文件..."
    cp -r "$FRONTEND_DIR/dist"/* "$FRONTEND_DEPLOY_DIR"/
    chmod -R 755 "$FRONTEND_DEPLOY_DIR"
    
    log_success "前端部署完成: $FRONTEND_DEPLOY_DIR"
}

# 重启服务
restart_services() {
    log_info "重启服务..."
    
    # 重新加载 systemd
    systemctl daemon-reload
    
    # 重启 API 服务
    log_info "重启 sja-api.service..."
    systemctl restart sja-api.service
    sleep 2
    
    # 重启 Bot 服务
    log_info "重启 sja-bot.service..."
    systemctl restart sja-bot.service
    sleep 2
    
    # 重启 Caddy
    # log_info "重启 caddy.service..."
    # systemctl restart caddy.service
    # sleep 2
    
    # # 重启 NapCat 容器
    # if docker ps -a | grep -q napcat; then
    #     log_info "重启 NapCat 容器..."
    #     docker restart napcat || log_warning "NapCat 容器重启失败"
    #     sleep 2
    # fi
    
    log_success "所有服务已重启"
}

# 验证部署
verify_deployment() {
    log_info "验证部署状态..."
    
    local success=true
    
    # 检查服务状态
    log_info "检查服务状态..."
    if ! systemctl is-active --quiet sja-api.service; then
        log_error "sja-api.service 未运行"
        success=false
    fi
    
    if ! systemctl is-active --quiet sja-bot.service; then
        log_error "sja-bot.service 未运行"
        success=false
    fi
    
    if ! systemctl is-active --quiet caddy.service; then
        log_error "caddy.service 未运行"
        success=false
    fi
    
    if ! docker ps | grep -q napcat; then
        log_error "NapCat 容器未运行"
        success=false
    fi
    
    # 检查端口
    log_info "检查端口监听..."
    local ports=(8000 8080 3000 443)
    for port in "${ports[@]}"; do
        if ! netstat -tlnp | grep -q ":$port "; then
            log_warning "端口 $port 未监听"
        else
            log_success "端口 $port 正在监听"
        fi
    done
    
    # API 健康检查
    log_info "检查 API 健康状态..."
    if curl -s http://localhost:8000/api/system/health > /dev/null; then
        log_success "API 健康检查通过"
    else
        log_error "API 健康检查失败"
        success=false
    fi
    
    # 显示服务状态
    log_info "服务状态："
    systemctl status sja-api.service --no-pager -l
    echo ""
    systemctl status sja-bot.service --no-pager -l
    echo ""
    
    if [ "$success" = true ]; then
        log_success "部署验证通过！"
        return 0
    else
        log_error "部署验证失败，请检查日志"
        return 1
    fi
}

# 显示日志
show_logs() {
    log_info "显示最近的服务日志..."
    
    echo -e "\n${BLUE}=== sja-api 日志（最近20行）===${NC}"
    journalctl -u sja-api.service -n 20 --no-pager
    
    echo -e "\n${BLUE}=== sja-bot 日志（最近20行）===${NC}"
    journalctl -u sja-bot.service -n 20 --no-pager
    
    echo -e "\n${BLUE}=== NapCat 日志（最近20行）===${NC}"
    docker logs napcat --tail 20 2>/dev/null || echo "无法获取 NapCat 日志"
}

# 主函数
main() {
    echo -e "${GREEN}"
    echo "╔════ ^╗ ════╗"
    echo "║ SJTU Sports Auto-Booking   ║"
    echo "║ 部署脚本                  ║"
    echo "╚═══════════════════════════╝"
    echo -e "${NC}"
    
    local mode="${1:-full}"
    
    check_root
    
    case "$mode" in
        "full")
            log_info "执行完整部署..."
            check_environment
            check_services_status
            update_code
            update_dependencies
            build_frontend
            deploy_frontend
            restart_services
            sleep 3
            verify_deployment
            show_logs
            ;;
        "restart")
            log_info "仅重启服务..."
            restart_services
            sleep 3
            verify_deployment
            ;;
        "frontend")
            log_info "仅更新前端..."
            build_frontend
            deploy_frontend
            systemctl restart caddy.service
            log_success "前端更新完成"
            ;;
        "deps")
            log_info "仅更新依赖..."
            update_dependencies
            restart_services
            ;;
        "verify")
            log_info "仅验证部署状态..."
            check_services_status
            verify_deployment
            ;;
        "status")
            log_info "显示服务状态..."
            check_services_status
            systemctl status sja-api.service sja-bot.service --no-pager
            docker ps | grep napcat || echo "NapCat 未运行"
            ;;
        "logs")
            show_logs
            ;;
        *)
            echo "用法: $0 [模式]"
            echo ""
            echo "模式选项："
            echo "  full      - 完整部署（默认）：更新代码、依赖、前端，并重启所有服务"
            echo "  restart   - 仅重启服务"
            echo "  frontend  - 仅更新前端"
            echo "  deps      - 仅更新 Python 依赖"
            echo "  verify    - 仅验证部署状态"
            echo "  status    - 显示服务状态"
            echo "  logs      - 显示服务日志"
            echo ""
            exit 1
            ;;
    esac
    
    echo ""
    log_success "部署脚本执行完成！"
    echo ""
    echo "💡 提示："
    echo "  - 查看实时日志: journalctl -u sja-api.service -f"
    echo "  - 查看服务状态: systemctl status sja-api.service sja-bot.service"
    echo "  - 查看 NapCat: docker logs napcat -f"
    echo "  - 检查端口: netstat -tlnp | grep -E ':(8000|8080|3000|443)'"
}

# 运行主函数
main "$@"

