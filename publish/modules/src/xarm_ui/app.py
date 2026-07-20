#!/usr/bin/env python3
"""
XArm 控制 Web UI 后端服务器
提供RESTful API和WebSocket接口用于机械臂控制和状态监控
"""

from flask import Flask, render_template, request, jsonify, Response
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import subprocess
import os
import signal
import threading
import time
from pathlib import Path
from typing import Dict, Optional, List
import logging

CAMERA_PREVIEW_TOPICS = {
    "cam_chest": "/cam_chest/cam_chest/color/image_raw",
    "cam_wrist_left": "/cam_wrist_left/cam_wrist_left/color/image_raw",
    "cam_wrist_right": "/cam_wrist_right/cam_wrist_right/color/image_raw",
}

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'xarm_control_secret_2026'

# 修改 Jinja2 分隔符，避免与 Vue.js 冲突
app.jinja_env.variable_start_string = '[['
app.jinja_env.variable_end_string = ']]'

CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# 全局进程管理
active_processes: Dict[str, subprocess.Popen] = {}
process_lock = threading.Lock()


class CameraPreviewManager:
    """Subscribe ROS image topics and expose latest JPEG frames for the web UI."""

    def __init__(self):
        self._lock = threading.Lock()
        self._frames = {name: None for name in CAMERA_PREVIEW_TOPICS}
        self._subscriptions = {}
        self._rclpy = None
        self._node = None
        self._bridge = None
        self._executor_thread = None

    def _ensure_runtime(self) -> Dict:
        if self._node is not None:
            return {"success": True}
        try:
            import rclpy
            from cv_bridge import CvBridge
            from rclpy.node import Node

            if not rclpy.ok():
                rclpy.init(args=None)
            self._rclpy = rclpy
            self._node = Node("xarm_ui_preview_node")
            self._bridge = CvBridge()
            self._executor_thread = threading.Thread(target=self._spin, daemon=True)
            self._executor_thread.start()
            return {"success": True}
        except Exception as exc:
            logger.error(f"初始化相机预览失败: {exc}")
            return {"success": False, "message": str(exc)}

    def _spin(self):
        while self._node is not None and self._rclpy is not None:
            try:
                self._rclpy.spin_once(self._node, timeout_sec=0.1)
            except Exception as exc:
                logger.error(f"相机预览 spin 失败: {exc}")
                time.sleep(0.2)

    def _make_callback(self, camera_name: str):
        def _callback(msg):
            try:
                import cv2
                frame = self._bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
                ok, encoded = cv2.imencode(".jpg", frame)
                if ok:
                    with self._lock:
                        if camera_name in self._subscriptions:
                            self._frames[camera_name] = encoded.tobytes()
            except Exception as exc:
                logger.error(f"{camera_name} 图像转换失败: {exc}")
        return _callback

    def start(self, camera_names: Optional[List[str]] = None) -> Dict:
        runtime = self._ensure_runtime()
        if not runtime.get("success"):
            return runtime
        try:
            from sensor_msgs.msg import Image
            targets = camera_names or list(CAMERA_PREVIEW_TOPICS.keys())
            with self._lock:
                for camera_name in targets:
                    if camera_name not in CAMERA_PREVIEW_TOPICS:
                        continue
                    if camera_name in self._subscriptions:
                        continue
                    sub = self._node.create_subscription(
                        Image,
                        CAMERA_PREVIEW_TOPICS[camera_name],
                        self._make_callback(camera_name),
                        10,
                    )
                    self._subscriptions[camera_name] = sub
            return {"success": True, "message": "相机预览已启动"}
        except Exception as exc:
            logger.error(f"启动相机预览失败: {exc}")
            return {"success": False, "message": str(exc)}

    def stop_all(self):
        with self._lock:
            for camera_name, sub in list(self._subscriptions.items()):
                try:
                    self._node.destroy_subscription(sub)
                except Exception as exc:
                    logger.warning(f"停止 {camera_name} 预览订阅失败: {exc}")
                self._frames[camera_name] = None
            self._subscriptions.clear()

    def status(self, camera_name: str) -> Dict:
        with self._lock:
            return {
                "success": True,
                "subscribed": camera_name in self._subscriptions,
                "available": self._frames.get(camera_name) is not None,
                "topic": CAMERA_PREVIEW_TOPICS.get(camera_name, ""),
            }

    def frame(self, camera_name: str):
        with self._lock:
            return self._frames.get(camera_name)


