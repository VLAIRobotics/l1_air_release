#!/usr/bin/env bash

set -euo pipefail

DEFAULT_ARM_SIDE="right_arm"
DEFAULT_LEADER_CAN_IF="can1"
DEFAULT_FOLLOWER_CAN_IF="can0"
DEFAULT_CAN0_IF="can0"
DEFAULT_CAN1_IF="can1"

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PUBLISH_ROOT=$(cd "$SCRIPT_DIR/../../../.." && pwd)
CAN_LIBEXEC_DIR="$PUBLISH_ROOT/xarm_can/package/libexec"
SETUP_CAN_SCRIPT="$CAN_LIBEXEC_DIR/setup_can_interfaces.sh"
LAUNCH_SCRIPT="$PUBLISH_ROOT/modules/src/xarm_teleop/script/launch_unilateral.sh"

CAN0_PID=""
CAN1_PID=""
CAN0_LOG=""
CAN1_LOG=""
CANDUMP_RUNNING=false

usage() {
    cat <<EOF
用法: $(basename "$0")

说明:
  1. 脚本启动后会先自动执行 CAN 接口配置
  2. 然后按阶段菜单推进: candump 监听 -> 转换日志 -> 摇操作
    3. candump 阶段可监听 can0 和 can1 数据帧并保存到脚本目录
    4. 转换日志阶段可将监听日志转换为可发送格式（can_id#data）
  5. 摇操作阶段可选择 left_arm、right_arm 或同时启动
EOF
}

require_command() {
    local command_name=$1

    if ! command -v "$command_name" >/dev/null 2>&1; then
        echo "[ERROR] 缺少命令: $command_name"
        exit 1
    fi
}

require_file() {
    local file_path=$1
    local description=$2

    if [[ ! -f "$file_path" ]]; then
        echo "[ERROR] 找不到${description}: $file_path"
        exit 1
    fi
}

prompt_value() {
    local prompt_text=$1
    local default_value=$2
    local value=""

    while true; do
        if ! read -r -p "${prompt_text} [${default_value}]: " value; then
            echo
            exit 130
        fi

        value="${value:-$default_value}"
        if [[ -n "$value" ]]; then
            printf '%s' "$value"
            return 0
        fi

        echo "[WARN] 输入不能为空，请重新输入。"
    done
}

prompt_choice() {
    local prompt_text=$1
    local choice=""

    if ! read -r -p "$prompt_text" choice; then
        echo
        exit 130
    fi

    printf '%s' "$choice"
}

validate_can_interface() {
    local can_if=$1

    if ! ip link show "$can_if" >/dev/null 2>&1; then
        echo "[ERROR] CAN 接口不存在: $can_if"
        return 1
    fi

    local state
    state=$(ip link show "$can_if" 2>/dev/null | sed -n 's/.*state \([A-Z]*\).*/\1/p' | head -n1)
    if [[ -z "$state" ]]; then
        state="UNKNOWN"
    fi

    if [[ "$state" != "UP" ]]; then
        echo "[ERROR] CAN 接口 $can_if 当前不是 UP 状态（state: $state）"
        return 1
    fi

    return 0
}

ask_can_interface() {
    local label=$1
    local default_value=$2
    local can_if=""

    while true; do
        can_if=$(prompt_value "$label" "$default_value")
        if validate_can_interface "$can_if"; then
            printf '%s' "$can_if"
            return 0
        fi

        echo "[WARN] 请重新输入 CAN 口。"
    done
}

check_prerequisites() {
    require_command sudo
    require_command ip
    require_command candump
    require_file "$SETUP_CAN_SCRIPT" "CAN 接口配置脚本"
    require_file "$LAUNCH_SCRIPT" "摇操作启动脚本"
}

run_setup_can() {
    echo "[INFO] 第 1 步: 配置 CAN 接口"
    bash "$SETUP_CAN_SCRIPT"
    echo "[INFO] CAN 接口配置完成"
}

