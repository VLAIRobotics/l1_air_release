#!/bin/bash
#
# CAN 监听触发器脚本 (需重置版本)
# 功能：监听 can2 接口，每次读取最新一帧
# 规则：脚本启动后必须先收到"不触发"信号重置，才能触发动作
#       触发动作后必须再次收到"不触发"信号重置，才能触发下一个动作
#
# 数据格式: FA 27 F9 93 F3 F2 0[套数] [动作] [触发]
#   套数: 第一摇杆 0=上, 1=中, 2=下
#   动作: 第二摇杆 0=上, 1=下
#   触发: 第三摇杆 0=触发, 1=不触发
#

set -e

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SEND_DATA_TOOL="$SCRIPT_DIR/../../xarm_action/send_data"
LOG_FILE_DIR="$SCRIPT_DIR/../../xarm_action/1"    

# 配置参数
CAN_INTERFACE="can2"
COOLDOWN_SECONDS=1

# 状态变量
is_running=0
last_end_time=0
child_pid=""
last_frame_data=""
last_action_type=""
need_reset=1  # 默认需要重置，脚本启动后必须先收到不触发信号
current_action_name=""  # 当前准备触发的动作名称

# 清理函数
cleanup() {
    echo ""
    echo "[INFO] 脚本退出，清理资源..."
    if [ $is_running -eq 1 ] && [ -n "$child_pid" ]; then
        kill -TERM "$child_pid" 2>/dev/null || true
        sleep 1
        kill -KILL "$child_pid" 2>/dev/null || true
    fi
    pkill -f "candump $CAN_INTERFACE" 2>/dev/null || true
    exit 0
}

trap cleanup INT TERM

# 检查冷却时间
check_cooldown() {
    local current_time=$(date +%s)
    local time_since_last_end=$((current_time - last_end_time))
    
    if [ $is_running -eq 1 ]; then
        return 1
    fi
    
    if [ $time_since_last_end -lt $COOLDOWN_SECONDS ] && [ $last_end_time -ne 0 ]; then
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
    
    echo "[INFO] 执行: ${action}"
    is_running=1
    
    if [ -n "$log_file2" ] && [ -n "$can_if2" ]; then
        "$SEND_DATA_TOOL" -f "$log_file" -c "$can_if" -f2 "$log_file2" -c2 "$can_if2" &
    else
        "$SEND_DATA_TOOL" -f "$log_file" -c "$can_if" &
    fi
    child_pid=$!
    
    wait $child_pid
    exit_code=$?
    
    echo "[INFO] 完成 (退出码: $exit_code)"
    is_running=0
    last_end_time=$(date +%s)
    
    # 动作执行完成后，需要等待重置信号
    need_reset=1
    current_action_name=""  # 清空当前动作名称
    echo "[INFO] 等待重置信号 (第三摇杆向下)..." 
}

# 获取动作名称
get_action_name() {
    local suite=$1
    local action=$2
    
    if [ "$suite" -eq 0 ]; then
        if [ "$action" -eq 0 ]; then
            echo "套数0-动作0: Rws.log"
        elif [ "$action" -eq 1 ]; then
            echo "套数0-动作1: Rhs1.log"
        else
            echo "未知动作"
        fi
    elif [ "$suite" -eq 1 ]; then
        if [ "$action" -eq 0 ]; then
            echo "套数1-动作0: Rhs2.log"
        elif [ "$action" -eq 1 ]; then
            echo "套数1-动作1: Lax1.log+Rax1.log"
        else
            echo "未知动作"
        fi
    elif [ "$suite" -eq 2 ]; then
        echo "套数2: 预留 (暂无动作)"
    else
        echo "未知套数"
    fi
}

echo "========================================"
echo "  CAN 监听触发器 (需重置)"
echo "========================================"
echo "监听: $CAN_INTERFACE | 冷却: ${COOLDOWN_SECONDS}s"
echo ""
echo "摇杆控制说明:"
echo "  第一摇杆 (套数): 0=上, 1=中, 2=下"
echo "  第二摇杆 (动作): 0=上, 1=下"
echo "  第三摇杆 (触发): 0=上(触发), 1=下(重置)"
echo ""
echo "动作映射:"
echo "  套数0 (上): 动作0→Rws.log | 动作1→Rhs1.log"
echo "  套数1 (中): 动作0→Rhs2.log | 动作1→Lax1.log+Rax1.log"
echo "  套数2 (下): 预留"
echo ""
echo "规则: 必须先收到'重置'(第三摇杆向下)才能触发动作"
echo "========================================"
echo "按 Ctrl+C 退出"
echo ""

