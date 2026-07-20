#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from std_msgs.msg import Float64MultiArray
import can
import struct
import threading
import math


class JoystickToCan(Node):

    def __init__(self):
        super().__init__('joystick_to_can')

        # ================= 参数 =================
        self.max_speed = 800
        self.can_id = 0x050
        self.send_hz = 200.0  # CAN 发送频率（Hz）

        # ================= 状态缓存 =================
        self.latest_joy = None
        self.joy_lock = threading.Lock()

        self.updowndatedate = 0

        # ================= CAN 初始化 =================
        try:
            self.bus = can.interface.Bus(
                channel='can2',
                interface='socketcan'
            )
            self.get_logger().info('CAN bus can2 opened')
        except Exception as e:
            self.get_logger().error(f'CAN init failed: {e}')
            raise
        # ================= CAN 接收线程 =================
        self.recv_thread = threading.Thread(
             target=self.can_recv_loop,
             daemon=True
        )
        self.recv_thread.start()

        # ================= ROS 订阅 =================
        self.sub = self.create_subscription(
            Float64MultiArray,
            '/dual_xarm/joystick',
            self.joystick_callback,
            10
        )
        self.subdate = self.create_subscription(
            Float64MultiArray,
            '/dual_xarm/py_motor_target',
            self.py_motor_position_callback,
            10
        )

        # ================= ROS 发布 =================
        # 发布底盘数据（速度：vx, vy, vw）
        self.chassis_pub = self.create_publisher(
            Float64MultiArray,
            '/stm32/chassis_data',
            10
        )




        # ================= 定时器（CAN 发送） =================
        self.timer = self.create_timer(
            1.0 / self.send_hz,
            self.can_send_loop
        )

        self.get_logger().info('Joystick → CAN node started')

    # ==================================================
    #                Joystick Callback
    # ==================================================
    def joystick_callback(self, msg: Float64MultiArray):
        # 只做数据接收 & 校验

        if len(msg.data) != 4:
            return

        # 数据合法性检查
        for v in msg.data:
            if not isinstance(v, float) or not math.isfinite(v):
                return

        with self.joy_lock:
            self.latest_joy = msg.data[:]  # 拷贝一份

    def py_motor_position_callback(self, msg):
        data = list(msg.data)
        if len(data) < 3:
            # 消息长度不足：数据包损坏或发布端格式错误，跳过本帧
            self.get_logger().warn("⚠️ PY motor msg length < 2")
            return
        self.updowndatedate = float(data[2])
    # ==================================================
    #                CAN Send Loop
    # ==================================================
    def can_send_loop(self):
        with self.joy_lock:
            if self.latest_joy is None:
                return
            joy = self.latest_joy

        # ================= 解析数据 =================
        x    = joy[0]   # 左右
        y    = joy[1]   # 前后        
        down = self.updowndatedate  # 上下

        # ================= 映射速度 =================
        # vx = 0
        # vy = int(-y * self.max_speed)
        # vw = int(x * self.max_speed)

        # vy = max(-self.max_speed, min(self.max_speed, vy))
        # vw = max(-self.max_speed, min(self.max_speed, vw))

        vx = int(x * self.max_speed)
        vy = int(y * self.max_speed)
        vw = 0

        vy = max(-self.max_speed, min(self.max_speed, vy))
        vx = max(-self.max_speed, min(self.max_speed, vx))



        if down == 1:
            updown = 2
        elif down == -1:
            updown = 1
        else:
            updown = 0
        print(f"Joystick: x={x:.2f}, y={y:.2f}, down={down} → vx={vx}, vy={vy}, vw={vw}, updown={updown}")
        # ================= 打包 CAN =================
        data = bytearray(8)
        data[0:2] = struct.pack('<h', vx)
        data[2:4] = struct.pack('<h', vy)
        data[4:6] = struct.pack('<h', vw)
        data[6] = 0
        data[7] = updown

        # ================= 发送 CAN =================
        try:
            msg = can.Message(
                arbitration_id=self.can_id,
                data=data,
                is_extended_id=False
            )
            self.bus.send(msg)
        except can.CanError:
            return

        self.get_logger().debug(
            f'CAN sent: vx={vx}, vy={vy}, vw={vw}, updown={updown}'
        )

# ==================================================
#                CAN Receive Loop
# ==================================================
    def can_recv_loop(self):

        self.get_logger().info("CAN receive thread started")

        while rclpy.ok():

            try:
                msg = self.bus.recv(timeout=1.0)

                if msg is None:
                    continue

                # ================= 基本信息 =================
                can_id = msg.arbitration_id
                data = msg.data
                dlc = msg.dlc

                # print(f"\n[CAN RX]")
                # print(f"ID   : 0x{can_id:03X}")
                # print(f"DLC  : {dlc}")
                # print(f"DATA : {[hex(b) for b in data]}")

                # ================= 示例解析 =================
                # 假设对方也发:
                # int16 vx vy vw
                if can_id == 0x051:       
                    vx = struct.unpack('<h', data[0:2])[0]
                    vy = struct.unpack('<h', data[2:4])[0]
                    vw = struct.unpack('<h', data[4:6])[0]

                    chassis_msg = Float64MultiArray()
                    chassis_msg.data = [float(vx), float(vy), float(vw)]
                    self.chassis_pub.publish(chassis_msg)

                    self.get_logger().info(
                        f"Chassis: vx={vx}, vy={vy}, vw={vw}"
                    )

            except can.CanError as e:
                self.get_logger().error(f"CAN recv failed: {e}")


def main():
    rclpy.init()
    node = JoystickToCan()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()