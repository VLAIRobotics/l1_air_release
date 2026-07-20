# xarm_chassis 底盘控制模块使用指南

---

## 目录

1. [模块概述](#1-模块概述)
2. [版本历史](#2-版本历史)
3. [模块目录结构](#3-模块目录结构)
4. [运行前准备](#4-运行前准备)
5. [运行](#5-运行)
6. [CAN 数据格式](#6-can-数据格式)
7. [固件说明](#7-固件说明)
8. [常见问题排查](#8-常见问题排查)

---

## 1. 模块概述

`xarm_chassis` 是 xArm 机器人底盘的控制模块，负责底盘运动和立柱升降的控制。模块支持多种控制方式：

- **遥控模式**：通过遥控器拨杆和摇杆控制底盘运动
- **上位机模式**：通过 ROS2 话题或命令行控制底盘运动和立柱升降
- **动作触发模式**：通过遥控器触发预定义的机器人动作

### 当前稳定版本

**V1.2.0**（推荐使用）

---

## 2. 版本历史

| 版本 | 发布日期 | 主要变更 | 固件更新 |
|------|---------|---------|---------|
| **V1.2.0** | 2026-07-17 | 新增 `can_listener_trigger.sh` 动作触发器脚本；新增 `/stm32/actual_distance` 话题；角度翻转处理 | **是** |
| **V1.1.1** | - | CAN ID 0x051 返回数据从速度改为累积位移；新增位移换算比例 | 否 |
| **V1.1.0** | - | 初始版本；支持双模式控制（ROS2 + CLI）；CAN ID 0x051 返回速度数据 | - |

### 版本兼容性

| 固件版本 | 支持的控制方式 | 推荐使用的脚本 |
|---------|---------------|---------------|
| V1.2.0 固件 | 遥控模式 + 上位机模式 + 动作触发模式 | `chassis_listener.py` + `chassis_control.py` + `can_listener_trigger.sh` |
| V1.1.1 固件 | 遥控模式 + 上位机模式 | `chassis_listener.py` + `chassis_control.py` |
| V1.1.0 固件 | 遥控模式 + 上位机模式 | `chassis_listener.py` + `chassis_control.py` |

---

## 3. 模块目录结构

```text
chassis_system/
├── chassis_listener.py          # ROS2 节点：操纵杆/CAN 桥接器
├── chassis_control.py           # 双模式控制器：ROS2 + CLI
├── can_listener_trigger.sh      # CAN 监听触发器脚本（V1.2.0 新增）
└── README.md                    # 项目说明文档
```

**脚本说明：**

| 脚本 | 功能 | 说明 |
|------|------|------|
| `chassis_listener.py` | 监听模式 | 订阅遥控器话题，发送 CAN 控制帧，接收反馈并发布到 ROS2 话题 |
| `chassis_control.py` | 控制模式 | 支持 CLI 和 ROS2 话题双模式控制底盘和立柱 |
| `can_listener_trigger.sh` | 动作触发 | 监听 CAN 总线信号，通过遥控器触发预定义动作 |

---

## 4. 运行前准备

### 4.1 基础环境

| 要求 | 说明 |
|------|------|
| 操作系统 | Ubuntu 22.04 |
| ROS2 版本 | Humble |
| CAN 接口 | 已完成物理接线和 SocketCAN 配置 |

### 4.2 CAN 接口准备

```bash
sudo ip link set can2 up type can bitrate 500000

ip link show can2
```

预期输出：
```text
can2: <NOARP,UP,LOWER_UP> mtu 72 qdisc pfifo_fast state UP mode DEFAULT
```

### 4.3 依赖安装

```bash
pip install python-can

sudo apt install ros-humble-rclpy ros-humble-std-msgs
sudo apt install can-utils
```

---

## 5. 运行

### 5.1 遥控模式（遥控器第四拨杆拨到中间）

使用 `chassis_listener.py` 监听底盘反馈数据：

```bash
cd /path/to/chassis_system
python3 chassis_listener.py
```

**功能说明：**
1. 订阅 `/dual_xarm/joystick` 话题接收遥控器摇杆数据
2. 订阅 `/dual_xarm/py_motor_target` 话题接收立柱控制指令
3. 将摇杆模拟量映射为速度值并发送 CAN 帧（ID: 0x050）
4. 接收底盘反馈数据（ID: 0x051）并发布到 ROS2 话题

### 5.2 上位机模式（遥控器第四拨杆拨到下面）

使用 `chassis_control.py` 控制底盘：

```bash
cd /path/to/chassis_system
python3 chassis_control.py
```

**功能说明：**
- 优先检测 ROS2 环境，可用则启动 ROS2 节点；不可用则回退到纯 CLI 模式
- 支持 CLI 命令行控制（按键 1-8）和 ROS2 话题控制

**CLI 命令表：**

| 按键 | 命令 | 功能 |
|------|------|------|
| 1 | stop | 底盘静止 |
| 2 | left | 左转 |
| 3 | right | 右转 |
| 4 | forward | 前进 |
| 5 | backward | 后退 |
| 6 | lift_up | 立柱上升 |
| 7 | lift_down | 立柱下降 |
| 8 | lift_stop | 立柱静止 |
| s | speed | 切换速度档位 |
| q | quit | 退出程序 |

**速度档位：**

| 档位 | 速度值 |
|------|--------|
| 1 | 200 |
| 2 | 400 |
| 3 | 600 |
| 4 | 800 |

**ROS2 话题控制：**

底盘运动控制：
```bash
ros2 topic pub /chassis/cmd std_msgs/String "data: 'stop'"
ros2 topic pub /chassis/cmd std_msgs/String "data: 'forward'"
ros2 topic pub /chassis/cmd std_msgs/String "data: 'backward'"
ros2 topic pub /chassis/cmd std_msgs/String "data: 'left'"
ros2 topic pub /chassis/cmd std_msgs/String "data: 'right'"
```

立柱控制：
```bash
ros2 topic pub /chassis/cmd std_msgs/String "data: 'lift_up'"
ros2 topic pub /chassis/cmd std_msgs/String "data: 'lift_down'"
ros2 topic pub /chassis/cmd std_msgs/String "data: 'lift_stop'"
```

速度设置：
```bash
ros2 topic pub /chassis/cmd std_msgs/String "data: 'speed_1'"
ros2 topic pub /chassis/cmd std_msgs/String "data: 'speed_2'"
ros2 topic pub /chassis/cmd std_msgs/String "data: 'speed_3'"
ros2 topic pub /chassis/cmd std_msgs/String "data: 'speed_4'"
```

### 5.3 动作触发模式（V1.2.0 新增）

使用 `can_listener_trigger.sh` 通过遥控器触发预定义动作：

```bash
cd /path/to/chassis_system
chmod +x can_listener_trigger.sh
./can_listener_trigger.sh
```

**功能说明：**
- 监听 CAN ID 0x051 的帧，解析摇杆状态触发动作
- 支持重置机制、1秒冷却时间和动作互斥

**摇杆控制：**
- 第一摇杆（套数）：0=上, 1=中, 2=下
- 第二摇杆（动作）：0=上, 1=下
- 第三摇杆（触发）：0=上(触发), 1=下(重置)

**动作映射：**

| 摇杆组合 | 触发动作 | CAN 接口 |
|---------|---------|---------|
| 套数0-动作0 | Rws.log | can1 |
| 套数0-动作1 | Rhs1.log | can1 |
| 套数1-动作0 | Rhs2.log | can1 |
| 套数1-动作1 | Lax1.log + Rax1.log | can0 + can1 |

**触发规则：**
- 必须先收到"重置"信号（第三摇杆向下）才能触发动作
- 动作执行完成后需再次重置才能触发下一个动作

### 5.4 遥控器操作说明

遥控器配备多个拨杆和摇杆，用于控制底盘和立柱的不同操作模式：

**拨杆功能：**

| 拨杆位置 | 名称 | 档位 | 功能说明 |
|----------|------|------|----------|
| 最左边 | 第一拨杆 | 上 | 立柱上升 |
| 最左边 | 第一拨杆 | 中 | 立柱静止 |
| 最左边 | 第一拨杆 | 下 | 立柱下降 |
| 最右边 | 第四拨杆 | 上 | 保留 |
| 最右边 | 第四拨杆 | **中** | **遥控模式**：遥控器摇杆控制底盘 |
| 最右边 | 第四拨杆 | **下** | **上位机模式**：上位机控制底盘 |

**摇杆功能（遥控模式下）：**

- **左右摇杆**：控制底盘横向移动（左右）
- **前后摇杆**：控制底盘纵向移动（前后）

### 5.5 发布的 ROS2 话题

| 话题名称 | 消息类型 | 说明 |
|---------|---------|------|
| `/stm32/chassis_data` | Float64MultiArray | STM32 当前返回的绝对位移值 |
| `/stm32/actual_distance` | Float64MultiArray | 相对于启动位置的实际位移值（V1.1.1+） |

**话题数据格式：**

`/stm32/chassis_data`：
- data[0]：横向位移（米，向右为正）
- data[1]：纵向位移（米，前进为正）
- data[2]：旋转角度（度，顺时针为正）

`/stm32/actual_distance`：
- data[0]：横向位移（米，向右为正，相对于启动位置）
- data[1]：纵向位移（米，前进为正，相对于启动位置）
- data[2]：旋转角度（度，顺时针为正，累积角度）

---

## 6. CAN 数据格式

### 6.1 发送帧（CAN ID: 0x050）

| 字节位置 | 字段 | 类型 | 说明 |
|----------|------|------|------|
| 0-1 | vx | int16 LE | 横向速度（左右） |
| 2-3 | vy | int16 LE | 纵向速度（前后） |
| 4-5 | vw | int16 LE | 角速度（旋转） |
| 6 | reserved | uint8 | 保留位 |
| 7 | updown | uint8 | 立柱状态（0=静止，1=下降，2=上升） |

### 6.2 接收帧（CAN ID: 0x051）

**V1.1.0 版本：**

| 字节位置 | 字段 | 类型 | 说明 |
|----------|------|------|------|
| 0-1 | vx | int16 LE | 实际横向速度 |
| 2-3 | vy | int16 LE | 实际纵向速度 |
| 4-5 | vw | int16 LE | 实际角速度 |

**V1.1.1+ 版本：**

| 字节位置 | 字段 | 类型 | 说明 |
|----------|------|------|------|
| 0-1 | x | int16 BE | 横向累积位移（原始值，单位=实际值×1000） |
| 2-3 | y | int16 BE | 纵向累积位移（原始值，单位=实际值×1000） |
| 4-5 | z | int16 BE | 旋转角度（原始值，单位=实际值×1000，弧度） |

### 6.3 位移换算比例（V1.1.1+）

| 轴 | 换算比例 | 说明 |
|----|----------|------|
| x | 1.0/1000.0 × 0.5 | 米/单位（向右为正，含0.5倍修正） |
| y | 1.0/1000.0 × 0.5 | 米/单位（前进为正，含0.5倍修正） |
| z | 1.0/1000.0 × 180/π | 度/单位（顺时针为正） |

**位移范围：**
- X/Y 轴最大可位移：37.767m（基于 int16 有符号数范围计算）

---

## 7. 固件说明

### 7.1 固件文件位置

```text
mini_car.zip
└── mini_car/
    └── User/
        └── app/
            ├── chassis_task.c    # 底盘任务
            └── controler_task.c  # 控制器任务
```

### 7.2 V1.2.0 固件修复

**修复 1：里程计发送条件**

文件：`chassis_task.c`（第 263 行）

| 版本 | 代码 |
|------|------|
| V1.1.1 | `if (/*last_all_online && (*/now_ms - last_odom_ms >= ODOM_INTERVAL_MS)` |
| V1.2.0 | `if (last_all_online && (now_ms - last_odom_ms >= ODOM_INTERVAL_MS))` |

说明：恢复 `last_all_online` 条件判断，确保遥控器在线时才发送里程计数据。

**修复 2：遥控器离线模式**

文件：`controler_task.c`（第 37-40 行）

| 版本 | 代码 |
|------|------|
| V1.1.1 | `if(remoter.rc.ch[7] == 0)` → `ctrl_mode = PROTECT_MODE;` |
| V1.2.0 | `if(remoter.online == 0)` → `ctrl_mode = AUTO_MODE;` |

说明：使用 `remoter.online` 标志位判断离线状态，离线时切换为 `AUTO_MODE` 允许上位机控制。

### 7.3 固件烧录

将 `mini_car.zip` 中的代码烧录到 STM32 单片机即可。

---

## 8. 常见问题排查

### 8.1 CAN 接口未找到

| 检查项 | 命令 |
|--------|------|
| CAN 接口是否存在 | `ip link show | grep can` |
| CAN 接口是否 UP | `sudo ip link set can2 up type can bitrate 500000` |
| 权限是否足够 | `sudo` 运行，或将用户加入 `netdev` 组 |

### 8.2 脚本运行后底盘无响应

| 检查项 | 说明 |
|--------|------|
| 遥控器模式是否正确 | 第四拨杆是否拨到对应模式（中间=遥控，下面=上位机） |
| CAN 通道是否正确 | 确认使用 `can2` 通道 |
| CAN 总线物理连接 | 检查 CAN 收发器接线是否正确 |
| 电机是否已使能 | 确认底盘控制器已上电且电机处于使能状态 |

### 8.3 监听模式下位移数据全为 0

| 检查项 | 说明 |
|--------|------|
| CAN ID 0x051 是否有数据回报 | `candump can2` 实时抓包 |
| STM32 单片机是否正常运行 | 检查单片机指示灯状态 |

### 8.4 动作触发无响应

| 检查项 | 说明 |
|--------|------|
| 是否先发送了重置信号 | 第三摇杆需先拨到下方触发重置 |
| 是否处于冷却期 | 动作执行后需等待 1 秒冷却时间 |
| `send_data` 工具是否可用 | 确认动作发送工具已正确安装 |

### 8.5 ROS2 话题发布后无响应

| 检查项 | 命令 |
|--------|------|
| ROS2 节点是否运行 | `ros2 node list` |
| 话题是否正确发布 | `ros2 topic echo /chassis/cmd` |
| 命令格式是否正确 | 确认命令为小写字符串，如 `'forward'` |

### 8.6 程序退出后电机仍在运动

原因：退出时未发送停止命令，或停止命令未成功传输。

解决：
- 使用 `chassis_control.py` 时，按 `q` 或 `Ctrl+C` 正常退出
- 节点会自动发送停止帧

### 8.7 遥控器对应模式没有生效

原因：可能没进入到对应模式

解决：上下拨动第四摇杆重置一下，再拨到需要的模式

---

## 配置说明

### 主要参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| max_speed | 800 | 最大速度限制 |
| can_id | 0x050 | 发送 CAN ID |
| send_hz | 200 | CAN 发送频率 |
| channel | can2 | CAN 接口名称 |
| ODOM_LINEAR_SCALE | 1.0/1000.0 | 线位移换算比例（米/单位） |
| ODOM_ANGULAR_SCALE | 1.0/1000.0 | 角位移换算比例（弧度/单位） |
| ODOM_LINEAR_CORRECTION | 0.5 | 线位移修正系数 |

### 修改参数

在 `chassis_listener.py` 或 `chassis_control.py` 中修改对应常量即可。

---

## 调试命令

```bash
candump can2

cansend can2 050#0000000000000000

ros2 topic list
ros2 topic echo /stm32/chassis_data
ros2 topic echo /stm32/actual_distance
```

---

## 注意事项

1. 运行前确保 CAN 接口已正确配置
2. 使用 ROS2 模式时需要先 source ROS2 环境
3. 退出程序时会自动发送停止指令，确保安全
4. 速度值范围为 -max_speed 到 max_speed
5. 立柱状态仅支持上升(2)、下降(1)、静止(0)三种状态
6. V1.1.1+ 版本中 CAN ID 0x051 返回的是累积位移原始值（int16 大端），数值 = 实际值 × 1000

---

## License

MIT License
