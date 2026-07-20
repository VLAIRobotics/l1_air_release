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

        self.updown_data = 0

        # ================= STM32 协议换算比例 =================
        # 固件发送的是 int16 大端有符号数，数值 = 实际值 * 1000
        self.ODOM_LINEAR_SCALE = 1.0 / 1000.0   # m / unit
        self.ODOM_ANGULAR_SCALE = 1.0 / 1000.0  # rad / unit
        self.ODOM_LINEAR_CORRECTION = 0.5       # 线位移里程计当前实测偏大约 2 倍

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
        # 发布底盘累积位移（横向位移x, 前后位移y, 旋转角度w）
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
        self.updown_data = float(data[2])
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
        down = self.updown_data  # 上下

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



        if self.updown_data == 1:
            updown = 2
        elif self.updown_data == -1:
            updown = 1
        else:
            updown = 0
        print(f"Joystick: x={x:.2f}, y={y:.2f}, down={self.updown_data} → vx={vx}, vy={vy}, vw={vw}, updown={updown}")
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

                # ================= 里程计解析 =================
                # STM32 发送格式：
                # [0:2] x, [2:4] y, [4:6] z
                # [6] ch4_state(0/1/2)
                # [7] 高4位 ch5_state(0/1), 低4位 ch6_state(0/1)
                # x/y/z 均为大端有符号 int16，且数值 = 实际值 * 1000
                if can_id == 0x051:       
                    odom_x_raw = struct.unpack('>h', data[0:2])[0]
                    odom_y_raw = struct.unpack('>h', data[2:4])[0]
                    odom_z_raw = struct.unpack('>h', data[4:6])[0]
                    ch4_state = int(data[6] & 0x0F)
                    ch5_state = int((data[7] >> 4) & 0x0F)
                    ch6_state = int(data[7] & 0x0F)

                    # 直接还原为 STM32 当前发送的物理量：
                    # x/y 单位 m，z 原始单位 rad
                    vx_display = odom_x_raw * self.ODOM_LINEAR_SCALE * self.ODOM_LINEAR_CORRECTION
                    vy_display = odom_y_raw * self.ODOM_LINEAR_SCALE * self.ODOM_LINEAR_CORRECTION
                    vw_display = math.degrees(odom_z_raw * self.ODOM_ANGULAR_SCALE)

                    # ================= 发布显示数据 =================
                    chassis_msg = Float64MultiArray()
                    chassis_msg.data = [
                        float(vx_display),
                        float(vy_display),
                        float(vw_display),
                        float(ch4_state),
                        float(ch5_state),
                        float(ch6_state),
                    ]
                    self.chassis_pub.publish(chassis_msg)

                    # ================= 日志输出（三个数据都显示） =================
                    self.get_logger().info(
                        f"Chassis: display(x={vx_display:.4f}m, y={vy_display:.4f}m, w={vw_display:.2f}deg, ch4={ch4_state}, ch5={ch5_state}, ch6={ch6_state}) | raw(x={odom_x_raw}, y={odom_y_raw}, z={odom_z_raw})"
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
