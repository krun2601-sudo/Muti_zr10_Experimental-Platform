"""Sequential hardware diagnostic for control ACK, feedback, and axis motion."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
import asyncio
import math

from siyi_sdk import configure_logging, connect_udp

from zr10_coop.angle_utils import normalize_zr10_pitch
from zr10_coop.config import load_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/three_zr10.yaml")
    parser.add_argument("--speed", type=int, default=15)
    parser.add_argument("--pulse", type=float, default=0.6)
    parser.add_argument("--sdk-log-level", default="WARNING")
    return parser.parse_args()


async def read_attitude(client):
    att = await client.get_gimbal_attitude()
    return (
        float(att.yaw_deg),
        normalize_zr10_pitch(float(att.pitch_deg)),
    )


async def stop(client) -> None:
    try:
        await client.rotate(yaw=0, pitch=0)
    except Exception:
        await client.rotate_nowait(yaw=0, pitch=0)


async def test_axis(client, *, yaw: int, pitch: int, pulse_s: float):
    before = await read_attitude(client)
    await client.rotate(yaw=yaw, pitch=pitch)
    await asyncio.sleep(pulse_s)
    await stop(client)
    await asyncio.sleep(0.35)
    after = await read_attitude(client)
    return before, after


async def test_one(gimbal, speed: int, pulse_s: float):
    print(f"\n[{gimbal.id}] {gimbal.ip} connecting...", flush=True)
    async with await connect_udp(
        gimbal.ip,
        gimbal.control_port,
        timeout=gimbal.command_timeout_s,
        max_retries=gimbal.max_retries,
    ) as client:
        fw = await client.get_firmware_version()
        await stop(client)
        base = await read_attitude(client)
        print(
            f"  firmware={fw}\n"
            f"  initial yaw={base[0]:+.2f}, pitch={base[1]:+.2f}",
            flush=True,
        )

        yaw_before, yaw_after = await test_axis(
            client,
            yaw=speed,
            pitch=0,
            pulse_s=pulse_s,
        )
        yaw_delta = (
            (yaw_after[0] - yaw_before[0] + 180.0) % 360.0
        ) - 180.0
        print(
            f"  +yaw test: before={yaw_before[0]:+.2f}, "
            f"after={yaw_after[0]:+.2f}, delta={yaw_delta:+.2f}",
            flush=True,
        )

        # Move approximately back toward the starting direction.
        await client.rotate(yaw=-speed, pitch=0)
        await asyncio.sleep(pulse_s)
        await stop(client)
        await asyncio.sleep(0.35)

        pitch_before, pitch_after = await test_axis(
            client,
            yaw=0,
            pitch=-speed,
            pulse_s=pulse_s,
        )
        pitch_delta = pitch_after[1] - pitch_before[1]
        print(
            f"  -pitch test: before={pitch_before[1]:+.2f}, "
            f"after={pitch_after[1]:+.2f}, delta={pitch_delta:+.2f}",
            flush=True,
        )

        moved_yaw = abs(yaw_delta) >= 0.5
        moved_pitch = abs(pitch_delta) >= 0.5
        print(
            f"  RESULT: yaw_motion={moved_yaw}, "
            f"pitch_motion={moved_pitch}",
            flush=True,
        )
        return moved_yaw and moved_pitch


async def async_main() -> int:
    args = parse_args()
    if not 1 <= abs(args.speed) <= 40:
        raise ValueError("--speed should be in [1, 40] for this diagnostic")
    if not 0.2 <= args.pulse <= 1.5:
        raise ValueError("--pulse should be in [0.2, 1.5] seconds")

    configure_logging(level=args.sdk_log_level)
    config = load_config(Path(args.config).expanduser().resolve())
    overall = True
    for gimbal in config.enabled_gimbals():
        try:
            ok = await test_one(gimbal, abs(args.speed), args.pulse)
        except Exception as exc:
            ok = False
            print(
                f"[{gimbal.id}] FAILED: {type(exc).__name__}: {exc}",
                flush=True,
            )
        overall = overall and ok
        await asyncio.sleep(config.system.connect_stagger_s)
    return 0 if overall else 1


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
