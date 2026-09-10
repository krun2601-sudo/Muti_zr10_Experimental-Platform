# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Attitude feedback + command loop in a single connection.

Demonstrates the correct pattern for closed-loop gimbal control:
- attitude stream runs continuously at 10 Hz
- a control coroutine reads the latest attitude and issues set_attitude commands
Both share one UDP connection so the gimbal always replies to the same port.

Why set_attitude instead of rotate?
  set_attitude (0x0E) sends a target angle; the gimbal's own PID moves to it.
  rotate (0x07) sends a velocity; you have to implement the outer P-loop yourself
  and handle angle wrapping at the ±180° boundary.
"""

import asyncio

from siyi_sdk import configure_logging, connect_udp
from siyi_sdk.exceptions import TimeoutError as SIYITimeoutError
from siyi_sdk.models import DataStreamFreq, GimbalAttitude, GimbalDataType

# Target attitude (degrees) — adjust to a reachable position for your gimbal
TARGET_YAW_DEG = 10.0
TARGET_PITCH_DEG = 0.0

# How close is "close enough" — stop commanding once inside the dead band
DEAD_BAND_DEG = 1.0

# How often the control loop runs (seconds)
CONTROL_HZ = 10
RUN_DURATION = 15.0


def _wrap(angle_deg: float) -> float:
    """Normalise an angle difference to (−180°, +180°]."""
    return ((angle_deg + 180.0) % 360.0) - 180.0


async def main() -> None:
    async with await connect_udp("192.168.144.25", 37260) as client:
        latest: list[GimbalAttitude | None] = [None]

        def on_attitude(att: GimbalAttitude) -> None:
            latest[0] = att
            print(
                f"  stream  yaw={att.yaw_deg:+7.2f}  pitch={att.pitch_deg:+7.2f}",
                flush=True,
            )

        unsub = client.on_attitude(on_attitude)
        await client.request_gimbal_stream(GimbalDataType.ATTITUDE, DataStreamFreq.HZ10)
        print(f"Attitude stream started. Running control loop for {RUN_DURATION} s …\n")

        async def control_loop() -> None:
            deadline = asyncio.get_event_loop().time() + RUN_DURATION
            while asyncio.get_event_loop().time() < deadline:
                att = latest[0]
                if att is not None:
                    # Wrap errors to (−180°, +180°] to avoid flipping at ±180° boundary
                    yaw_err = _wrap(TARGET_YAW_DEG - att.yaw_deg)
                    pitch_err = _wrap(TARGET_PITCH_DEG - att.pitch_deg)

                    if abs(yaw_err) > DEAD_BAND_DEG or abs(pitch_err) > DEAD_BAND_DEG:
                        try:
                            ack = await client.set_attitude(TARGET_YAW_DEG, TARGET_PITCH_DEG)
                            print(
                                f"  cmd     set_attitude → yaw={TARGET_YAW_DEG:+.1f}°  "
                                f"pitch={TARGET_PITCH_DEG:+.1f}°  "
                                f"(err: yaw={yaw_err:+.1f}°  pitch={pitch_err:+.1f}°)  "
                                f"ack: yaw={ack.yaw_deg:+.1f}°  pitch={ack.pitch_deg:+.1f}°",
                                flush=True,
                            )
                        except SIYITimeoutError:
                            print("  cmd     timeout — skipping this cycle", flush=True)
                    else:
                        print(
                            f"  cmd     on-target (err: yaw={yaw_err:+.1f}°  pitch={pitch_err:+.1f}°)",
                            flush=True,
                        )

                await asyncio.sleep(1.0 / CONTROL_HZ)

        await control_loop()

        unsub()
        await client.request_gimbal_stream(GimbalDataType.ATTITUDE, DataStreamFreq.OFF)
        print("\nDone — stream closed.")


if __name__ == "__main__":
    configure_logging(level="INFO")
    asyncio.run(main())