preview_manager = CameraPreviewManager()

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent
TELEOP_DIR = PROJECT_ROOT / "src" / "xarm_teleop"
TELEOP_SCRIPT_DIR = PROJECT_ROOT / "src" / "xarm_teleop" / "script"
COLLECTOR_DIR = PROJECT_ROOT / "src" / "lerobot_collector"
XARM_CAN_LIBEXEC_DIR = PROJECT_ROOT.parent / "xarm_can" / "package" / "libexec"


class ProcessManager:
    """管理后台进程"""
    
    @staticmethod
    def start_process(
        name: str, 
        command: List[str], 
        cwd: Optional[str] = None,
        env: Optional[Dict] = None,
        enable_stdin: bool = False
    ) -> Dict:
        """启动一个后台进程
        
        Args:
            name: 进程名称
            command: 命令列表
            cwd: 工作目录
            env: 环境变量
            enable_stdin: 是否启用stdin通信（用于交互式控制）
        """
        with process_lock:
            if name in active_processes and active_processes[name].poll() is None:
                return {"success": False, "message": f"进程 {name} 已在运行"}
            
            try:
                # 合并环境变量
                process_env = os.environ.copy()
                if env:
                    process_env.update(env)
                
                # 启动进程
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.PIPE if enable_stdin else subprocess.DEVNULL,
                    cwd=cwd,
                    env=process_env,
                    text=True,
                    bufsize=1,
                    preexec_fn=os.setsid  # 创建新进程组
                )
                
                active_processes[name] = process
                logger.info(f"✅ 启动进程: {name}, PID: {process.pid}")
                
                # 启动日志监听线程
                threading.Thread(
                    target=ProcessManager._stream_output,
                    args=(name, process),
                    daemon=True
                ).start()
                
                return {
                    "success": True, 
                    "message": f"进程 {name} 启动成功",
                    "pid": process.pid
                }
                
            except Exception as e:
                logger.error(f"❌ 启动进程失败: {name}, 错误: {e}")
                return {"success": False, "message": str(e)}
    
    @staticmethod
    def stop_process(name: str) -> Dict:
        """停止一个后台进程"""
        fallback_patterns = {
            'camera_node': r'multi_realsense|realsense2_camera|ros2 launch multi_realsense',
            'teleop_right_arm': r'unilateral_control.*right_arm|launch_unilateral.*right_arm',
            'teleop_left_arm': r'unilateral_control.*left_arm|launch_unilateral.*left_arm',
            'recorder_right_arm': r'xarm_ros2_record.py.*right_arm',
            'recorder_left_arm': r'xarm_ros2_record.py.*left_arm',
        }

        with process_lock:
            if name not in active_processes or active_processes[name].poll() is not None:
                # 从 active_processes 清理残留
                if name in active_processes:
                    del active_processes[name]
                # 尝试 pgrep 兜底
                pattern = fallback_patterns.get(name)
                if pattern:
                    try:
                        result = subprocess.run(
                            ['pgrep', '-f', pattern],
                            capture_output=True, text=True, timeout=2
                        )
                        pids = [int(p) for p in result.stdout.strip().split('\n') if p.strip().isdigit()]
                        if pids:
                            for pid in pids:
                                try:
                                    os.killpg(os.getpgid(pid), signal.SIGTERM)
                                except ProcessLookupError:
                                    os.kill(pid, signal.SIGTERM)
                            logger.info(f"✅ 通过 pgrep 停止进程: {name} (pids: {pids})")
                            return {"success": True, "message": f"进程 {name} 已停止"}
                    except Exception as e:
                        logger.error(f"pgrep fallback 失败: {e}")
                return {"success": False, "message": f"进程 {name} 不存在"}

            process = active_processes[name]
            try:
                # 向进程组发送SIGTERM
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)

                # 等待进程结束（recorder cleanup 需要时间写入数据）
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    process.wait()

                del active_processes[name]
                logger.info(f"✅ 停止进程: {name}")
                return {"success": True, "message": f"进程 {name} 已停止"}

            except Exception as e:
                logger.error(f"❌ 停止进程失败: {name}, 错误: {e}")
                return {"success": False, "message": str(e)}
    
    @staticmethod
    def get_status() -> Dict:
        """获取所有进程状态"""
        with process_lock:
            status = {}
            for name, process in list(active_processes.items()):
                poll_result = process.poll()
                if poll_result is None:
                    status[name] = {"running": True, "pid": process.pid}
                else:
                    status[name] = {"running": False, "exit_code": poll_result}
                    # 清理已结束的进程
                    del active_processes[name]
            
            # 兼容：页面刷新后进程仍在，但active_processes已丢失
            def _find_pids(pattern: str) -> List[int]:
                try:
                    result = subprocess.run(
                        ['pgrep', '-f', pattern],
                        capture_output=True,
                        text=True,
                        timeout=2
                    )
                    if result.returncode != 0:
                        return []
                    return [int(pid) for pid in result.stdout.strip().split('\n') if pid.strip().isdigit()]
                except Exception:
                    return []
            
            fallback_checks = {
                'camera_node': r'multi_realsense|realsense2_camera|ros2 launch multi_realsense',
                'teleop_right_arm': r'unilateral_control.*right_arm|launch_unilateral.*right_arm',
                'teleop_left_arm': r'unilateral_control.*left_arm|launch_unilateral.*left_arm',
                'recorder_right_arm': r'xarm_ros2_record.py.*right_arm',
                'recorder_left_arm': r'xarm_ros2_record.py.*left_arm'
            }
            
            for name, pattern in fallback_checks.items():
                if name in status:
                    continue
                pids = _find_pids(pattern)
                if pids:
                    status[name] = {"running": True, "pid": pids[0]}
            
            return status
    
    @staticmethod
    def _stream_output(name: str, process: subprocess.Popen):
        """流式读取进程输出并通过WebSocket发送"""
        def _classify(msg: str, default_type: str) -> str:
            """根据 ROS2 日志前缀判断实际类型"""
            if '[ERROR]' in msg or '[FATAL]' in msg:
                return 'stderr'
            if '[WARN]' in msg:
                return 'stdwarn'
            if '[INFO]' in msg:
                return 'stdout'
            return default_type

        def _read_stream(stream, stream_type: str):
            try:
                for line in iter(stream.readline, ''):
                    if line:
                        msg = line.strip()
                        socketio.emit('process_log', {
                            'process': name,
                            'type': _classify(msg, stream_type),
                            'message': msg
                        })
            except Exception as e:
                logger.error(f"日志流错误 {name} ({stream_type}): {e}")
        
        try:
            if process.stdout:
                threading.Thread(
                    target=_read_stream,
                    args=(process.stdout, 'stdout'),
                    daemon=True
                ).start()
            if process.stderr:
                threading.Thread(
                    target=_read_stream,
                    args=(process.stderr, 'stderr'),
                    daemon=True
                ).start()
        except Exception as e:
            logger.error(f"日志流错误 {name}: {e}")


