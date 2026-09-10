"""Clear residual ZR10 motion/stream state before restarting an experiment."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
import asyncio

from siyi_sdk import configure_logging, connect_udp
from siyi_sdk.models import DataStreamFreq, GimbalDataType

from zr10_coop.config import load_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default="config/three_zr10.yaml",
    )
    parser.add_argument(
        "--center",
        action="store_true",
        help="Also execute one-key centering",
    )
    parser.add_argument(
        "--sdk-log-level",
        default="WARNING",
    )
    return parser.parse_args()


async def reliable_stop(client) -> str:
    try:
        await client.rotate(yaw=0, pitch=0)
        return "stop_ack"
    except Exception as exc:
        try:
            await client.rotate_nowait(yaw=0, pitch=0)
            return (
                "stop_nowait_fallback: "
                f"{type(exc).__name__}: {exc}"
            )
        except Exception as fallback_exc:
            raise RuntimeError(
                "both stop methods failed; "
                f"ack={type(exc).__name__}: {exc}; "
                f"nowait={type(fallback_exc).__name__}: "
                f"{fallback_exc}"
            ) from fallback_exc


async def recover_one(
    name: str,
    ip: str,
    port: int,
    center: bool,
) -> tuple[str, bool, str]:
    client = None
    try:
        client = await connect_udp(
            ip,
            port,
            timeout=1.5,
            max_retries=1,
            auto_reconnect=False,
        )
        firmware = await client.get_firmware_version()
        stop_status = await reliable_stop(client)
        try:
            await client.request_gimbal_stream(
                GimbalDataType.ATTITUDE,
                DataStreamFreq.OFF,
            )
            stream_status = "stream_off_ack"
        except Exception as exc:
            stream_status = (
                "stream_off_warning: "
                f"{type(exc).__name__}: {exc}"
            )
        if center:
            await client.one_key_centering()
            await asyncio.sleep(3.0)
        attitude = await client.get_gimbal_attitude()
        message = (
            f"firmware={firmware}; {stop_status}; "
            f"{stream_status}; "
            f"yaw={attitude.yaw_deg:+.1f}, "
            f"pitch={attitude.pitch_deg:+.1f}"
        )
        return name, True, message
    except Exception as exc:
        return (
            name,
            False,
            f"{type(exc).__name__}: {exc}",
        )
    finally:
        if client is not None:
            try:
                await client.close()
            except Exception:
                pass


async def async_main() -> int:
    args = parse_args()
    configure_logging(level=args.sdk_log_level)
    config = load_config(
        Path(args.config).expanduser().resolve()
    )
    results = []
    for gimbal in config.enabled_gimbals():
        result = await recover_one(
            gimbal.id,
            gimbal.ip,
            gimbal.control_port,
            args.center,
        )
        results.append(result)
        await asyncio.sleep(
            config.system.connect_stagger_s
        )

    ok = True
    for name, success, message in results:
        print(
            f"[{name}] "
            f"{'OK' if success else 'FAILED'}: "
            f"{message}"
        )
        ok = ok and success
    return 0 if ok else 1


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
