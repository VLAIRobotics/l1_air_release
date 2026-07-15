#!/usr/bin/env python3
"""Repeat position-reach cycles via joint_trajectory_controller, continuously
recording every joint's position/velocity/effort throughout both the
target-reach (去程) and home-return (回程) phases of every trial.

Unlike a "final error only" test, this captures the full motion profile per
phase, so problems that only show up mid-motion (velocity spikes, overshoot,
oscillation) are visible in the CSV, not just the settled endpoint error.

CSV is written incrementally (flushed every sample) so data survives even if
the script crashes mid-run, not just on a clean Ctrl+C.

Usage:
  source /opt/ros/humble/setup.bash
  source <workspace>/install/setup.bash
  python3 accuracy_test.py --trials 100 --target 0 0 0 1.2 0 0 0

  # bimanual: each side is its own controller/action server, test separately
  python3 accuracy_test.py --side right --trials 100 --target 0 0.5 0 0.5 0 0 0
  python3 accuracy_test.py --side left  --trials 100 --target 0 0.5 0 0.5 0 0 0
"""

import argparse
import csv
import math
import statistics
import sys
import time

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from control_msgs.action import FollowJointTrajectory
from trajectory_msgs.msg import JointTrajectoryPoint
from sensor_msgs.msg import JointState


def joint_names_for(side: str):
    prefix = {"single": "", "left": "left_", "right": "right_"}[side]
    return [f"xarm_{prefix}joint{i}" for i in range(1, 8)]


def action_topic_for(side: str):
    controller = {"single": "joint_trajectory_controller",
                  "left": "left_joint_trajectory_controller",
                  "right": "right_joint_trajectory_controller"}[side]
    return f"/{controller}/follow_joint_trajectory"