# ==================== REST API 路由 ====================

@app.route('/')
def index():
    """主页"""
    return render_template('index-v1.html')


@app.route('/api/system/info', methods=['GET'])
def system_info():
    """获取系统信息"""
    return jsonify({
        "project_root": str(PROJECT_ROOT),
        "teleop_scripts": str(TELEOP_SCRIPT_DIR),
        "collector_dir": str(COLLECTOR_DIR),
        "ros_distro": os.environ.get('ROS_DISTRO', 'unknown')
    })


@app.route('/api/process/status', methods=['GET'])
def process_status():
    """获取所有进程状态"""
    return jsonify(ProcessManager.get_status())


@app.route('/api/teleop/start', methods=['POST'])
def start_teleop():
    """启动遥操作"""
    data = request.json
    arm_side = data.get('arm_side', 'right_arm')
    leader_can = data.get('leader_can', 'can0' if arm_side == 'right_arm' else 'can2')
    follower_can = data.get('follower_can', 'can1' if arm_side == 'right_arm' else 'can3')
    use_ros2 = data.get('use_ros2', False)
    
    script_name = 'launch_unilateral_ros2.sh' if use_ros2 else 'launch_unilateral.sh'
    script_path = TELEOP_SCRIPT_DIR / script_name
    
    if not script_path.exists():
        return jsonify({"success": False, "message": f"脚本不存在: {script_path}"})
    
    command = ['bash', str(script_path), arm_side, leader_can, follower_can]
    process_name = f"teleop_{arm_side}"
    
    result = ProcessManager.start_process(
        name=process_name,
        command=command,
        cwd=str(TELEOP_DIR)
    )
    
    return jsonify(result)


