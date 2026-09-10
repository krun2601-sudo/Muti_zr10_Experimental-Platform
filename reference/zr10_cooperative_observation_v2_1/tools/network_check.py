from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
import asyncio
import socket
import subprocess
from pathlib import Path

from siyi_sdk import connect_udp

from zr10_coop.config import load_config


def ping(ip: str) -> bool:
    result = subprocess.run(
        ["ping", "-c", "1", "-W", "1", ip],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def tcp_open(ip: str, port: int, timeout_s: float = 1.0) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout_s)
        return sock.connect_ex((ip, port)) == 0


async def sdk_probe(ip: str, port: int) -> str:
    try:
        async with await connect_udp(ip, port, timeout=1.5, max_retries=0) as client:
            firmware = await client.get_firmware_version()
            attitude = await client.get_gimbal_attitude()
            return (
                f"OK firmware={firmware}; yaw={attitude.yaw_deg:.1f}; "
                f"pitch={attitude.pitch_deg:.1f}"
            )
    except Exception as exc:
        return f"FAILED {type(exc).__name__}: {exc}"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/three_zr10.yaml")
    args = parser.parse_args()
    config = load_config(Path(args.config))

    print("ID          IP                ping   RTSP:8554   SDK:37260")
    print("-" * 88)
    for gimbal in config.enabled_gimbals():
        ping_ok = ping(gimbal.ip)
        rtsp_ok = tcp_open(gimbal.ip, 8554)
        sdk_status = await sdk_probe(gimbal.ip, gimbal.control_port)
        print(
            f"{gimbal.id:<11} {gimbal.ip:<17} "
            f"{str(ping_ok):<6} {str(rtsp_ok):<11} {sdk_status}"
        )


if __name__ == "__main__":
    asyncio.run(main())