class AccuracyTester(Node):

    def __init__(self, side, move_time, settle_time, writer, csv_file):
        super().__init__("accuracy_tester")
        self.joint_names = joint_names_for(side)
        self.move_time = move_time
        self.settle_time = settle_time
        self.writer = writer
        self.csv_file = csv_file
        self.latest_state = {}

        # recording context: set before a phase starts, cleared after
        self._trial = None
        self._phase = None
        self._target = None
        self._phase_t0 = None

        # last settled reading per phase, for the per-trial log line
        self.last_reading = {}

        # per-joint error, sampled only during the settle_time window after
        # each trajectory completes (not while still in transit, where
        # position-vs-target is naturally large and meaningless as an
        # accuracy number), for the overall mean/max/std summary
        self._settling = False
        self.all_errors = [[] for _ in self.joint_names]

        self.create_subscription(JointState, "/joint_states", self._on_state, 50)
        self.client = ActionClient(
            self, FollowJointTrajectory, action_topic_for(side))

    def _on_state(self, msg: JointState):
        d = dict(zip(msg.name, zip(msg.position, msg.velocity, msg.effort)))
        for name in self.joint_names:
            if name in d:
                self.latest_state[name] = d[name]

        if self._phase is None:
            return

        t = time.time() - self._phase_t0
        row = [self._trial, self._phase, f"{t:.4f}"]
        for j, (name, tgt) in enumerate(zip(self.joint_names, self._target)):
            pos, vel, eff = self.latest_state.get(name, (float("nan"),) * 3)
            err = pos - tgt
            row += [pos, vel, eff, tgt, err]
            if self._settling and self._phase == "target":
                self.all_errors[j].append(abs(err))
        self.writer.writerow(row)
        self.csv_file.flush()
        self.last_reading[self._phase] = [self.latest_state.get(n, (float("nan"),) * 3)[0]
                                           for n in self.joint_names]

    def wait_for_server(self, timeout=10.0):
        if not self.client.wait_for_server(timeout_sec=timeout):
            raise RuntimeError("Action server not available")

    def run_phase(self, trial, phase, setpoint):
        """Send a goal and continuously log until it completes + settles."""
        self._trial = trial
        self._phase = phase
        self._target = setpoint
        self._phase_t0 = time.time()

        goal = FollowJointTrajectory.Goal()
        goal.trajectory.joint_names = self.joint_names
        point = JointTrajectoryPoint()
        point.positions = setpoint
        point.time_from_start.sec = int(self.move_time)
        point.time_from_start.nanosec = int((self.move_time % 1) * 1e9)
        goal.trajectory.points = [point]

        send_future = self.client.send_goal_async(goal)
        rclpy.spin_until_future_complete(self, send_future)
        goal_handle = send_future.result()
        if not goal_handle.accepted:
            self._phase = None
            raise RuntimeError("Goal rejected")

        result_future = goal_handle.get_result_async()
        rclpy.spin_until_future_complete(self, result_future)

        self._settling = True
        deadline = time.time() + self.settle_time
        while time.time() < deadline:
            rclpy.spin_once(self, timeout_sec=0.02)
        self._settling = False

        self._phase = None
        return self.last_reading.get(phase, [float("nan")] * 7)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--side", choices=["single", "left", "right"],
                        default="single",
                        help="single-arm, or which bimanual arm to test "
                             "(bimanual has separate left/right controllers)")
    parser.add_argument("--trials", type=int, default=100)
    parser.add_argument("--target", type=float, nargs=7,
                         default=[0.0, 0.0, 0.0, 1.2, 0.0, 0.0, 0.0])
    parser.add_argument("--home", type=float, nargs=7,
                         default=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    parser.add_argument("--move-time", type=float, default=3.0)
    parser.add_argument("--settle-time", type=float, default=1.0)
    parser.add_argument("--out", type=str, default="/tmp/accuracy_log.csv")
    args = parser.parse_args()

    joint_names = joint_names_for(args.side)

    # Only the joints actually commanded to a nonzero target are "under
    # test" - the rest are just expected to hold near zero and aren't what
    # the user is asking about, so keep both per-trial logging and the final
    # summary scoped to these.
    tested = [i for i, t in enumerate(args.target) if t != 0.0]
    if not tested:
        tested = list(range(len(joint_names)))

    header = ["trial", "phase", "t"]
    for name in joint_names:
        header += [f"{name}_pos", f"{name}_vel", f"{name}_eff",
                   f"{name}_target", f"{name}_err"]

    f = open(args.out, "w", newline="")
    writer = csv.writer(f)
    writer.writerow(header)
    f.flush()

    rclpy.init()
    node = AccuracyTester(args.side, args.move_time, args.settle_time, writer, f)
    node.wait_for_server()

    n_done = 0

    try:
        for i in range(args.trials):
            actual = node.run_phase(i, "target", args.target)
            err_str = ", ".join(
                f"{joint_names[j]}={math.degrees(abs(actual[j] - args.target[j])):.3f}deg"
                for j in tested)
            node.get_logger().info(f"[{i+1}/{args.trials}] target reached, {err_str}")

            actual = node.run_phase(i, "home", args.home)

            n_done = i + 1
    except KeyboardInterrupt:
        node.get_logger().warn("Interrupted by user, partial results already saved")
    except Exception as e:  # noqa: BLE001 - want partial data preserved on any crash
        node.get_logger().error(f"Crashed: {e!r}, partial results already saved")
    finally:
        f.close()

    print(f"\n=== Summary over {n_done} trials (saved to {args.out}, "
          f"per-sample motion profile included; stats below are target-reach "
          f"settled error only, home-return not counted, tested joints only) ===")
    for j in tested:
        name = joint_names[j]
        e = node.all_errors[j]
        if not e:
            continue
        e_deg = [math.degrees(x) for x in e]
        print(f"{name}: mean_abs_err={statistics.mean(e_deg):.3f} deg  "
              f"max_abs_err={max(e_deg):.3f} deg  "
              f"std={statistics.pstdev(e_deg):.3f} deg")

    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    sys.exit(main())