run_candump_stage() {
    local can0_if
    local can1_if
    local timestamp
    local rounds_to_skip=9

    if [[ "$CANDUMP_RUNNING" == true ]]; then
        echo "[INFO] 监听已在运行中，日志文件: $CAN0_LOG 和 $CAN1_LOG"
        return
    fi

    can0_if=$(ask_can_interface "请输入要监听的第一个 CAN 口" "$DEFAULT_CAN0_IF")
    can1_if=$(ask_can_interface "请输入要监听的第二个 CAN 口" "$DEFAULT_CAN1_IF")

    timestamp=$(date +"%H%M%S")
    CAN0_LOG="$SCRIPT_DIR/candump_${can0_if}_${timestamp}.log"
    CAN1_LOG="$SCRIPT_DIR/candump_${can1_if}_${timestamp}.log"

    echo "[INFO] 开始监听 CAN 数据帧（1/10频率）..."
    echo "[INFO] $can0_if -> $CAN0_LOG"
    echo "[INFO] $can1_if -> $CAN1_LOG"
    echo "[INFO] 监听已在后台运行，写入1轮，跳过9轮"

    candump "$can0_if",000:FF0 | awk -v skip="$rounds_to_skip" '
        BEGIN {
            frame_count = 0
            frames_per_round = 8
            current_round = 1
        }
        {
            frame_count++
            if (frame_count % frames_per_round == 1) {
                current_round++
            }
            if (current_round % (skip + 1) == 1) {
                print $0
            }
        }' > "$CAN0_LOG" 2>&1 &
    CAN0_PID=$!
    
    candump "$can1_if",000:FF0 | awk -v skip="$rounds_to_skip" '
        BEGIN {
            frame_count = 0
            frames_per_round = 8
            current_round = 1
        }
        {
            frame_count++
            if (frame_count % frames_per_round == 1) {
                current_round++
            }
            if (current_round % (skip + 1) == 1) {
                print $0
            }
        }' > "$CAN1_LOG" 2>&1 &
    CAN1_PID=$!

    CANDUMP_RUNNING=true
}

stop_candump_stage() {
    if [[ "$CANDUMP_RUNNING" == false ]]; then
        echo "[WARN] 当前没有运行中的监听"
        return
    fi

    kill "$CAN0_PID" "$CAN1_PID" 2>/dev/null || true
    wait "$CAN0_PID" "$CAN1_PID" 2>/dev/null || true
    
    echo "[INFO] 监听已停止"
    echo "[INFO] 日志文件: $CAN0_LOG"
    echo "[INFO] 日志文件: $CAN1_LOG"
    
    CAN0_PID=""
    CAN1_PID=""
    CAN0_LOG=""
    CAN1_LOG=""
    CANDUMP_RUNNING=false
}

