"""命令行只做参数解释，业务逻辑留在可测试的独立模块中。"""
from __future__ import annotations
import argparse
import asyncio
import json
from pathlib import Path
import sys
from .config import load_config,validate_config


def main(argv=None):
    parser = argparse.ArgumentParser(description="ZR10 多智能体协同观测实验平台")
    sub = parser.add_subparsers(dest="command",required=True)
    for name in ("run","validate","probe","capabilities"):
        p = sub.add_parser(name)
        p.add_argument("--config",default="configs/four_zr10.yaml")
        if name=="run":
            p.add_argument("--mode",choices=("sim","hardware"),default="sim")
            p.add_argument("--duration",type=float)
            p.add_argument("--seed",type=int)
            p.add_argument("--output")
            p.add_argument("--realtime",action="store_true")
            p.add_argument("--arm",action="store_true",help="明确启动实机运动闭环")
            interface = p.add_mutually_exclusive_group()
            interface.add_argument("--ui", dest="ui", action="store_true", help="弹出总控制中心并从界面监督本次实验")
            interface.add_argument("--no-ui", dest="ui", action="store_false", help="本次不打开界面，覆盖配置中的界面开关")
            p.set_defaults(ui=None)
            p.add_argument("--ui-port", type=int, default=None, help="本机界面端口，默认自动分配")
            p.add_argument("--no-browser", action="store_true", help="启动界面服务但仅打印链接")
        if name=="probe":
            p.add_argument("--output",default="probe_result.json")
    p = sub.add_parser("analyze"); p.add_argument("session"); p.add_argument("--no-plots",action="store_true")
    p = sub.add_parser("replay"); p.add_argument("session"); p.add_argument("--output",default="runs")
    p.add_argument("--fusion-json",default="{}",help="例如 {\"max_residual_m\":1.0}")
    p = sub.add_parser("monitor"); p.add_argument("session",nargs="?",default="runs")
    p = sub.add_parser("console", help="打开可操作的设备总控制中心，等待在界面中启动实验")
    p.add_argument("--config", default="configs/four_zr10.yaml")
    p.add_argument("--mode", choices=("sim", "hardware"), default="sim")
    p.add_argument("--arm", action="store_true")
    p.add_argument("--output")
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command in ("run","validate","probe","capabilities","console"):
            cfg = load_config(args.config)
        if args.command=="validate":
            from .geometry import intrinsics_at_zoom
            from .actions import ActionValidator
            ActionValidator(cfg)
            for d in cfg.active_devices:
                intrinsics_at_zoom(d,d.initial_zoom)
            print(f"配置通过：{len(cfg.active_devices)} 台设备，{cfg.system.get('rate_hz',10)} Hz")
        elif args.command=="capabilities":
            from .actions import PARAMETERS
            from dataclasses import asdict
            print(json.dumps({k:asdict(v) for k,v in PARAMETERS.items()},ensure_ascii=False,indent=2))
        elif args.command=="probe":
            from .hardware import probe_devices
            result = asyncio.run(probe_devices(cfg))
            Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
            print(json.dumps(result,ensure_ascii=False,indent=2))
            return 0 if all(r["ok"] for r in result) else 2
        elif args.command=="run":
            from .runtime import run_simulation,run_hardware
            show_ui = cfg.control_center.get("enabled", False) if args.ui is None else args.ui
            if args.duration is not None:
                # 无界面实验仍要求正时长；界面允许 0 表示用户手动结束。
                if args.duration != 0 or not show_ui:
                    cfg.system["duration_s"] = args.duration
            if args.seed is not None:
                cfg.simulation["seed"] = args.seed
            validate_config(cfg)
            if show_ui:
                from .console import launch_console
                launch_console(cfg, environment=args.mode, armed=args.arm, output=args.output,
                    port=args.ui_port,
                    open_browser=not args.no_browser and cfg.control_center.get("open_browser", True),
                    auto_run=True, duration_s=args.duration)
                return 0
            def progress(s):
                if s["step"] % max(1,int(cfg.system.get("rate_hz",10)*5)) == 0:
                    m = s["metrics"]
                    print(f"cycle={s['step']} tracks={len(s['tracks'])} measured={m['measured_track_count']} coverage={m['roi_cumulative_coverage']:.1%}",flush=True)
            path = run_simulation(cfg,args.output,args.realtime,progress) if args.mode=="sim" else asyncio.run(run_hardware(cfg,args.output,args.arm,progress))
            print(f"实验记录：{path}")
            print(f'生成报告：python -m zr10lab analyze "{path}"')
        elif args.command=="analyze":
            from .analysis import analyze_session
            print(json.dumps(analyze_session(args.session,not args.no_plots),ensure_ascii=False,indent=2))
        elif args.command=="replay":
            from .analysis import replay_session
            print(replay_session(args.session,args.output,json.loads(args.fusion_json)))
        elif args.command=="monitor":
            from .monitor import monitor
            monitor(args.session)
        elif args.command=="console":
            from .console import launch_console
            launch_console(cfg, environment=args.mode, armed=args.arm, output=args.output,
                port=args.port,
                open_browser=not args.no_browser and cfg.control_center.get("open_browser", True))
        return 0
    except KeyboardInterrupt:
        print("实验已中断；已执行关闭与日志刷新。",file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"错误：{type(exc).__name__}: {exc}",file=sys.stderr)
        return 1
