#!/usr/bin/env python3
import subprocess
import threading
import time
import struct
import sys

CAN_ID = 0x050

# 速度档位定义
SPEED_LEVELS = {
    "1": 200,
    "2": 400,
    "3": 600,
    "4": 800,
}
DEFAULT_SPEED = 800

# 底盘方向定义（只存方向，速度由 speed_level 动态决定）
# vx=左右, vy=前后, vw=旋转；值为 1/-1/0 表示该方向上的速度系数
CHASSIS_DIRS = {
    "stop":     {"vx_mul": 0,  "vy_mul": 0,  "vw_mul": 0},
    "forward":  {"vx_mul": 0,  "vy_mul": 1,  "vw_mul": 0},
    "backward": {"vx_mul": 0,  "vy_mul": -1, "vw_mul": 0},
    "left":     {"vx_mul": 0,  "vy_mul": 0,  "vw_mul": -1},
    "right":    {"vx_mul": 0,  "vy_mul": 0,  "vw_mul": 1},
}

# 立柱控制（0=静止, 1=下降, 2=上升）
LIFT_STATES = {
    "lift_stop":  0,
    "lift_up":    2,
    "lift_down":  1,
}

SEND_INTERVAL = 0.2

CMD_MAP = {
    "1": "stop",
    "2": "left",
    "3": "right",
    "4": "forward",
    "5": "backward",
    "6": "lift_up",
    "7": "lift_down",
    "8": "lift_stop",
    "s": "speed",
}


def build_can_frame(vx, vy, vw, updown):
    data = bytearray(8)
    data[0:2] = struct.pack('<h', vx)
    data[2:4] = struct.pack('<h', vy)
    data[4:6] = struct.pack('<h', vw)
    data[6] = 0
    data[7] = updown
    return {"id": CAN_ID, "data": list(data)}


def can_id_to_hex(id_val):
    return f"{id_val:03X}"


def can_data_to_hex(data):
    return "".join(f"{byte:02X}" for byte in data)


def can_frame_to_string(frame):
    return f"{can_id_to_hex(frame['id'])}#{can_data_to_hex(frame['data'])}"


class CANSender:
    def __init__(self, channel='can2', method='subprocess'):
        self.channel = channel
        self.method = method
        self.bus = None
        self._shutdown = False
        if method == 'python-can':
            import can
            self.bus = can.interface.Bus(channel=channel, interface='socketcan')

    def send(self, frame):
        if self.method == 'subprocess':
            frame_str = can_frame_to_string(frame)
            subprocess.run(["cansend", self.channel, frame_str], check=False)
        elif self.method == 'python-can' and self.bus and not self._shutdown:
            import can
            msg = can.Message(
                arbitration_id=frame["id"],
                data=frame["data"],
                is_extended_id=False
            )
            try:
                self.bus.send(msg)
            except can.CanError:
                pass

    def shutdown(self):
        if self.bus and not self._shutdown:
            self._shutdown = True
            self.bus.shutdown()


class ChassisController:
    def __init__(self, cansender):
        self.chassis_state = "stop"
        self.lift_state = "lift_stop"
        self.speed = DEFAULT_SPEED
        self.cansender = cansender
        self._stopped = False

    def set_chassis_state(self, state):
        if state in CHASSIS_DIRS:
            self.chassis_state = state
            return True
        return False

    def set_lift_state(self, state):
        if state in LIFT_STATES:
            self.lift_state = state
            return True
        return False

    def set_speed(self, speed):
        self.speed = speed

    def can_send_loop(self):
        if self._stopped:
            return
        d = CHASSIS_DIRS.get(self.chassis_state, CHASSIS_DIRS["stop"])
        vx = d["vx_mul"] * self.speed
        vy = d["vy_mul"] * self.speed
        vw = d["vw_mul"] * self.speed
        updown = LIFT_STATES.get(self.lift_state, LIFT_STATES["lift_stop"])
        frame = build_can_frame(vx, vy, vw, updown)
        self.cansender.send(frame)

    def stop_all(self):
        if self._stopped:
            return
        self._stopped = True
        frame = build_can_frame(0, 0, 0, 0)
        self.cansender.send(frame)
        self.cansender.shutdown()


