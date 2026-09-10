"""Directly test 0x07 velocity and 0x0E absolute-angle control on each ZR10."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
import asyncio

from siyi_sdk import configure_logging, connect_udp


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ips", nargs="+", default=["192.168.144.25", "192.168.144.26", "192.168.144.27"])
    parser.add_argument("--port", type=int, default=37260)
    parser.add_argument("--mode", choices=["velocity", "position"], default="velocity")
    return parser.parse_args()


async def test_one(ip: str, port: int, mode: str) -> None:
    print(f"\n[{ip}] connecting...")
    async with await connect_udp(ip, port, timeout=2.0, max_retries=1) as client:
        fw = await client.get_firmware_version()
        att0 = await client.get_gimbal_attitude()
        print(f"[{ip}] firmware={fw}")
        print(f"[{ip}] before yaw={att0.yaw_deg:+.1f}, pitch={att0.pitch_deg:+.1f}")

        if mode == "velocity":
            print(f"[{ip}] rotate yaw=+15 for 0.8 s")
            await client.rotate(yaw=15, pitch=0)
            await asyncio.sleep(0.8)
            await client.rotate(yaw=0, pitch=0)
        else:
            target_yaw = max(-120.0, min(120.0, att0.yaw_deg + 10.0))
            target_pitch = att0.pitch_deg
            print(f"[{ip}] set_attitude yaw={target_yaw:+.1f}, pitch={target_pitch:+.1f}")
            ack = await client.set_attitude(target_yaw, target_pitch)
            print(f"[{ip}] ACK yaw={ack.yaw_deg:+.1f}, pitch={ack.pitch_deg:+.1f}")
            await asyncio.sleep(2.0)

        att1 = await client.get_gimbal_attitude()
        print(f"[{ip}] after  yaw={att1.yaw_deg:+.1f}, pitch={att1.pitch_deg:+.1f}")


async def main() -> None:
    args = parse_args()
    # Sequential on purpose: easy to identify the physical device and safer.
    for ip in args.ips:
        try:
            await test_one(ip, args.port, args.mode)
        except Exception as exc:
            print(f"[{ip}] FAILED: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    configure_logging(level="INFO")
    asyncio.run(main())
