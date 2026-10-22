from __future__ import annotations

import argparse
import time
import webbrowser

from ..config import load_config
from ..console import ControlHTTPServer
from .control_center import ResearchControlCenter


def launch_research_console(cfg, *, environment="sim", armed=False, output=None,
                            port=None, open_browser=True, auto_run=False,
                            duration_s=None, mode=None):
    if environment not in ("sim", "mirror"):
        raise ValueError("research console uses sim or mirror; legacy real-video experiments use the standard hardware console")
    if environment == "mirror" and not armed:
        raise ValueError("mirror drives physical ZR10 units and requires --arm")
    selected_mode = mode or cfg.control_center.get("default_mode", "ecprh")
    center = ResearchControlCenter(cfg, environment=environment, armed=armed, output=output)
    pending = None
    if auto_run:
        pending = {"action": "start", "environment": environment, "armed": armed,
                   "mode": selected_mode,
                   "duration_s": duration_s if duration_s is not None else cfg.system.get("duration_s", 60)}
    server = None
    try:
        center.start()
        server = ControlHTTPServer(center,
            port=cfg.control_center.get("port", 0) if port is None else port,
            auto_start=pending)
        server.start()
        print("ZR10 持续搜索/连续监视研究控制中心已启动（仅本机访问）。", flush=True)
        print(f"任务环境: {environment}; 虚拟目标为权威任务真值。", flush=True)
        if environment == "mirror":
            print("MIRROR: 真实 ZR10 只执行 A/E/Zoom；真实视频不参与目标闭环。", flush=True)
        print(server.url, flush=True)
        if open_browser:
            webbrowser.open(server.url, new=1)
        while True:
            time.sleep(0.25)
    except KeyboardInterrupt:
        print("正在停止研究会话、保存记录并关闭控制中心……", flush=True)
    finally:
        if server is not None:
            server.close()
        center.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="ECP-RH persistent-search research control center")
    parser.add_argument("--config", default="configs/research/search_monitor_base.yaml")
    parser.add_argument("--mode", choices=("sim", "mirror"), default="sim")
    parser.add_argument("--algorithm", default=None,
                        choices=("ecprh", "weighted_rh", "greedy", "fixed_scan", "classical_ptz", "info_planner", "ssm_belief"))
    parser.add_argument("--arm", action="store_true")
    parser.add_argument("--output")
    parser.add_argument("--port", type=int)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--auto-run", action="store_true")
    parser.add_argument("--duration", type=float)
    args = parser.parse_args(argv)
    cfg = load_config(args.config)
    launch_research_console(cfg, environment=args.mode, armed=args.arm, output=args.output,
                            port=args.port, open_browser=not args.no_browser,
                            auto_run=args.auto_run, duration_s=args.duration,
                            mode=args.algorithm)


if __name__ == "__main__":
    main()
