from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

try:
    from siyi_sdk import configure_logging
except ImportError:
    def configure_logging(*, level: str = "WARNING") -> None:
        del level

import zr10_coop
from zr10_coop.config import load_config
from zr10_coop.manager import CooperativeObservationSystem
from zr10_coop.policies import build_policy


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run scalable cooperative observation control "
            "for multiple ZR10 gimbals."
        )
    )
    parser.add_argument(
        "--config",
        default="config/three_zr10.yaml",
        help="YAML configuration path",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Use simulated gimbals and generate complete CSV logs",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Override system.duration_s; 0 means run until Ctrl+C",
    )
    parser.add_argument(
        "--sdk-log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser.parse_args()


async def async_main() -> None:
    args = parse_args()
    config_path = Path(args.config).expanduser().resolve()
    config = load_config(config_path)
    if args.duration is not None:
        config.system.duration_s = args.duration

    configure_logging(level=args.sdk_log_level)
    policy = build_policy(config.policy)
    system = CooperativeObservationSystem(
        config,
        policy,
        dry_run=args.dry_run,
    )

    print(f"Project version: {zr10_coop.__version__}")
    print(f"Imported package: {Path(zr10_coop.__file__).resolve()}")
    print(f"Configuration: {config_path}")
    print(
        "Devices: "
        + ", ".join(
            f"{g.id}={g.ip}"
            for g in config.enabled_gimbals()
        )
    )
    print(
        "Mode: "
        + (
            "DRY-RUN simulation"
            if args.dry_run
            else "REAL ZR10 hardware"
        )
    )
    print("Press Ctrl+C to stop safely.\n")

    log_dir = await system.run()
    print(f"\nSession complete. Logs: {log_dir}")


def main() -> None:
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