def cli_input_loop(controller, exit_event):
    print("===== 底盘控制 =====")
    print("速度选择 (s):")
    print("  s   切换速度档位 (1=200 2=400 3=600 4=800)")
    print("底盘运动 (1-5):")
    print("  1. 静止")
    print("  2. 左转")
    print("  3. 右转")
    print("  4. 前进")
    print("  5. 后退")
    print("立柱控制 (6-8):")
    print("  6. 立柱上升")
    print("  7. 立柱下降")
    print("  8. 立柱静止")
    print("q. 退出")
    print("")

    while not exit_event.is_set():
        try:
            cmd = input(f"请输入命令 [1-8/s/q] (速度:{controller.speed}): ").strip()
            if cmd == "":
                continue
            if cmd == "q":
                print("\n正在停止底盘和立柱...")
                controller.stop_all()
                exit_event.set()
                return
            if cmd == "s":
                level = input(f"选择速度档位 {list(SPEED_LEVELS.keys())}: ").strip()
                if level in SPEED_LEVELS:
                    controller.set_speed(SPEED_LEVELS[level])
                    print(f"→ 速度设置为: {SPEED_LEVELS[level]}")
                else:
                    print("无效档位")
                continue
            if cmd in CMD_MAP:
                state = CMD_MAP[cmd]
                if state in CHASSIS_DIRS:
                    controller.set_chassis_state(state)
                    print(f"→ 底盘: {state}  |  速度: {controller.speed}  |  立柱: {controller.lift_state.replace('lift_', '')}")
                elif state in LIFT_STATES:
                    controller.set_lift_state(state)
                    print(f"→ 底盘: {controller.chassis_state}  |  速度: {controller.speed}  |  立柱: {state.replace('lift_', '')}")
            else:
                print("无效命令，请输入 1-8, s 或 q")
        except EOFError:
            print("\n正在停止底盘和立柱...")
            controller.stop_all()
            exit_event.set()
            return
        except KeyboardInterrupt:
            print("\n正在停止底盘和立柱...")
            controller.stop_all()
            exit_event.set()
            return


def ros2_node_main(controller):
    import rclpy
    from rclpy.node import Node
    from std_msgs.msg import String

    class ChassisControlROS2(Node):
        def __init__(self, controller):
            super().__init__('chassis_control_ros2')
            self.controller = controller

            self.sub = self.create_subscription(
                String,
                '/chassis/cmd',
                self.cmd_callback,
                10
            )

            self.timer = self.create_timer(
                SEND_INTERVAL,
                self.can_send_loop
            )

            self.get_logger().info('Chassis control ROS2 node started')
            self.get_logger().info('同时支持 CLI 命令行输入控制')

        def cmd_callback(self, msg: String):
            cmd = msg.data.strip().lower()
            if cmd in CHASSIS_DIRS:
                self.controller.set_chassis_state(cmd)
                self.get_logger().info(f'Chassis state: {cmd}, Speed: {self.controller.speed}, Lift state: {self.controller.lift_state}')
            elif cmd in LIFT_STATES:
                self.controller.set_lift_state(cmd)
                self.get_logger().info(f'Chassis state: {self.controller.chassis_state}, Speed: {self.controller.speed}, Lift state: {cmd}')
            elif cmd.startswith('speed_') and cmd[6:] in SPEED_LEVELS:
                self.controller.set_speed(SPEED_LEVELS[cmd[6:]])
                self.get_logger().info(f'Speed set to: {SPEED_LEVELS[cmd[6:]]}')
            else:
                self.get_logger().warn(f'Invalid command: {cmd}')

        def can_send_loop(self):
            self.controller.can_send_loop()

        def destroy_node(self):
            self.get_logger().info('Stopping chassis and lift...')
            self.controller.stop_all()
            super().destroy_node()

    rclpy.init()
    node = ChassisControlROS2(controller)

    exit_event = threading.Event()
    cli_thread = threading.Thread(target=cli_input_loop, args=(controller, exit_event), daemon=True)
    cli_thread.start()

    try:
        while rclpy.ok() and not exit_event.is_set():
            rclpy.spin_once(node, timeout_sec=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


def cli_only_main():
    cansender = CANSender(channel='can2', method='subprocess')
    controller = ChassisController(cansender)

    def send_loop():
        while not controller._stopped:
            controller.can_send_loop()
            time.sleep(SEND_INTERVAL)

    t = threading.Thread(target=send_loop, daemon=True)
    t.start()

    exit_event = threading.Event()
    cli_input_loop(controller, exit_event)


def main():
    try:
        import rclpy
        cansender = CANSender(channel='can2', method='python-can')
        controller = ChassisController(cansender)
        ros2_node_main(controller)
    except ImportError:
        print("rclpy 未安装，回退到纯 CLI 模式")
        cli_only_main()


if __name__ == "__main__":
    main()
