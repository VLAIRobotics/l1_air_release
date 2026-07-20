#include <chrono>
#include <csignal>
#include <cstdio>
#include <cstring>
#include <sstream>
#include <string>
#include <thread>
#include <vector>
#include <xarm_teleop_sdk.h>

static xarm_teleop_handle_t g_handle = nullptr;
static volatile std::sig_atomic_t g_stop_requested = 0;

static void on_signal(int /*sig*/) {
    g_stop_requested = 1;
}

static void print_usage(const char *prog) {
    fprintf(stderr,
            "用法: %s <leader_urdf> <follower_urdf> <arm_side> <leader_can> <follower_can> [config_dir] [--home j1,j2,j3,j4,j5,j6,j7]\n"
            "  arm_side    : right_arm | left_arm\n"
            "  leader_can  : Leader 臂 CAN 接口，如 can0\n"
            "  follower_can: Follower 臂 CAN 接口，如 can2\n"
            "  config_dir  : 配置目录（含 leader.yaml/follower.yaml），默认: config\n"
            "  --home      : 初始关节位置（弧度），逗号分隔的7个值，如 0,0,0,0.628,0,0,0\n",
            prog);
}

static std::vector<double> parse_home_position(const char *str) {
    std::vector<double> pos;
    std::istringstream ss(str);
    std::string token;
    while (std::getline(ss, token, ',')) {
        pos.push_back(std::stod(token));
    }
    return pos;
}

int main(int argc, char **argv) {
    if (argc < 6) {
        print_usage(argv[0]);
        return 1;
    }

    const char *leader_urdf   = argv[1];
    const char *follower_urdf = argv[2];
    const char *arm_side      = argv[3];
    const char *leader_can    = argv[4];
    const char *follower_can  = argv[5];
    const char *config_dir    = "config";
    std::vector<double> home_position;

    for (int i = 6; i < argc; ++i) {
        if (std::strcmp(argv[i], "--home") == 0 && i + 1 < argc) {
            home_position = parse_home_position(argv[++i]);
        } else if (home_position.empty() && argv[i][0] != '-') {
            config_dir = argv[i];
        }
    }

    fprintf(stdout,
            "=== XArm 单边遥操作 (SDK %s) ===\n"
            "  arm_side      : %s\n"
            "  leader_can    : %s\n"
            "  follower_can  : %s\n"
            "  leader_urdf   : %s\n"
            "  follower_urdf : %s\n"
            "  config_dir    : %s\n",
            xarm_teleop_version(), arm_side, leader_can, follower_can,
            leader_urdf, follower_urdf, config_dir);

    int ret = xarm_teleop_create_unilateral(leader_can, follower_can,
                                             leader_urdf, follower_urdf,
                                             arm_side, config_dir, &g_handle);
    if (ret != XARM_TELEOP_OK) {
        fprintf(stderr, "[ERROR] 初始化失败: %s\n", xarm_teleop_get_last_error());
        return 1;
    }

    if (!home_position.empty()) {
        ret = xarm_teleop_set_home_position(g_handle, home_position.data(),
                                             static_cast<int>(home_position.size()));
        if (ret != XARM_TELEOP_OK) {
            fprintf(stderr, "[ERROR] 设置初始位置失败: %s\n", xarm_teleop_get_last_error());
            xarm_teleop_destroy(g_handle);
            return 1;
        }
        fprintf(stdout, "  home_position : 已设置（%zu 个关节）\n", home_position.size());
    }

    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);

    ret = xarm_teleop_start(g_handle);
    if (ret != XARM_TELEOP_OK) {
        fprintf(stderr, "[ERROR] 启动失败: %s\n", xarm_teleop_get_last_error());
        xarm_teleop_destroy(g_handle);
        return 1;
    }

    fprintf(stdout, "控制循环运行中，按 Ctrl+C 停止...\n");
    while (!g_stop_requested && xarm_teleop_is_running(g_handle) == 1) {
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }

    if (xarm_teleop_is_running(g_handle) == 1) {
        xarm_teleop_stop(g_handle);
    }
    xarm_teleop_destroy(g_handle);
    g_handle = nullptr;
    fprintf(stdout, "已停止。\n");
    return 0;
}