run_convert_log_format() {
    local input_file
    local output_file
    local line_count=0
    local converted_count=0

    echo
    echo "转换监听日志为可发送格式"

    input_file=$(prompt_value "请输入要转换的日志文件路径" "$SCRIPT_DIR/candump_can0_$(date +%Y%m%d)_*.log")
    
    if [[ ! -f "$input_file" ]]; then
        echo "[ERROR] 文件不存在: $input_file"
        return
    fi

    output_file="${input_file%.log}_converted.log"
    
    if [[ -f "$output_file" ]]; then
        echo "[WARN] 输出文件已存在: $output_file"
        if ! prompt_choice "是否覆盖? [y/N]: "; then
            echo "[INFO] 取消转换"
            return
        fi
    fi

    echo "[INFO] 开始转换..."
    echo "[INFO] 输入文件: $input_file"
    echo "[INFO] 输出文件: $output_file"
    echo "[INFO] 转换频率: 原频率（全部转换）"

    > "$output_file"

    # 写入开头8帧
    echo "001#FFFFFFFFFFFFFFFC" >> "$output_file"
    echo "002#FFFFFFFFFFFFFFFC" >> "$output_file"
    echo "003#FFFFFFFFFFFFFFFC" >> "$output_file"
    echo "004#FFFFFFFFFFFFFFFC" >> "$output_file"
    echo "005#FFFFFFFFFFFFFFFC" >> "$output_file"
    echo "006#FFFFFFFFFFFFFFFC" >> "$output_file"
    echo "007#FFFFFFFFFFFFFFFC" >> "$output_file"
    echo "008#FFFFFFFFFFFFFFFC" >> "$output_file"

    while IFS= read -r line; do
        if [[ -z "$line" ]] || [[ "$line" =~ ^[[:space:]]*$ ]]; then
            continue
        fi

        line_count=$((line_count + 1))

        if [[ "$line" =~ ^[[:space:]]*([a-zA-Z0-9]+)[[:space:]]+([0-9A-Fa-f]+)[[:space:]]+\[([0-9]+)\][[:space:]]+(.*)$ ]]; then
            local can_id="${BASH_REMATCH[2]}"
            local dlc="${BASH_REMATCH[3]}"
            local data="${BASH_REMATCH[4]}"

            data=$(echo "$data" | tr -d ' ')

            local can_frame="${can_id}#${data}"

            echo "$can_frame" >> "$output_file"
            converted_count=$((converted_count + 1))
        fi
    done < "$input_file"

    # 写入结尾8帧
    echo "001#FFFFFFFFFFFFFFFD" >> "$output_file"
    echo "002#FFFFFFFFFFFFFFFD" >> "$output_file"
    echo "003#FFFFFFFFFFFFFFFD" >> "$output_file"
    echo "004#FFFFFFFFFFFFFFFD" >> "$output_file"
    echo "005#FFFFFFFFFFFFFFFD" >> "$output_file"
    echo "006#FFFFFFFFFFFFFFFD" >> "$output_file"
    echo "007#FFFFFFFFFFFFFFFD" >> "$output_file"
    echo "008#FFFFFFFFFFFFFFFD" >> "$output_file"

    echo "[INFO] 转换完成"
    echo "[INFO] 总行数: $line_count"
    echo "[INFO] 转换成功: $converted_count"
    echo "[INFO] 输出文件: $output_file"
}

run_shake_stage() {
    local left_leader_can_if
    local left_follower_can_if
    local right_leader_can_if
    local right_follower_can_if
    local arm_side

    while true; do
        echo
        echo "摇操作手臂选择:"
        echo "  1) left_arm"
        echo "  2) right_arm"
        echo "  3) 同时启动左右手臂"
        case "$(prompt_choice "请选择 [1-3]: ")" in
            1)
                arm_side="left_arm"
                break
                ;;
            2)
                arm_side="right_arm"
                break
                ;;
            3)
                arm_side="both"
                break
                ;;
            *)
                echo "[WARN] 无效选择，请重新输入。"
                ;;
        esac
    done

    if [[ "$arm_side" == "left_arm" ]]; then
        left_leader_can_if=$(ask_can_interface "请输入 left_arm Leader 侧 CAN 口" "$DEFAULT_LEADER_CAN_IF")
        left_follower_can_if=$(ask_can_interface "请输入 left_arm Follower 侧 CAN 口" "$DEFAULT_FOLLOWER_CAN_IF")
        echo "[INFO] 启动摇操作: left_arm, leader=$left_leader_can_if, follower=$left_follower_can_if"
        exec bash "$LAUNCH_SCRIPT" "left_arm" "$left_leader_can_if" "$left_follower_can_if" --home "0,0,0,0,0,0,0"
    elif [[ "$arm_side" == "right_arm" ]]; then
        right_leader_can_if=$(ask_can_interface "请输入 right_arm Leader 侧 CAN 口" "$DEFAULT_LEADER_CAN_IF")
        right_follower_can_if=$(ask_can_interface "请输入 right_arm Follower 侧 CAN 口" "$DEFAULT_FOLLOWER_CAN_IF")
        echo "[INFO] 启动摇操作: right_arm, leader=$right_leader_can_if, follower=$right_follower_can_if"
        exec bash "$LAUNCH_SCRIPT" "right_arm" "$right_leader_can_if" "$right_follower_can_if" --home "0,0,0,0,0,0,0"
    else
        echo "[INFO] 请分别为左右手臂配置 CAN 口"
        left_leader_can_if=$(ask_can_interface "请输入 left_arm Leader 侧 CAN 口" "$DEFAULT_LEADER_CAN_IF")
        left_follower_can_if=$(ask_can_interface "请输入 left_arm Follower 侧 CAN 口" "$DEFAULT_FOLLOWER_CAN_IF")
        right_leader_can_if=$(ask_can_interface "请输入 right_arm Leader 侧 CAN 口" "$DEFAULT_LEADER_CAN_IF")
        right_follower_can_if=$(ask_can_interface "请输入 right_arm Follower 侧 CAN 口" "$DEFAULT_FOLLOWER_CAN_IF")
        
        echo "[INFO] 同时启动摇操作:"
        echo "[INFO]   left_arm: leader=$left_leader_can_if, follower=$left_follower_can_if"
        echo "[INFO]   right_arm: leader=$right_leader_can_if, follower=$right_follower_can_if"
        bash "$LAUNCH_SCRIPT" "left_arm" "$left_leader_can_if" "$left_follower_can_if" --home "0,0,0,0,0,0,0" &
        exec bash "$LAUNCH_SCRIPT" "right_arm" "$right_leader_can_if" "$right_follower_can_if" --home "0,0,0,0,0,0,0"
    fi
}

