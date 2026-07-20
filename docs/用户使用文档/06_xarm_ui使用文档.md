# XArm UI 使用文档

## 1. 简介

`xarm_ui` 是基于 Flask + Vue.js 的 XArm 机械臂 Web 控制面板，提供 CAN 接口管理、遥操作控制、相机管理、数据采集等功能，可在浏览器中统一操作和监控机械臂系统。

## 2. 文件清单

```
~/x_air/publish/modules/src/xarm_ui/
├── app.py              # Flask 后端
├── start_ui.sh         # 启动脚本
├── requirements.txt    # Python 依赖
├── static/             # 静态资源（JS、图片）
└── templates/
    ├── index.html      # 前端页面
    └── index-v1.html   # 前端页面（v1 版本）
```

## 3. 环境要求

- Python 3.10+
- ROS2 Humble
- `can-utils`（`cansend`、`ip` 命令）
- Intel RealSense SDK（可选，用于相机功能）

## 4. 快速开始

### 4.1 安装 Python 依赖

```bash
cd ~/x_air/publish/modules/src/xarm_ui
pip3 install -r requirements.txt
```

依赖包：
- `flask >= 3.0.0`
- `flask-cors >= 4.0.0`
- `flask-socketio >= 5.3.0`
- `python-socketio >= 5.11.0`

### 4.2 配置 ROS2 环境

```bash
source /opt/ros/humble/setup.bash
source ~/x_air/publish/modules/install/setup.bash
```

### 4.3 配置 CAN 接口

首次使用前需要配置 CAN 硬件接口（需要 sudo 权限）：

```bash
sudo src/xarm_can/setup/setup_can_interfaces.sh
```

或在 Web UI 中点击"配置 CAN 接口"按钮。

### 4.4 启动

```bash
cd ~/x_air/publish/modules/src/xarm_ui
bash start_ui.sh
```

启动后访问：**http://localhost:5000**

脚本会自动：
1. 检查 Python 环境
2. 安装/更新依赖
3. 检查 ROS2 环境变量
4. 检查端口占用（如已占用可选择自动释放）

## 5. 功能说明

### 5.1 CAN 接口管理

- **配置 CAN 接口**：以 CAN-FD 模式初始化 can0–can3（bitrate 1 Mbps，dbitrate 5 Mbps）
- **检查接口状态**：查看各接口 UP/DOWN 状态

### 5.2 遥操作控制

- 选择机械臂（右臂 / 左臂）
- 选择主臂和从臂 CAN 接口（从已检测接口中选择）
- **零点设置**：对指定 CAN 接口上的所有电机（ID 001–008）发送零点校准指令
- 启动 / 停止遥操作进程

### 5.3 相机管理

- 检测已连接的 Intel RealSense 相机
- 启动 / 停止相机节点（支持单相机和双相机模式）

### 5.4 数据采集

- 配置数据集名称、任务描述、采集帧率等参数
- 启动 / 停止录制
- 支持 episode 控制（保存 / 重录）
- 基于 [LeRobot](https://github.com/huggingface/lerobot) 0.3.3+

> 注意：数据采集功能依赖 `src/lerobot_collector` 模块，该模块属于 pro/max 产品层级功能，air 基础版若未包含该模块，对应入口在 Web UI 中将不可用。

### 5.5 ROS 系统监控

- 刷新查看当前活跃的 ROS2 话题和节点

### 5.6 系统日志

实时显示各模块日志，颜色区分：
- 蓝色：标准输出
- 黄色：警告
- 红色：错误
- 紫色：状态信息

## 6. API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/system/info` | 系统信息 |
| GET | `/api/process/status` | 运行中的进程列表 |
| POST | `/api/teleop/start` | 启动遥操作 |
| POST | `/api/teleop/stop` | 停止遥操作 |
| GET | `/api/can/status` | CAN 接口状态 |
| POST | `/api/can/setup` | 配置 CAN 接口 |
| POST | `/api/can/setzero` | 设置电机零点 |
| GET | `/api/camera/check` | 检测相机 |
| POST | `/api/camera/launch` | 启动相机节点 |
| POST | `/api/camera/stop` | 停止相机节点 |
| POST | `/api/record/start` | 开始录制 |
| POST | `/api/record/stop` | 停止录制 |
| POST | `/api/record/control` | 控制 episode |
| GET | `/api/ros/topics` | ROS2 话题列表 |
| GET | `/api/ros/nodes` | ROS2 节点列表 |

## 7. 注意事项

### 7.1 端口占用

默认监听端口为 5000，如被占用，`start_ui.sh` 会提示是否自动释放（`kill -9` 占用进程）。

### 7.2 路径解析

`app.py` 中的工作空间路径（`PROJECT_ROOT`）按 `src/xarm_ui` 相对当前文件的上两级目录自动推导，对应 `publish/modules/`，无需手动修改。