# 主循环 - 每次只读最新一帧
while true; do
    # 读取最新的一帧数据
    line=$(candump -n 1 "$CAN_INTERFACE" 2>/dev/null | head -1)
    
    if [ -z "$line" ]; then
        continue
    fi
    
    # 提取完整的数据部分作为帧标识
    full_data=$(echo "$line" | awk '{for(i=3;i<=NF;i++) printf "%s ", $i}' | sed 's/ $//')
    
    # 检查帧是否变化
    if [ -n "$last_frame_data" ] && [ "$full_data" == "$last_frame_data" ]; then
        continue
    fi
    last_frame_data="$full_data"
    
    # 提取 CAN ID
    can_id=$(echo "$line" | awk '{print $2}')
    can_id_clean=$(echo "$can_id" | sed 's/^0*//')
    
    # 只处理 ID 为 051 的帧
    if [ "${can_id_clean,,}" != "51" ]; then
        continue
    fi
    
    # 提取数据字节
    data_bytes=$(echo "$line" | awk '{for(i=4;i<=11;i++) printf "%s ", $i}')
    byte7=$(echo "$data_bytes" | awk '{print $7}')
    byte8=$(echo "$data_bytes" | awk '{print $8}')
    
    if [ -z "$byte7" ] || [ -z "$byte8" ]; then
        continue
    fi
    
    # 去掉前导零
    byte7_num=$(echo "$byte7" | sed 's/^0*//')
    byte8_num=$(echo "$byte8" | sed 's/^0*//')
    
    # 如果为空则设为0
    if [ -z "$byte7_num" ]; then byte7_num=0; fi
    if [ -z "$byte8_num" ]; then byte8_num=0; fi
    
    # 解析: 动作 = 十位, 触发 = 个位
    action=$((byte8_num / 10))
    trigger=$((byte8_num % 10))
    
    # 获取当前准备触发的动作名称
    action_name=$(get_action_name "$byte7_num" "$action")
    
    # 如果动作名称变了，打印准备触发的动作
    if [ "$action_name" != "$current_action_name" ]; then
        current_action_name="$action_name"
        if [ "$trigger" -eq 0 ]; then
            echo "[INFO] 准备触发: $action_name (第三摇杆向下)"
        else
            echo "[INFO] 准备触发: $action_name (第三摇杆向下=重置)"
        fi
    fi
    
    # 检查第三摇杆 (触发标志)
    if [ "$trigger" -eq 0 ]; then
        # 第三摇杆向下 = 触发信号
        
        # 检查是否需要重置
        if [ $need_reset -eq 1 ]; then
            echo "[WARN] 需要先重置! 请将第三摇杆向下"
            continue
        fi
        
        # 检查冷却时间
        if ! check_cooldown; then
            echo "[WARN] 冷却中，忽略触发"
            continue
        fi
        
        # 根据第一摇杆(套数)和第二摇杆(动作)确定动作
        if [ "$byte7_num" -eq 0 ]; then  # 第一摇杆: 上
            if [ "$action" -eq 0 ]; then  # 第二摇杆: 上
                current_action="action1"
                if [ "$current_action" != "$last_action_type" ]; then
                    last_action_type="$current_action"
                    execute_command "套数0-动作0: Rws.log" "$can_id" "$LOG_FILE_DIR/Rws.log" "can1"
                fi
            elif [ "$action" -eq 1 ]; then  # 第二摇杆: 下
                current_action="action2"
                if [ "$current_action" != "$last_action_type" ]; then
                    last_action_type="$current_action"
                    execute_command "套数0-动作1: Rhs1.log" "$can_id" "$LOG_FILE_DIR/Rhs1.log" "can1"
                fi
            else
                echo "[WARN] 未知动作: $action"
            fi
        elif [ "$byte7_num" -eq 1 ]; then  # 第一摇杆: 中
            if [ "$action" -eq 0 ]; then  # 第二摇杆: 上
                current_action="action3"
                if [ "$current_action" != "$last_action_type" ]; then
                    last_action_type="$current_action"
                    execute_command "套数1-动作0: Rhs2.log" "$can_id" "$LOG_FILE_DIR/Rhs2.log" "can1"
                fi
            elif [ "$action" -eq 1 ]; then  # 第二摇杆: 下
                current_action="action4"
                if [ "$current_action" != "$last_action_type" ]; then
                    last_action_type="$current_action"
                    execute_command "套数1-动作1: Lax1.log+Rax1.log" "$can_id" "$LOG_FILE_DIR/Lax1.log" "can0" "$LOG_FILE_DIR/Rax1.log" "can1"
                fi
            else
                echo "[WARN] 未知动作: $action"
            fi
        elif [ "$byte7_num" -eq 2 ]; then  # 第一摇杆: 下 (预留)
            echo "[INFO] 套数2 (第一摇杆向下) - 预留，暂无动作"
        else
            echo "[WARN] 未知套数: $byte7_num"
        fi
        
    else
        # 第三摇杆向上 = 重置信号
        if [ $need_reset -eq 1 ]; then
            echo "[INFO] 收到重置信号 (第三摇杆向下)，可以触发动作"
            need_reset=0
            last_action_type=""  # 清空动作类型，允许触发相同动作
        else
            # 如果已经重置状态，提示当前准备触发的动作
            if [ -n "$current_action_name" ]; then
                echo "[INFO] 当前准备触发: $current_action_name (第三摇杆向上即可触发)"
            fi
        fi
    fi
done