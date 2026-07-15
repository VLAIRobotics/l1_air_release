#!/bin/bash
#
# CAN 监听触发器脚本
# 功能：监听 can2 接口，识别多种 CAN 消息并执行相应操作
# 特性：命令运行期间忽略重复触发，命令结束后需等待5秒才能再次触发
#
# CAN 消息定义：
# can2  052  [08]  50 00 00 00 00 00 00 01  -> 帧1 - 右臂(R)发送 Rws.log (can1)
# can2  052  [08]  50 00 00 00 00 00 00 02  -> 帧2 - 右臂(R)发送 Rhs1.log (can1)
# can2  052  [08]  60 00 00 00 00 00 00 01  -> 帧3 - 右臂(R)发送 Rhs2.log (can1)
# can2  052  [08]  60 00 00 00 00 00 00 02  -> 帧4 - 双臂发送 Lax1.log(can0) + Rax1.log(can1)

set -e

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SEND_DATA_TOOL="$SCRIPT_DIR/../xarm_action/send_data"
LOG_FILE_DIR="$SCRIPT_DIR/../xarm_action/1"

# 配置参数
CAN_INTERFACE="can2"
COOLDOWN_SECONDS=1

# 状态变量
is_running=0
last_end_time=0
child_pid=""

# 清理函数
cleanup() {
    echo ""
    echo "[INFO] 脚本退出，清理资源..."
    if [ $is_running -eq 1 ] && [ -n "$child_pid" ]; then
        echo "[INFO] 正在终止子进程..."
        kill -TERM "$child_pid" 2>/dev/null || true
        sleep 1
        kill -KILL "$child_pid" 2>/dev/null || true
    fi
    # 杀死所有后台的candump进程
    pkill -f "candump $CAN_INTERFACE" 2>/dev/null || true
    exit 0
}

# 注册信号处理
trap cleanup INT TERM

# 检查冷却时间
check_cooldown() {
    local current_time=$(date +%s)
    local time_since_last_end=$((current_time - last_end_time))
    
    if [ $is_running -eq 1 ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] [WARN] 命令正在运行中，忽略触发"
        return 1
    fi
    
    if [ $time_since_last_end -lt $COOLDOWN_SECONDS ] && [ $last_end_time -ne 0 ]; then
        local remaining=$((COOLDOWN_SECONDS - time_since_last_end))
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] [WARN] 冷却时间未到，忽略触发 (还需等待 ${remaining}s)"
        return 1
    fi
    
    return 0
}

# 执行触发命令
execute_command() {
    local action=$1
    local can_id=$2
    local log_file=$3
    local can_if=$4
    local log_file2=$5
    local can_if2=$6
    
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] 收到${action}信号 (CAN ID: 0x$can_id)，启动命令..."
    is_running=1
    
    # 在后台执行命令，并保存 PID
    if [ -n "$log_file2" ] && [ -n "$can_if2" ]; then
        "$SEND_DATA_TOOL" -f "$log_file" -c "$can_if" -f2 "$log_file2" -c2 "$can_if2" &
    else
        "$SEND_DATA_TOOL" -f "$log_file" -c "$can_if" &
    fi
    child_pid=$!
    
    # 等待命令完成
    wait $child_pid
    exit_code=$?
    
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] 命令执行完成，退出码: $exit_code"
    is_running=0
    last_end_time=$(date +%s)
    
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] 进入冷却期，${COOLDOWN_SECONDS}秒后可再次触发"
}

echo "========================================"
echo "  CAN 监听触发器脚本"
echo "========================================"
echo "监听接口: $CAN_INTERFACE"
echo "冷却时间: $COOLDOWN_SECONDS 秒"
echo "========================================"
echo "支持的 CAN 消息:"
echo "  0x052 [08] 50 00 00 00 00 00 00 01 - 帧1: 右臂(R)发送 Rws.log (can1)"
echo "  0x052 [08] 50 00 00 00 00 00 00 02 - 帧2: 右臂(R)发送 Rhs1.log (can1)"
echo "  0x052 [08] 60 00 00 00 00 00 00 01 - 帧3: 右臂(R)发送 Rhs2.log (can1)"
echo "  0x052 [08] 60 00 00 00 00 00 00 02 - 帧4: 双臂发送 Lax1.log(can0) + Rax1.log(can1)"
echo "========================================"
echo "按 Ctrl+C 退出"
echo ""

# 监听 CAN 总线
candump "$CAN_INTERFACE" 2>/dev/null | while read -r line; do
    # 解析 CAN 帧格式: can2  052  [08]  50 00 00 00 00 00 00 01
    
    # 提取 CAN ID（第二个字段）
    can_id=$(echo "$line" | awk '{print $2}')
    
    # 提取数据字节（第4-11个字段）
    data_bytes=$(echo "$line" | awk '{for(i=4;i<=11;i++) printf "%s ", $i}')
    
    # 清理 CAN ID（去掉前导0）
    can_id_clean=$(echo "$can_id" | sed 's/^0*//')
    
    # 判断 CAN ID 是否为 052
    if [ "${can_id_clean,,}" = "52" ]; then
        # 判断数据帧
        if echo "$data_bytes" | grep -q "50 00 00 00 00 00 00 01"; then
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] 检测到帧1 (CAN ID: 0x$can_id) - 右臂(R)发送 Rws.log"
            if check_cooldown; then
                execute_command "帧1" "$can_id" "$LOG_FILE_DIR/Rws.log" "can1"
            fi
        elif echo "$data_bytes" | grep -q "50 00 00 00 00 00 00 02"; then
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] 检测到帧2 (CAN ID: 0x$can_id) - 右臂(R)发送 Rhs1.log"
            if check_cooldown; then
                execute_command "帧2" "$can_id" "$LOG_FILE_DIR/Rhs1.log" "can1"
            fi
        elif echo "$data_bytes" | grep -q "60 00 00 00 00 00 00 01"; then
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] 检测到帧3 (CAN ID: 0x$can_id) - 右臂(R)发送 Rhs2.log"
            if check_cooldown; then
                execute_command "帧3" "$can_id" "$LOG_FILE_DIR/Rhs2.log" "can1"
            fi
        elif echo "$data_bytes" | grep -q "60 00 00 00 00 00 00 02"; then
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] 检测到帧4 (CAN ID: 0x$can_id) - 双臂同时发送 (左臂 Lax1.log, 右臂 Rax1.log)"
            if check_cooldown; then
                execute_command "帧4" "$can_id" "$LOG_FILE_DIR/Lax1.log" "can0" "$LOG_FILE_DIR/Rax1.log" "can1"
            fi
        fi
    fi
done