@app.route('/api/teleop/stop', methods=['POST'])
def stop_teleop():
    """停止遥操作"""
    data = request.json
    arm_side = data.get('arm_side', 'right_arm')
    process_name = f"teleop_{arm_side}"
    
    # 先停止Web UI跟踪的进程
    result = ProcessManager.stop_process(process_name)
    
    # 额外清理：强制杀死所有unilateral_control进程
    try:
        subprocess.run(
            ['pkill', '-9', '-f', 'unilateral_control'],
            capture_output=True,
            timeout=5
        )
        logger.info("已清理所有 unilateral_control 进程")
    except Exception as e:
        logger.warning(f"清理进程时出错: {e}")
    
    return jsonify(result)


@app.route('/api/can/status', methods=['GET'])
def can_status():
    """检查 CAN 接口状态"""
    try:
        result = subprocess.run(
            ['ip', 'link', 'show'],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        # 过滤出 CAN 接口信息
        lines = result.stdout.split('\n')
        can_interfaces = []
        current_interface = None
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # 检测接口行（包含 ":"）
            if ': can' in line:
                parts = line.split(':')
                if len(parts) >= 2:
                    # 提取接口名
                    iface_name = parts[1].strip().split()[0]
                    
                    # 检查是否为 UP 状态
                    is_up = 'UP' in line and 'state UP' in line
                    
                    # 构造简洁的状态信息
                    if 'state UP' in line:
                        status = 'UP - 运行中'
                    elif 'state DOWN' in line:
                        status = 'DOWN - 未启动'
                    else:
                        status = '未知状态'
                    
                    # 提取 MTU 信息
                    if 'mtu' in line:
                        mtu_match = line.split('mtu')[1].split()[0]
                        status += f' (MTU: {mtu_match})'
                    
                    can_interfaces.append({
                        'name': iface_name,
                        'status': status,
                        'is_up': is_up
                    })
        
        return jsonify({
            "success": True,
            "interfaces": can_interfaces,
            "output": result.stdout
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route('/api/can/setup', methods=['POST'])
def can_setup():
    """配置 CAN 接口"""
    try:
        script_path = XARM_CAN_LIBEXEC_DIR / 'setup_can_interfaces.sh'
        
        if not script_path.exists():
            return jsonify({
                "success": False,
                "message": f"配置脚本不存在: {script_path}"
            })
        
        # 已经是 root 直接跑脚本；非 root 才需要 pkexec 弹图形密码提权
        # （pkexec 依赖 polkit D-Bus 服务，纯命令行/容器环境下通常不可用）
        cmd = ['bash', str(script_path)] if os.geteuid() == 0 else ['pkexec', 'bash', str(script_path)]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            env=os.environ.copy()
        )

        if result.returncode != 0 and 'not authorized' in result.stderr.lower():
            # 如果 pkexec 失败，返回手动配置提示
            return jsonify({
                "success": False,
                "message": "需要管理员权限。请在终端手动运行：sudo " + str(script_path),
                "error": result.stderr,
                "manual_command": f"sudo {script_path}"
            })
        
        return jsonify({
            "success": result.returncode == 0,
            "output": result.stdout,
            "error": result.stderr,
            "message": "CAN 接口配置成功" if result.returncode == 0 else "CAN 接口配置失败"
        })
    except subprocess.TimeoutExpired:
        return jsonify({
            "success": False,
            "message": "配置超时，可能需要手动授权"
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "message": f"配置失败: {str(e)}。请在终端手动运行：sudo {script_path}",
            "manual_command": f"sudo {script_path}"
        })


@app.route('/api/can/setzero', methods=['POST'])
def can_setzero():
    """设置机械臂零点"""
    try:
        data = request.get_json() or {}
        can_if = data.get('can_if', 'can0')
        script_path = XARM_CAN_LIBEXEC_DIR / 'set_zero.sh'

        if not script_path.exists():
            return jsonify({"success": False, "message": f"脚本不存在: {script_path}"})

        result = subprocess.run(
            ['bash', str(script_path), can_if, '--all'],
            capture_output=True, text=True, timeout=30,
            env=os.environ.copy()
        )

        return jsonify({
            "success": result.returncode == 0,
            "output": result.stdout,
            "error": result.stderr,
            "message": f"{can_if} 零点设置完成" if result.returncode == 0 else f"{can_if} 零点设置失败"
        })
    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "message": "零点设置超时"})
    except Exception as e:
        return jsonify({"success": False, "message": f"零点设置失败: {str(e)}"})


