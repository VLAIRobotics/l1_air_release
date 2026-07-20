#!/usr/bin/env bash

set -euo pipefail

DEFAULT_ARM_SIDE="right_arm"
DEFAULT_BAUDRATE="5000000"
DEFAULT_BAUDRATE_START_ID=1
DEFAULT_BAUDRATE_END_ID=8
DEFAULT_SETUP_CAN_IF="can0"
DEFAULT_ZERO_CAN_IF="can0"
DEFAULT_LEADER_CAN_IF="can1"
DEFAULT_FOLLOWER_CAN_IF="can0"

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PUBLISH_ROOT=$(cd "$SCRIPT_DIR/../../../.." && pwd)
CAN_LIBEXEC_DIR="$PUBLISH_ROOT/xarm_can/package/libexec"
SETUP_CAN_SCRIPT="$CAN_LIBEXEC_DIR/setup_can_interfaces.sh"
CHANGE_BAUDRATE_SCRIPT="$CAN_LIBEXEC_DIR/change_baudrate.py"
SET_ZERO_SCRIPT="$CAN_LIBEXEC_DIR/set_zero.sh"
LAUNCH_SCRIPT="$SCRIPT_DIR/launch_unilateral.sh"

usage() {
    cat <<EOF
用法: $(basename "$0")

说明:
  1. 脚本启动后会先自动执行 CAN 接口配置
  2. 然后按阶段菜单推进: 波特率 -> 零点 -> 摇操作
    3. 波特率阶段可选择写入全部电机，或指定单个电机
  4. 零点阶段固定执行 --all
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
    require_command python3
    require_command cansend
    require_file "$SETUP_CAN_SCRIPT" "CAN 接口配置脚本"
    require_file "$CHANGE_BAUDRATE_SCRIPT" "波特率设置脚本"
    require_file "$SET_ZERO_SCRIPT" "零点设置脚本"
    require_file "$LAUNCH_SCRIPT" "摇操作启动脚本"

    if ! python3 -c 'import can' >/dev/null 2>&1; then
        echo "[ERROR] Python 环境缺少 python-can，请先安装后再运行。"
        exit 1
    fi
}

run_setup_can() {
    echo "[INFO] 第 1 步: 配置 CAN 接口"
    bash "$SETUP_CAN_SCRIPT"
    echo "[INFO] CAN 接口配置完成"
}

run_baudrate_stage() {
    local can_if
    local baudrate_mode
    local canid

    can_if=$(ask_can_interface "请输入波特率阶段使用的 CAN 口" "$DEFAULT_SETUP_CAN_IF")

    while true; do
        echo
        echo "波特率写入方式:"
        echo "  1) 所有电机 (canid 1 到 8)"
        echo "  2) 指定单个电机"
        case "$(prompt_choice "请选择 [1-2]: ")" in
            1)
                baudrate_mode="all"
                break
                ;;
            2)
                baudrate_mode="single"
                break
                ;;
            *)
                echo "[WARN] 无效选择，请重新输入。"
                ;;
        esac
    done

    if [[ "$baudrate_mode" == "all" ]]; then
        echo "[INFO] 开始设置波特率: can=$can_if, baudrate=$DEFAULT_BAUDRATE, mode=all"
        for canid in $(seq "$DEFAULT_BAUDRATE_START_ID" "$DEFAULT_BAUDRATE_END_ID"); do
            echo "[INFO] 正在写入 canid=$canid"
            python3 "$CHANGE_BAUDRATE_SCRIPT" \
                --baudrate "$DEFAULT_BAUDRATE" \
                --canid "$canid" \
                --socketcan "$can_if" \
                --flash
        done
    else
        while true; do
            canid=$(prompt_value "请输入要设置波特率的电机号(1-8)" "8")
            if [[ "$canid" =~ ^[1-8]$ ]]; then
                break
            fi
            echo "[WARN] 电机号必须是 1 到 8 的整数，请重新输入。"
        done

        echo "[INFO] 开始设置波特率: can=$can_if, baudrate=$DEFAULT_BAUDRATE, canid=$canid"
        python3 "$CHANGE_BAUDRATE_SCRIPT" \
            --baudrate "$DEFAULT_BAUDRATE" \
            --canid "$canid" \
            --socketcan "$can_if" \
            --flash
    fi
    echo "[INFO] 波特率阶段完成"
}

run_zero_stage() {
    local can_if

    can_if=$(ask_can_interface "请输入设置零点阶段使用的 CAN 口" "$DEFAULT_ZERO_CAN_IF")

    echo "[INFO] 开始设置零点: can=$can_if"
    bash "$SET_ZERO_SCRIPT" "$can_if" --all
    echo "[INFO] 零点阶段完成"
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
        exec bash "$LAUNCH_SCRIPT" "left_arm" "$left_leader_can_if" "$left_follower_can_if"
    elif [[ "$arm_side" == "right_arm" ]]; then
        right_leader_can_if=$(ask_can_interface "请输入 right_arm Leader 侧 CAN 口" "$DEFAULT_LEADER_CAN_IF")
        right_follower_can_if=$(ask_can_interface "请输入 right_arm Follower 侧 CAN 口" "$DEFAULT_FOLLOWER_CAN_IF")
        echo "[INFO] 启动摇操作: right_arm, leader=$right_leader_can_if, follower=$right_follower_can_if"
        exec bash "$LAUNCH_SCRIPT" "right_arm" "$right_leader_can_if" "$right_follower_can_if"
    else
        echo "[INFO] 请分别为左右手臂配置 CAN 口"
        left_leader_can_if=$(ask_can_interface "请输入 left_arm Leader 侧 CAN 口" "$DEFAULT_LEADER_CAN_IF")
        left_follower_can_if=$(ask_can_interface "请输入 left_arm Follower 侧 CAN 口" "$DEFAULT_FOLLOWER_CAN_IF")
        right_leader_can_if=$(ask_can_interface "请输入 right_arm Leader 侧 CAN 口" "$DEFAULT_LEADER_CAN_IF")
        right_follower_can_if=$(ask_can_interface "请输入 right_arm Follower 侧 CAN 口" "$DEFAULT_FOLLOWER_CAN_IF")
        
        echo "[INFO] 同时启动摇操作:"
        echo "[INFO]   left_arm: leader=$left_leader_can_if, follower=$left_follower_can_if"
        echo "[INFO]   right_arm: leader=$right_leader_can_if, follower=$right_follower_can_if"
        bash "$LAUNCH_SCRIPT" "left_arm" "$left_leader_can_if" "$left_follower_can_if" &
        exec bash "$LAUNCH_SCRIPT" "right_arm" "$right_leader_can_if" "$right_follower_can_if"
    fi
}

post_stage_menu() {
    while true; do
        echo
        echo "当前阶段结束后，可选择:"
        echo "  1) 继续设置波特率"
        echo "  2) 进行设置零点"
        echo "  3) 执行摇操作"
        echo "  4) 退出"

        case "$(prompt_choice "请选择 [1-4]: ")" in
            1)
                run_baudrate_stage
                ;;
            2)
                run_zero_stage
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
        echo "  1) 设置波特率"
        echo "  2) 设置电机零点"
        echo "  3) 执行摇操作"
        echo "  4) 退出"

        case "$(prompt_choice "请选择 [1-4]: ")" in
            1)
                run_baudrate_stage
                post_stage_menu
                ;;
            2)
                run_zero_stage
                post_stage_menu
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
