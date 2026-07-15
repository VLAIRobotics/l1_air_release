#!/bin/bash
# fix_services.sh - 配置 CAN 监听服务，开机自启

set -e

echo "=== 配置 XArm CAN 监听服务 ==="

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
WORK_DIR="$SCRIPT_DIR"
CAN_SETUP_SCRIPT="$SCRIPT_DIR/../../../xarm_can/package/libexec/setup_can_interfaces.sh"

# 1. 检查文件是否存在
echo "1. 检查必要文件..."
if [ ! -f "$WORK_DIR/can_listener_trigger.sh" ]; then
    echo "错误: $WORK_DIR/can_listener_trigger.sh 不存在"
    exit 1
fi

if [ ! -f "$CAN_SETUP_SCRIPT" ]; then
    echo "错误: $CAN_SETUP_SCRIPT 不存在"
    exit 1
fi

# 2. 设置执行权限
echo "2. 设置脚本执行权限..."
chmod +x "$WORK_DIR"/can_listener_trigger.sh 2>/dev/null || true
chmod +x "$CAN_SETUP_SCRIPT" 2>/dev/null || true

# 3. 创建/更新 setup-can.service
echo "3. 创建/更新 setup-can.service..."
sudo tee /etc/systemd/system/setup-can.service > /dev/null << EOF
[Unit]
Description=Setup CAN Interfaces
After=network.target

[Service]
Type=oneshot
User=root
ExecStart=$CAN_SETUP_SCRIPT
RemainAfterExit=yes
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# 4. 创建/更新 can-listener.service
echo "4. 创建/更新 can-listener.service..."
sudo tee /etc/systemd/system/can-listener.service > /dev/null << EOF
[Unit]
Description=CAN Listener Trigger Service
After=network.target setup-can.service
Requires=setup-can.service

[Service]
Type=simple
User=root
WorkingDirectory=$WORK_DIR
Environment="PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ExecStart=/bin/bash $WORK_DIR/can_listener_trigger.sh
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# 5. 重新加载 systemd
echo "5. 重新加载 systemd 配置..."
sudo systemctl daemon-reload

# 6. 启用服务
echo "6. 设置开机自启动..."
sudo systemctl enable setup-can.service
sudo systemctl enable can-listener.service

# 7. 验证状态
echo "7. 验证服务状态..."
echo "setup-can.service: $(systemctl is-enabled setup-can.service)"
echo "can-listener.service: $(systemctl is-enabled can-listener.service)"

# 8. 显示完成信息
echo ""
echo "=== 服务配置完成 ==="
echo ""
echo "服务文件位置:"
echo "  - /etc/systemd/system/setup-can.service"
echo "  - /etc/systemd/system/can-listener.service"
echo ""
echo "测试命令:"
echo "  sudo systemctl start setup-can.service"
echo "  sudo systemctl start can-listener.service"
echo "  sudo systemctl status setup-can.service can-listener.service"
echo "  sudo journalctl -u setup-can.service -u can-listener.service -f"
echo "  sudo reboot  # 重启验证开机自启"
echo ""
echo "监听脚本内容:"
echo "  cat $WORK_DIR/can_listener_trigger.sh"
