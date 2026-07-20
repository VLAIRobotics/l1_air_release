# CHANGELOG L1

L1 系列版本的变更记录。

版本号遵循 `vMAJOR.MINOR.PATCH`。L1 版本独立编号，并在每个发布条目中标注对应的 X1 基线版本。

---

## [Unreleased]

<!-- 在这里记录尚未发布的 L1 改动，发布时将本节内容移动到新版本条目 -->

---

## [v1.2.0] - 2026-07-17

> 对应 X1 版本：v1.4.0

### 新功能

- `can_listener_trigger.sh`：新增 CAN 监听触发器脚本，支持通过遥控器摇杆触发预定义动作（Rws.log、Rhs1.log、Rhs2.log、Lax1.log+Rax1.log）。
- `chassis_listener.py`：新增 `/stm32/actual_distance` 话题，发布相对于启动位置的实际位移值。

### 优化

- `chassis_listener.py`：新增角度翻转处理，自动处理旋转角度跨越 360 度边界的情况，确保角度连续累加。
- `can_listener_trigger.sh`：实现重置机制、1秒冷却时间和动作互斥，确保触发安全可靠。

### 修复


- `mini_car` 固件：修复遥控器离线模式判断逻辑，使用 `remoter.online` 标志位替代通道值判断，离线时切换为 `AUTO_MODE` 允许上位机控制。

---

## [v1.1.1] - 2026-07-16

> 对应 X1 版本：v1.4.0

### 优化

- `chassis_listener.py`：CAN ID 0x051 返回数据从速度改为累积位移，新增位移换算比例（含 0.5 倍修正系数）。

### 文档

- 完善底盘控制使用文档，补充位移换算比例和位移范围说明。

---

## [v1.1.0] - 2026-07-15

> 对应 X1 版本：v1.4.0

### 新功能

- 初始发布 L1 系列版本，基于 X1 v1.4.0。
- `chassis_control.py`：支持双模式控制（ROS2 话题 + CLI），支持底盘运动和立柱升降控制。
- `chassis_listener.py`：ROS2 节点，负责操纵杆数据与 CAN 总线的桥接，订阅遥控器话题并发布底盘状态反馈。
- 支持 4 档可调速度（200/400/600/800）。
- CAN 通信基于 SocketCAN，200Hz 发送频率。

### 文档

- 新增底盘使用文档（`05_xarm_chassis使用文档.md`）