post_stage_menu() {
    while true; do
        echo
        echo "当前阶段结束后，可选择:"
        if [[ "$CANDUMP_RUNNING" == true ]]; then
            echo "  [监听运行中] 日志: $CAN0_LOG, $CAN1_LOG"
            echo "  1) 停止 CAN 数据帧监听"
        else
            echo "  1) 启动 CAN 数据帧监听"
        fi
        echo "  2) 转换日志为可发送格式"
        echo "  3) 执行摇操作"
        echo "  4) 退出"

        case "$(prompt_choice "请选择 [1-4]: ")" in
            1)
                if [[ "$CANDUMP_RUNNING" == true ]]; then
                    stop_candump_stage
                else
                    run_candump_stage
                fi
                ;;
            2)
                run_convert_log_format
                ;;
            3)
                run_shake_stage
                ;;
            4|q|Q)
                exit 0
                ;;
            *)
                echo "[WARN] 无效选择，请重新输入。"
                ;;
        esac
    done
}

post_setup_menu() {
    while true; do
        echo
        echo "CAN 接口配置完成，可选择:"
        if [[ "$CANDUMP_RUNNING" == true ]]; then
            echo "  [监听运行中] 日志: $CAN0_LOG, $CAN1_LOG"
            echo "  1) 停止 CAN 数据帧监听"
        else
            echo "  1) 启动 CAN 数据帧监听"
        fi
        echo "  2) 转换日志为可发送格式"
        echo "  3) 执行摇操作"
        echo "  4) 退出"

        case "$(prompt_choice "请选择 [1-4]: ")" in
            1)
                if [[ "$CANDUMP_RUNNING" == true ]]; then
                    stop_candump_stage
                else
                    run_candump_stage
                fi
                ;;
            2)
                run_convert_log_format
                ;;
            3)
                run_shake_stage
                ;;
            4|q|Q)
                exit 0
                ;;
            *)
                echo "[WARN] 无效选择，请重新输入。"
                ;;
        esac
    done
}

main() {
    if [[ $# -gt 0 ]]; then
        echo "[ERROR] 该脚本不接收位置参数。"
        usage
        exit 1
    fi

    check_prerequisites

    if [[ -t 0 ]]; then
        sudo -v
    fi

    run_setup_can
    post_setup_menu
}

if [[ ${1:-} == "-h" || ${1:-} == "--help" ]]; then
    usage
    exit 0
fi

trap 'echo; echo "[INFO] 用户取消操作"; exit 130' INT

main "$@"