@app.route('/api/camera/check', methods=['GET'])
def check_cameras():
    """检查相机"""
    try:
        workspace_setup = str(PROJECT_ROOT / "install" / "setup.bash")
        result = subprocess.run(
            ['bash', '-c', f'source /opt/ros/humble/setup.bash && source {workspace_setup} && ros2 run multi_realsense check_cameras.py'],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        output = result.stdout
        error = result.stderr
        
        # 记录原始输出以便调试
        logger.info(f"检查相机 - 返回码: {result.returncode}")
        logger.info(f"检查相机 - stdout: {output[:200] if output else '(空)'}")
        logger.info(f"检查相机 - stderr: {error[:200] if error else '(空)'}")
        
        # 判断是否检测到相机：检查输出中是否包含成功标志
        # 即使返回码非0，只要输出包含"检测到"和"相机"就认为成功
        has_camera = output and ('✅ 检测到' in output or ('检测到' in output and '相机' in output))
        
        if has_camera:
            # 提取关键信息：相机数量和每个相机的信息
            import re
            
            # 提取相机数量
            camera_count_match = re.search(r'检测到\s+(\d+)\s+个相机', output)
            camera_count = camera_count_match.group(1) if camera_count_match else '未知'
            
            # 提取每个相机的信息
            camera_info = []
            camera_list = []  # 用于前端下拉选择
            camera_blocks = re.findall(r'相机\s+\d+:\s+名称:\s+(.+?)\s+序列号:\s+(\w+)', output, re.DOTALL)
            for idx, (name, serial) in enumerate(camera_blocks, 1):
                name = name.strip()
                camera_info.append(f"相机 {idx}: {name} (序列号: {serial})")
                camera_list.append({
                    "name": name,
                    "serial": serial
                })
            
            # 构造简洁的输出
            summary = f"✅ 检测到 {camera_count} 个相机\n\n" + "\n".join(camera_info)
            
            return jsonify({
                "success": True,
                "output": summary,
                "cameras": camera_list,  # 返回相机列表供前端选择
                "raw_output": output,  # 保留原始输出以备需要
                "error": error
            })
        else:
            # 没有连接设备
            return jsonify({
                "success": False,
                "output": "⚠️ 未检测到 RealSense 相机，请检查是否已连接",
                "error": error,
                "no_camera": True
            })
    except subprocess.TimeoutExpired:
        return jsonify({
            "success": False,
            "message": "检查相机超时（10秒）",
            "error": "命令执行超时，请检查系统状态"
        })
    except Exception as e:
        logger.error(f"检查相机异常: {e}")
        return jsonify({
            "success": False,
            "message": str(e),
            "error": "执行检查命令时出错"
        })


@app.route('/api/camera/launch', methods=['POST'])
def launch_cameras():
    """启动相机节点"""
    data = request.json
    camera_config = data.get('config', 'multi')  # 'single' or 'multi'
    
    # 创建临时启动脚本
    import tempfile
    workspace_setup = str(PROJECT_ROOT / "install" / "setup.bash")
    
    if camera_config == 'multi':
        serial_chest = data.get('serialChest', '')
        serial_left = data.get('serialLeft', '')
        serial_right = data.get('serialRight', '')

        if serial_left and serial_right and serial_left == serial_right:
            return jsonify({
                "success": False,
                "message": "左手腕和右手腕不能选择同一个相机序列号"
            })

        # 构建 launch 参数，只包含非空的序列号
        launch_params = []
        if serial_chest:
            launch_params.append(f'serial_chest:="{serial_chest}"')
        if serial_left:
            launch_params.append(f'serial_left:="{serial_left}"')
        if serial_right:
            launch_params.append(f'serial_right:="{serial_right}"')
        
        # 至少需要一个相机
        if not launch_params:
            return jsonify({
                "success": False,
                "message": "请至少选择一个相机"
            })
        
        params_str = ' '.join(launch_params)
        
        launch_script = f"""#!/bin/bash
set -e
echo "Sourcing ROS2 base environment..."
source /opt/ros/humble/setup.bash
echo "Sourcing workspace: {workspace_setup}"
source {workspace_setup}
echo "Checking if multi_realsense package exists..."
ros2 pkg list | grep multi_realsense || echo "WARNING: multi_realsense not found in package list"
echo "Launching multi_realsense with params: {params_str}"
exec ros2 launch multi_realsense multi_cameras.launch.py {params_str}
"""
    else:
        camera_name = data.get('cameraName', 'test_cam')
        serial_no = data.get('serialNo', '')
        
        # 验证序列号不为空
        if not serial_no:
            return jsonify({
                "success": False,
                "message": "请先检查相机并选择序列号"
            })
        
        launch_script = f"""#!/bin/bash
set -e
echo "Sourcing ROS2 base environment..."
source /opt/ros/humble/setup.bash
echo "Sourcing workspace: {workspace_setup}"
source {workspace_setup}
echo "Checking if multi_realsense package exists..."
ros2 pkg list | grep multi_realsense || echo "WARNING: multi_realsense not found in package list"
echo "Launching multi_realsense..."
exec ros2 launch multi_realsense single_camera.launch.py camera_name:={camera_name} serial_no:=\\"{serial_no}\\"
"""
    
    # 写入临时脚本
    with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
        f.write(launch_script)
        script_path = f.name
    
    # 添加执行权限
    os.chmod(script_path, 0o755)
    
    logger.info(f"启动相机，使用临时脚本: {script_path}")
    logger.info(f"工作空间路径: {workspace_setup}")
    command = ['bash', script_path]
    
    result = ProcessManager.start_process(
        name='camera_node',
        command=command
    )
    
    return jsonify(result)


@app.route('/api/camera/stop', methods=['POST'])
def stop_cameras():
    """停止相机节点"""
    preview_manager.stop_all()
    result = ProcessManager.stop_process('camera_node')
    
    # 额外清理：防止 ros2 launch 派生进程残留
    try:
        subprocess.run(
            ['pkill', '-9', '-f', 'multi_realsense|realsense2_camera|single_camera.launch.py|multi_cameras.launch.py'],
            capture_output=True,
            timeout=5
        )
        logger.info("已清理所有 multi_realsense / realsense2_camera 进程")
    except Exception as e:
        logger.warning(f"清理相机进程时出错: {e}")
    
    return jsonify(result)


@app.route('/api/camera/preview/start', methods=['POST'])
def start_camera_preview():
    """启动网页相机预览订阅。"""
    data = request.json or {}
    camera_names = data.get("camera_names")
    if not isinstance(camera_names, list):
        camera_names = None
    return jsonify(preview_manager.start(camera_names))


@app.route('/api/camera/preview/status', methods=['GET'])
def camera_preview_status():
    """返回指定相机的网页预览状态。"""
    camera_name = request.args.get("camera_name", "cam_chest")
    return jsonify(preview_manager.status(camera_name))


@app.route('/api/camera/preview/stream', methods=['GET'])
def camera_preview_stream():
    """输出 MJPEG 预览流。"""
    camera_name = request.args.get("camera_name", "cam_chest")
    if camera_name not in CAMERA_PREVIEW_TOPICS:
        return jsonify({"success": False, "message": "未知相机"}), 404

    def generate():
        while True:
            payload = preview_manager.frame(camera_name)
            if payload is None:
                time.sleep(0.05)
                continue
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + payload + b"\r\n"
            )
            time.sleep(0.03)

    return Response(
        generate(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route('/api/record/start', methods=['POST'])
def start_recording():
    """启动数据录制"""
    data = request.json
    
    repo_id = data.get('repo_id', 'xarm_dataset')
    root = data.get('root', '~/lerobot_datasets')
    arm_side = data.get('arm_side', 'right_arm')
    task = data.get('task', 'pick and place')
    num_episodes = data.get('num_episodes', 50)
    use_wrist_camera = data.get('use_wrist_camera', False)
    
    # 使用 bash -c 来 source ROS2 环境
    setup_bash = PROJECT_ROOT / "install" / "setup.bash"
    recorder_script = COLLECTOR_DIR / 'xarm_ros2_record.py'
    
    # 激活 lerobot conda 环境并运行录制脚本
    ros_command = f"""
# 初始化 conda
eval "$(conda shell.bash hook)"

# 激活 lerobot 环境
conda activate lerobot

# Source ROS2环境
source /opt/ros/humble/setup.bash
source {setup_bash}

# 运行录制脚本（用 exec 替换 bash，确保stdin直接到python）
exec python3 -u {recorder_script} --repo-id '{repo_id}' --root '{root}' --arm-side {arm_side} --single-task '{task}' --num-episodes {num_episodes}"""
    
    if use_wrist_camera:
        ros_command += ' --use-wrist-camera'
    
    command = ['bash', '-c', ros_command]
    
    result = ProcessManager.start_process(
        name=f'recorder_{arm_side}',
        command=command,
        cwd=str(COLLECTOR_DIR),
        enable_stdin=True  # 启用stdin以便发送控制命令
    )
    
    return jsonify(result)


@app.route('/api/record/stop', methods=['POST'])
def stop_recording():
    """停止数据录制"""
    data = request.json
    arm_side = data.get('arm_side', 'right_arm')
    process_name = f'recorder_{arm_side}'
    
    result = ProcessManager.stop_process(process_name)
    return jsonify(result)


@app.route('/api/record/control', methods=['POST'])
def control_recording():
    """控制数据录制的episode操作
    
    支持的命令:
        - 'r': 开始录制当前episode
        - 'h': 机器人回到初始位置
        - 's': 保存当前episode（不回零）
        - 'n': 保存当前episode并回到初始位置
    """
    data = request.json
    arm_side = data.get('arm_side', 'right_arm')
    command = data.get('command', '')
    process_name = f'recorder_{arm_side}'
    
    # 验证命令
    valid_commands = ['r', 'h', 's', 'n']
    if command not in valid_commands:
        return jsonify({
            'success': False,
            'message': f'Invalid command. Must be one of: {valid_commands}'
        })
    
    # 检查进程是否运行（使用全局active_processes）
    with process_lock:
        if process_name not in active_processes:
            return jsonify({
                'success': False,
                'message': 'Recording process is not running'
            })
        
        process = active_processes[process_name]
        
        # 检查进程是否还活着
        if process.poll() is not None:
            return jsonify({
                'success': False,
                'message': 'Recording process has stopped'
            })
        
        try:
            # 向进程的stdin发送命令
            if process.stdin is None:
                return jsonify({
                    'success': False,
                    'message': 'Recording process stdin is not available'
                })
            process.stdin.write(f'{command}\n')
            process.stdin.flush()
            
            command_desc = {
                'r': '开始录制episode',
                'h': '机器人回到初始位置',
                's': '保存episode（不回零）',
                'n': '保存episode并回到初始位置'
            }
            
            return jsonify({
                'success': True,
                'message': f'Command sent: {command_desc.get(command, command)}'
            })
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'Failed to send command: {str(e)}'
            })


