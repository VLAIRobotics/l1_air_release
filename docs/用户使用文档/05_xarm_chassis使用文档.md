# xarm_chassis 底盘控制模块使用指南

---

## 目录

1. [模块目录结构](#1-模块目录结构)
2. [版本说明](#2-版本说明)
3. [运行前准备](#3-运行前准备)
4. [运行](#4-运行)
5. [CAN 数据格式](#5-can-数据格式)
6. [常见问题排查](#6-常见问题排查)

---

## 1. 模块目录结构

`publish` 目录中，xarm_chassis 结构如下：

```text
publish/modules/src/xarm_chassis/
├── chassis_control.py           ← 控制模式：CLI + ROS2 话题双模式控制
├── chassis_listener.py          ← 监听模式：CAN 反馈数据监听与发布
├── can_listener_trigger.sh      ← CAN 监听触发器：识别 CAN 消息并触发动作
├── fix_services.sh              ← 服务配置脚本：配置开机自启服务
└── readme.md                    ← 模块说明文档
```

**说明**：
- `chassis_control.py`：适用于新版本固件，同时支持交互式命令行和 ROS2 话题控制底盘和立柱
- `chassis_listener.py`：监听 CAN 总线上的底盘反馈数据（速度、通道状态）并发布到 ROS2 话题
- `can_listener_trigger.sh`：监听 CAN 总线特定消息，自动触发动作播放（如播放手臂动作日志）
- `fix_services.sh`：一键配置 systemd 服务，实现 CAN 接口初始化和监听触发器开机自启

---

## 2. 版本说明

### 2.1 版本兼容性

| 产品发货日期 | 固件版本 | 支持的控制方式 |
|-------------|---------|---------------|
| 2026.7.6 之前 | 旧版本 | 仅监听模式 |
| 2026.7.6 之后 / 烧录更新后 | 新版本 | 控制模式 + 监听模式 |

> **注意**：两种模式的 CAN 通信协议不同，需根据固件版本选择对应的控制脚本。

### 2.2 固件更新说明

如需从监听模式升级为直接控制模式，需烧录更新后的 STM32 单片机代码。升级后将支持：
- 独立控制底盘运动（静止、左转、右转、前进、后退）
- 独立控制立柱升降（上升、下降、静止）
- 通过 ROS2 话题实现远程控制

---

## 3. 运行前准备

### 3.1 基础环境

| 要求 | 说明 |
|------|------|
| 操作系统 | Ubuntu 22.04 |
| ROS2 版本 | Humble |
| CAN 接口 | 已完成物理接线和 SocketCAN 配置 |

### 3.2 CAN 接口准备

启动前，先确认 CAN 接口可用：

```bash
# 使用 xarm_can SDK 中的配置脚本一键初始化
cd /path/to/publish/xarm_can/package/libexec
bash setup_can_interfaces.sh

# 验证接口状态
ip link show | grep can
```

预期输出示例：

```text
can0: <NOARP,UP,LOWER_UP> mtu 72 qdisc pfifo_fast state UP mode DEFAULT
can1: <NOARP,UP,LOWER_UP> mtu 72 qdisc pfifo_fast state UP mode DEFAULT
can2: <NOARP,UP,LOWER_UP> mtu 72 qdisc pfifo_fast state UP mode DEFAULT
```

> **注意**：底盘控制使用 `can2` 通道，确保该接口已正确配置并处于 UP 状态。

### 3.3 依赖安装

```bash
# 安装 Python CAN 库
pip install python-can

# 安装 ROS2 相关依赖（如未安装）
sudo apt install ros-humble-rclpy ros-humble-std-msgs
```

---

## 4. 运行

### 4.1 控制模式（新版本固件）

`chassis_control.py` 同时支持两种控制方式：
- **CLI 命令行控制**：输入 1-8 数字直接控制
- **ROS2 话题控制**：通过 `/chassis/cmd` 话题接收命令

两种方式共享同一个状态，可同时使用。

**独立控制模型：**

底盘运动和立柱控制为**两个独立状态变量**，可同时控制：

```
CHASSIS_STATE (底盘): stop / left / right / forward / backward
LIFT_STATE (立柱):   lift_stop / lift_up / lift_down
```

**运动状态与 CAN 帧映射：**

**底盘控制帧：**

| 状态 | 左轮 CAN 帧 | 右轮 CAN 帧 |
|------|------------|------------|
| 静止 | `601#2B18230000000000` | `603#2B18330000000000` |
| 左转 | `601#2B182300E9FFFFFF` | `603#2B183300E9FFFFFF` |
| 右转 | `601#2B18230018000000` | `603#2B18330018000000` |
| 前进 | `601#2B18230017000000` | `603#2B183300E8FFFFFF` |
| 后退 | `601#2B182300E8FFFFFF` | `603#2B18330018000000` |

**立柱控制帧：**

| 状态 | 立柱 CAN 帧 |
|------|------------|
| 立柱静止 | `600#0000000000000000` |
| 立柱上升 | `600#0000000000000002` |
| 立柱下降 | `600#0000000000000001` |

**运行命令：**

```bash
cd /path/to/publish/modules/src/xarm_chassis

# 运行控制脚本（自动检测 rclpy，优先 ROS2 模式）
python3 chassis_control.py

# 或直接执行（需赋予执行权限）
chmod +x chassis_control.py
./chassis_control.py
```

运行成功后显示菜单：

```text
===== 底盘控制 =====
底盘运动 (1-5):
  1. 静止
  2. 左转
  3. 右转
  4. 前进
  5. 后退
立柱控制 (6-8):
  6. 立柱上升
  7. 立柱下降
  8. 立柱静止
q. 退出
同时支持 ROS2 话题 /chassis/cmd 控制

请输入命令 [1-8/q]:
```

**CLI 命令说明：**

| 输入 | 功能 | 说明 |
|------|------|------|
| 1 | 底盘静止 | 仅改变底盘状态 |
| 2 | 底盘左转 | 仅改变底盘状态 |
| 3 | 底盘右转 | 仅改变底盘状态 |
| 4 | 底盘前进 | 仅改变底盘状态 |
| 5 | 底盘后退 | 仅改变底盘状态 |
| 6 | 立柱上升 | 仅改变立柱状态 |
| 7 | 立柱下降 | 仅改变立柱状态 |
| 8 | 立柱静止 | 仅改变立柱状态 |
| q | 退出 | 发送停止命令 |

**ROS2 话题说明：**

**订阅的 ROS2 话题：**

| 话题名称 | 消息类型 | 说明 |
|---------|---------|------|
| `/chassis/cmd` | `std_msgs/String` | 底盘运动命令或立柱控制命令 |

**命令格式：**

**底盘控制命令：**

| 命令值 | 功能 |
|--------|------|
| `stop` | 底盘静止 |
| `left` | 底盘左转 |
| `right` | 底盘右转 |
| `forward` | 底盘前进 |
| `backward` | 底盘后退 |

**立柱控制命令：**

| 命令值 | 功能 |
|--------|------|
| `lift_stop` | 立柱静止 |
| `lift_up` | 立柱上升 |
| `lift_down` | 立柱下降 |

**ROS2 使用示例：**

```bash
# 控制底盘（不影响立柱）
ros2 topic pub /chassis/cmd std_msgs/msg/String "data: 'forward'"
ros2 topic pub /chassis/cmd std_msgs/msg/String "data: 'stop'"
ros2 topic pub /chassis/cmd std_msgs/msg/String "data: 'left'"
ros2 topic pub /chassis/cmd std_msgs/msg/String "data: 'right'"
ros2 topic pub /chassis/cmd std_msgs/msg/String "data: 'backward'"

# 控制立柱（不影响底盘）
ros2 topic pub /chassis/cmd std_msgs/msg/String "data: 'lift_up'"
ros2 topic pub /chassis/cmd std_msgs/msg/String "data: 'lift_down'"
ros2 topic pub /chassis/cmd std_msgs/msg/String "data: 'lift_stop'"

# 组合控制示例：底盘前进的同时立柱上升
ros2 topic pub /chassis/cmd std_msgs/msg/String "data: 'forward'"
ros2 topic pub /chassis/cmd std_msgs/msg/String "data: 'lift_up'"
```

**CLI 使用示例：**

```text
请输入命令 [1-8/q]: 4
→ 底盘: 前进  |  立柱: 静止

请输入命令 [1-8/q]: 6
→ 底盘: 前进  |  立柱: 上升

请输入命令 [1-8/q]: 8
→ 底盘: 前进  |  立柱: 静止

请输入命令 [1-8/q]: 1
→ 底盘: 静止  |  立柱: 静止

请输入命令 [1-8/q]: q
正在停止底盘和立柱...
```

**技术参数：**

| 参数 | 值 | 说明 |
|------|-----|------|
| CAN 通道 | `can2` | 发送 CAN 帧的总线通道 |
| 发送频率 | 5Hz | 每 0.2 秒发送一次 |
| 发送方式 | 三轮同时发送 | 左/右轮/立柱帧连续发送 |
| CAN ID | 0x601 / 0x603 / 0x600 | 左/右轮/立柱控制帧 ID |

**回退机制：**
- 如环境未安装 rclpy，自动回退到纯 CLI 模式

**退出行为：**
- 输入 `q` 或按 `Ctrl+C` 退出时，自动发送静止 CAN 帧，确保底盘和立柱停止运动

---

### 4.2 监听模式（旧版本固件）

`chassis_listener.py` 从 CAN 总线接收底盘反馈数据，并发布到 ROS2 话题。主要功能：
- 从 CAN 总线接收底盘里程计反馈数据（ID: 0x051），发布到 `/stm32/chassis_data` 话题

**运行命令：**

```bash
cd /path/to/publish/modules/src/xarm_chassis
python3 chassis_listener.py
```

运行成功后的日志：

```text
[INFO] [chassis_listener]: CAN bus can2 opened
[INFO] [chassis_listener]: Chassis listener node started
[INFO] [chassis_listener]: CAN receive thread started
```

**发布的 ROS2 话题：**

| 话题名称 | 消息类型 | 说明 |
|---------|---------|------|
| `/stm32/chassis_data` | `Float64MultiArray` | 底盘里程计反馈 |

**话题数据格式：**

`/stm32/chassis_data`:
```
data[0]: vx  - X轴位移
data[1]: vy  - Y轴位移
data[2]: vw  - w轴位移
```

**监听话题：**

```bash
# 监听底盘位移反馈
ros2 topic echo /stm32/chassis_data


---

### 4.3 两种模式区别

| 模式 | 依赖 ROS2 | 适用固件版本 | 控制方式 |
|------|-----------|-------------|---------|
| `chassis_control.py` | 可选（自动检测） | 新版本 | CLI + ROS2 话题双模式 |
| `chassis_listener.py` | 是 | 旧版本 | CAN 监听与数据发布 |

---

### 4.4 CAN 监听触发器（can_listener_trigger.sh）

`can_listener_trigger.sh` 用于监听 CAN 总线上的特定消息，并根据消息内容自动触发预设动作（如播放手臂动作日志）。

**功能特性：**
- 监听 `can2` 接口上的 CAN 消息
- 识别特定 CAN 帧（ID: 0x052）并触发相应动作
- 命令运行期间忽略重复触发
- 命令结束后进入冷却期（默认1秒），防止频繁触发

**支持的 CAN 消息：**

| CAN 帧 | 触发动作 |
|--------|---------|
| `0x052 [08] 50 00 00 00 00 00 00 01` | 右臂发送 Rws.log（can1） |
| `0x052 [08] 50 00 00 00 00 00 00 02` | 右臂发送 Rhs1.log（can1） |
| `0x052 [08] 60 00 00 00 00 00 00 01` | 右臂发送 Rhs2.log（can1） |
| `0x052 [08] 60 00 00 00 00 00 00 02` | 双臂同时发送 Lax1.log（can0）+ Rax1.log（can1） |

**运行命令：**

```bash
cd /path/to/publish/modules/src/xarm_chassis
chmod +x can_listener_trigger.sh
./can_listener_trigger.sh
```

**运行日志示例：**

```text
========================================
  CAN 监听触发器脚本
========================================
监听接口: can2
冷却时间: 1 秒
========================================
支持的 CAN 消息:
  0x052 [08] 50 00 00 00 00 00 00 01 - 帧1: 右臂(R)发送 Rws.log (can1)
  0x052 [08] 50 00 00 00 00 00 00 02 - 帧2: 右臂(R)发送 Rhs1.log (can1)
  0x052 [08] 60 00 00 00 00 00 00 01 - 帧3: 右臂(R)发送 Rhs2.log (can1)
  0x052 [08] 60 00 00 00 00 00 00 02 - 帧4: 双臂发送 Lax1.log(can0) + Rax1.log(can1)
========================================
按 Ctrl+C 退出

[2026-07-13 10:30:00] [INFO] 检测到帧1 (CAN ID: 0x052) - 右臂(R)发送 Rws.log
[2026-07-13 10:30:00] [INFO] 收到帧1信号 (CAN ID: 0x052)，启动命令...
[2026-07-13 10:30:05] [INFO] 命令执行完成，退出码: 0
[2026-07-13 10:30:05] [INFO] 进入冷却期，1秒后可再次触发
```

**技术参数：**

| 参数 | 值 | 说明 |
|------|-----|------|
| 监听接口 | `can2` | 监听的 CAN 总线通道 |
| 冷却时间 | 1秒 | 命令结束后需等待的时间 |
| 触发命令 | `send_data` | 调用的动作发送工具 |

---

### 4.5 服务配置脚本（fix_services.sh）

`fix_services.sh` 用于一键配置 systemd 服务，实现 CAN 接口初始化和 CAN 监听触发器的开机自启。

**功能特性：**
- 自动检测必要文件是否存在
- 设置脚本执行权限
- 创建 `setup-can.service`：开机自动配置 CAN 接口
- 创建 `can-listener.service`：开机自动启动 CAN 监听触发器
- 设置服务开机自启
- 验证服务配置状态

**创建的服务：**

| 服务名称 | 类型 | 功能 |
|---------|------|------|
| `setup-can.service` | oneshot | 初始化 CAN 接口（调用 `setup_can_interfaces.sh`） |
| `can-listener.service` | simple | 启动 CAN 监听触发器脚本 |

**服务依赖关系：**

```
multi-user.target
    └── can-listener.service
            └── setup-can.service
                    └── network.target
```

**运行命令：**

```bash
cd /path/to/publish/modules/src/xarm_chassis
chmod +x fix_services.sh
sudo ./fix_services.sh
```

**运行日志示例：**

```text
=== 配置 XArm CAN 监听服务 ===

1. 检查必要文件...
2. 设置脚本执行权限...
3. 创建/更新 setup-can.service...
4. 创建/更新 can-listener.service...
5. 重新加载 systemd 配置...
6. 设置开机自启动...
7. 验证服务状态...
setup-can.service: enabled
can-listener.service: enabled

=== 服务配置完成 ===

服务文件位置:
  - /etc/systemd/system/setup-can.service
  - /etc/systemd/system/can-listener.service

测试命令:
  sudo systemctl start setup-can.service
  sudo systemctl start can-listener.service
  sudo systemctl status setup-can.service can-listener.service
  sudo journalctl -u setup-can.service -u can-listener.service -f
  sudo reboot  # 重启验证开机自启
```

**服务管理命令：**

```bash
# 启动服务
sudo systemctl start setup-can.service
sudo systemctl start can-listener.service

# 停止服务
sudo systemctl stop can-listener.service
sudo systemctl stop setup-can.service

# 查看状态
sudo systemctl status setup-can.service can-listener.service

# 查看日志
sudo journalctl -u setup-can.service -u can-listener.service -f

# 禁用开机自启
sudo systemctl disable setup-can.service
sudo systemctl disable can-listener.service
```

---

## 5. CAN 数据格式

### 5.1 监听模式 CAN 报文（旧版本固件）

**接收报文 (ID: 0x051)**

| 字节 | 数据类型 | 含义 | 说明 |
|------|---------|------|------|
| 0-1 | int16_t | vx (X轴速度) | 底盘实际速度反馈 |
| 2-3 | int16_t | vy (Y轴速度) | 底盘实际速度反馈 |
| 4-5 | int16_t | vw (角速度) | 底盘实际速度反馈 |
| 7 (bit 0) | uint8_t | ch5 | 按钮状态 (1 bit) |
| 7 (bit 1) | uint8_t | ch6 | 按钮状态 (1 bit) |
| 7 (bit 2-3) | uint8_t | ch7 | 按钮状态 (2 bits) |
| 7 (bit 4-5) | uint8_t | ch8 | 按钮状态 (2 bits) |
| 7 (bit 6) | uint8_t | ch9 | 按钮状态 (1 bit) |

### 5.2 直接控制模式 CAN 报文（新版本固件）

| CAN ID | 用途 | 数据格式 |
|--------|------|---------|
| 0x601 | 左轮控制帧 | 8 字节，格式：`2B 18 23 00 [速度数据]` |
| 0x603 | 右轮控制帧 | 8 字节，格式：`2B 18 33 00 [速度数据]` |
| 0x600 | 立柱控制帧 | 8 字节，最后一字节为控制码（0/1/2）|

---

## 6. 常见问题排查

### 6.1 CAN 接口未找到

| 检查项 | 命令 |
|--------|------|
| CAN 接口是否存在 | `ip link show \| grep can` |
| CAN 接口是否 UP | `sudo ip link set can2 up type can bitrate 1000000` |
| 权限是否足够 | `sudo` 运行，或将用户加入 `netdev` 组 |

### 6.2 脚本运行后底盘无响应

| 检查项 | 说明 |
|--------|------|
| 固件版本是否匹配 | 旧版本固件只能使用监听模式，新版本固件使用 `chassis_control.py` |
| CAN 通道是否正确 | 确认使用 `can2` 通道 |
| CAN 总线物理连接 | 检查 CAN 收发器接线是否正确 |
| 电机是否已使能 | 确认底盘控制器已上电且电机处于使能状态 |

### 6.3 监听模式下速度数据全为 0

| 检查项 | 说明 |
|--------|------|
| CAN ID 0x051 是否有数据回报 | `candump can2` 实时抓包 |
| STM32 单片机是否正常运行 | 检查单片机指示灯状态 |

### 6.4 直接控制模式下 CAN 发送失败

| 检查项 | 说明 |
|--------|------|
| `cansend` 命令是否可用 | `cansend can2 601#2B18230000000000` |
| CAN 接口是否处于 UP 状态 | `ip link show can2` |
| 新版本固件是否已烧录 | 确认单片机已烧录更新后的代码 |

### 6.5 ROS2 话题发布后无响应

| 检查项 | 命令 |
|--------|------|
| ROS2 节点是否运行 | `ros2 node list` |
| 话题是否正确发布 | `ros2 topic echo /chassis/cmd` |
| 命令格式是否正确 | 确认命令为小写字符串，如 `'forward'` |

### 6.6 程序退出后电机仍在运动

原因：退出时未发送停止命令，或停止命令未成功传输。

解决：
- 使用 `chassis_control.py` 时，按 `q` 或 `Ctrl+C` 正常退出
- 节点会自动发送停止帧


### 6.7 遥控器对应模式没有生效

原因：可能没进入到对应模式
解决：上下拨动第四摇杆重置一下，再拨到需要的模式



---
