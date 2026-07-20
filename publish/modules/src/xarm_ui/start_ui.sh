#!/bin/bash
# XArm Web UI 启动脚本

# 设置颜色输出
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}🤖 XArm Web UI 启动脚本${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# 获取脚本所在目录
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# 检查Python环境
echo -e "${BLUE}📦 检查Python环境...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ 未找到Python3，请先安装Python3${NC}"
    exit 1
fi

echo -e "✓ Python版本: $(python3 --version)"
echo ""

# 检查并安装依赖
echo -e "${BLUE}📦 检查依赖包...${NC}"
if [ -f "requirements.txt" ]; then
    echo "正在检查/安装依赖..."
    pip3 install -q -r requirements.txt
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ 依赖包已就绪${NC}"
    else
        echo -e "${RED}❌ 依赖安装失败${NC}"
        exit 1
    fi
else
    echo -e "${RED}❌ 未找到 requirements.txt${NC}"
    exit 1
fi
echo ""

# 检查ROS2环境
echo -e "${BLUE}🤖 检查ROS2环境...${NC}"
if [ -z "$ROS_DISTRO" ]; then
    echo -e "${RED}⚠️  警告: 未检测到ROS2环境变量${NC}"
    echo "请先执行: source /opt/ros/humble/setup.bash"
    echo "以及: source ~/Documents/vlai/x_series/x_air/install/setup.bash"
    echo ""
    echo "是否继续启动 Web UI? (y/n)"
    read -r response
    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    echo -e "✓ ROS发行版: ${GREEN}$ROS_DISTRO${NC}"
fi
echo ""

# 检查端口占用
echo -e "${BLUE}🔍 检查端口5000...${NC}"
if lsof -Pi :5000 -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo -e "${RED}❌ 端口5000已被占用${NC}"
    echo "占用进程信息:"
    lsof -i :5000
    echo ""
    echo "是否要杀死占用进程? (y/n)"
    read -r response
    if [[ "$response" =~ ^[Yy]$ ]]; then
        kill -9 $(lsof -t -i:5000)
        echo -e "${GREEN}✓ 已清理端口${NC}"
    else
        exit 1
    fi
else
    echo -e "${GREEN}✓ 端口5000可用${NC}"
fi
echo ""

# 显示项目信息
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}📁 项目信息${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo "工作目录: $SCRIPT_DIR"
echo "访问地址: http://localhost:5000"
echo "日志级别: INFO"
echo ""

# 启动服务器
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}🚀 启动 Web UI 服务器...${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${GREEN}提示: 按 Ctrl+C 停止服务器${NC}"
echo ""

# 启动Python应用
python3 app.py

# 清理
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}👋 服务器已停止${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