@app.route('/api/ros/topics', methods=['GET'])
def get_ros_topics():
    """获取ROS话题列表"""
    try:
        setup_bash = PROJECT_ROOT / "install" / "setup.bash"
        result = subprocess.run(
            ['bash', '-c', f'source /opt/ros/humble/setup.bash && source {setup_bash} && ros2 topic list'],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        topics = result.stdout.strip().split('\n')
        return jsonify({
            "success": True,
            "topics": topics
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route('/api/ros/nodes', methods=['GET'])
def get_ros_nodes():
    """获取ROS节点列表"""
    try:
        setup_bash = PROJECT_ROOT / "install" / "setup.bash"
        result = subprocess.run(
            ['bash', '-c', f'source /opt/ros/humble/setup.bash && source {setup_bash} && ros2 node list'],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        nodes = result.stdout.strip().split('\n')
        return jsonify({
            "success": True,
            "nodes": nodes
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


# ==================== WebSocket 事件处理 ====================

@socketio.on('connect')
def handle_connect():
    """客户端连接"""
    logger.info("客户端已连接")
    emit('connection_response', {'status': 'connected'})


@socketio.on('disconnect')
def handle_disconnect():
    """客户端断开"""
    logger.info("客户端已断开")


@socketio.on('request_status')
def handle_status_request():
    """请求系统状态"""
    status = ProcessManager.get_status()
    emit('status_update', status)


# ==================== 主程序 ====================

if __name__ == '__main__':
    logger.info("🚀 启动 XArm 控制 Web UI 服务器")
    logger.info(f"📁 项目根目录: {PROJECT_ROOT}")
    logger.info(f"🎮 遥操作脚本: {TELEOP_SCRIPT_DIR}")
    logger.info(f"📹 数据采集: {COLLECTOR_DIR}")
    logger.info("🌐 访问地址: http://localhost:5000")
    
    # 启动服务器
    socketio.run(app, host='0.0.0.0', port=5000, debug=True, allow_unsafe_werkzeug=True)
