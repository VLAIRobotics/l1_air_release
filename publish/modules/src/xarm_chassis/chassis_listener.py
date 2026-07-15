#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from std_msgs.msg import Float64MultiArray
import can
import struct
import threading


class ChassisListener(Node):

    def __init__(self):
        super().__init__('chassis_listener')

        self.bus = can.interface.Bus(
            channel='can2',
            interface='socketcan'
        )
        self.get_logger().info('CAN bus can2 opened')

        self.recv_thread = threading.Thread(
            target=self.can_recv_loop,
            daemon=True
        )
        self.recv_thread.start()

        self.chassis_pub = self.create_publisher(
            Float64MultiArray,
            '/stm32/chassis_data',
            10
        )

        self.get_logger().info('Chassis listener node started')

    def can_recv_loop(self):
        self.get_logger().info("CAN receive thread started")

        while rclpy.ok():
            try:
                msg = self.bus.recv(timeout=1.0)
                if msg is None:
                    continue

                can_id = msg.arbitration_id
                data = msg.data

                if can_id == 0x051:
                    vy = struct.unpack('<h', data[2:4])[0]
                    vw = struct.unpack('<h', data[4:6])[0]

                    chassis_msg = Float64MultiArray()
                    chassis_msg.data = [float(vy), float(vw)]
                    self.chassis_pub.publish(chassis_msg)

                    self.get_logger().info(
                        f"Chassis: vy={vy}, vw={vw}"
                    )

            except can.CanError as e:
                self.get_logger().error(f"CAN recv failed: {e}")


def main():
    rclpy.init()
    node = ChassisListener()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
