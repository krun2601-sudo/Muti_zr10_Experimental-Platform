---
name: siyi-sdk-docs-and-release
description: Writes README, protocol notes, runnable examples, updates CHANGELOG, audits pyproject, and builds the v0.1.0 release artifact — Phase 6.
model: claude-haiku-4-5
---

### Context
**Phase 6.** Implementation (Phases 0–4) and tests/coverage (Phase 5) are complete. Your job: produce user-facing documentation, runnable examples, finalise `pyproject.toml`, update `CHANGELOG.md` to a full `[0.1.0]` entry, and build distribution artifacts.

### Tasks (verbatim from plan §9 Phase 6)

- **TASK-070**: Write `docs/quickstart.md` (UDP + TCP + Serial examples) — AC: every code snippet executes against `MockTransport` in a doctest.
- **TASK-071**: Write `docs/protocol.md` mirroring Appendix A/B/D/E of this plan — AC: link-checker green; all CMD_IDs covered.
- **TASK-072**: Add `examples/udp_heartbeat.py`, `examples/set_attitude.py`, `examples/subscribe_attitude_stream.py`, `examples/thermal_spot_temperature.py`, `examples/laser_ranging.py` — AC: each runs against `MockTransport` under `pytest --collect-only examples/`.
- **TASK-073**: Publish v0.1.0 — tag `v0.1.0`, CHANGELOG updated, GitHub Release + PyPI publish via workflow — AC: `pip install siyi-sdk==0.1.0` succeeds on a clean venv.

### Files to Create

#### `README.md` (full rewrite — expand the scaffolding skeleton)

Required sections:
- **Badges**: PyPI version (`https://img.shields.io/pypi/v/siyi-sdk`), CI status (GitHub Actions badge for `ci.yml`), coverage (codecov placeholder), licence (MIT badge).
- **Description**: one paragraph naming the SIYI Gimbal Camera External SDK Protocol v0.1.1 and the supported products: ZT30, ZT6, ZR10, ZR30, A8 mini, A2 mini, Quad-Spectrum.
- **Installation**:
  ```bash
  pip install siyi-sdk
  # or with uv
  uv pip install siyi-sdk
  ```
- **Quickstart** (real defaults from `siyi_sdk.constants`):
  ```python
  import asyncio
  from siyi_sdk import connect_udp

  async def main() -> None:
      async with await connect_udp("192.168.144.25", 37260) as client:
          fw = await client.get_firmware_version()
          print(f"Camera FW: {fw.camera}, Gimbal FW: {fw.gimbal}, Zoom FW: {fw.zoom}")
          att = await client.get_gimbal_attitude()
          print(f"Yaw={att.yaw_deg:.1f}°  Pitch={att.pitch_deg:.1f}°  Roll={att.roll_deg:.1f}°")

  asyncio.run(main())
  ```
- **Full API reference table**: one row per `SIYIClient` public method. Columns: method name | parameters with types | return type | description. Every method from Phase 4 must appear. Include at minimum:
  - `heartbeat()` / `get_firmware_version()` / `get_hardware_id()` / `get_system_time(...)` / `set_utc_time(...)` / `get_gimbal_system_info()` / `soft_reboot(...)` / `get_ip_config()` / `set_ip_config(...)`
  - `auto_focus(...)` / `manual_zoom(...)` / `manual_focus(...)` / `absolute_zoom(...)` / `get_zoom_range()` / `get_current_zoom()`
  - `rotate(...)` / `one_key_centering(...)` / `set_attitude(...)` / `set_single_axis(...)` / `get_gimbal_mode()`
  - `get_gimbal_attitude()` / `send_aircraft_attitude(...)` / `request_fc_stream(...)` / `request_gimbal_stream(...)` / `get_magnetic_encoder()` / `send_raw_gps(...)` / `on_attitude(cb)` / `on_laser_distance(cb)`
  - `get_camera_system_info()` / `on_function_feedback(cb)` / `capture(...)` / `get_encoding_params(...)` / `set_encoding_params(...)` / `format_sd_card()` / `get_picture_name_type(...)` / `set_picture_name_type(...)` / `get_osd_flag()` / `set_osd_flag(...)`
  - `get_video_stitching_mode()` / `set_video_stitching_mode(...)`
  - All thermal methods (`temp_at_point`, `temp_region`, `temp_global`, pseudo_color, thermal_output_mode, single_temp_frame, thermal_gain, env_correction_params, env_correction_switch, ir_thresh_map_state, ir_thresh_params, ir_thresh_precision, manual_thermal_shutter).
  - `get_laser_distance()` / `get_laser_target_latlon()` / `set_laser_ranging_state(...)`
  - `send_rc_channels(...)` (deprecated note)
  - `get_ai_mode()` / `get_ai_stream_status()` / `set_ai_stream_output(...)` / `on_ai_tracking(cb)`
  - All ArduPilot-only debug methods.
- **Configuration reference**:
  - `SIYI_LOG_LEVEL` — `DEBUG|INFO|WARNING|ERROR`, default `INFO`.
  - `SIYI_PROTOCOL_TRACE=1` — force DEBUG level and attach `payload_hex` hex dumps to every frame log record.
- **Links**: `CONTRIBUTING.md`, `docs/quickstart.md`, `docs/protocol.md`, `CHANGELOG.md`.
- **Licence**: MIT.

#### `docs/quickstart.md`

Three sections: UDP, TCP, Serial. Each contains a full runnable snippet using `MockTransport` via `unittest.mock` or constructing the client directly. Include:
- UDP example identical to README quickstart.
- TCP example using `connect_tcp("192.168.144.25", 37260)`.
- Serial example using `connect_serial("/dev/ttyUSB0", 115200)`.
- Doctests: wrap snippets in `>>>` lines against `MockTransport` so `pytest --doctest-glob="*.md"` validates them.

#### `docs/protocol.md`

Mirror plan Appendices A, B, D, E:
- **§ Frame Structure** — ASCII diagram from Appendix A.
- **§ Command Catalogue** — full table from Appendix B (every CMD_ID row).
- **§ CRC Algorithm** — polynomial, seed, table-driven reference code, all 7 test vectors.
- **§ Timing and Heartbeat** — from Appendix E.
- **§ Known Quirks** — condensed from plan §11.G:
  1. CRC seed 0; no final XOR.
  2. CTRL reserved bits sent as 0; non-zero RX logged WARNING but accepted.
  3. SEQ free-running, wraps.
  4. Firmware version: high byte of each 32-bit word ignored.
  5. Retry: 1 retry on TimeoutError for idempotent reads; none for writes.
  6. Heartbeat: TCP only.
  7. Laser raw 0 → `distance_m=None`.
  8. A2 mini yaw fixed.
  9. Multiple in-flight same CMD_ID serialised via per-CMD_ID lock.
  10. 0x23 RC channels marked "Not in use" — deprecated.
  11. 0x22 float endianness: little-endian (assumed).
  12. Product-specific "No Response" entries → standard 1 s timeout applies.
  13. 0x21 resolution constraints: encoder validates 1920×1080 or 1280×720.
  14. Reserved CMD_IDs: logged WARNING and dropped.

#### Examples (all must `python -m py_compile` cleanly and use real API names)

`examples/udp_heartbeat.py`:
```python
"""Connect to a SIYI gimbal over UDP and read firmware + attitude."""
import asyncio
from siyi_sdk import connect_udp

async def main() -> None:
    async with await connect_udp("192.168.144.25", 37260) as client:
        fw = await client.get_firmware_version()
        print(f"Camera={fw.camera} Gimbal={fw.gimbal} Zoom={fw.zoom}")
        att = await client.get_gimbal_attitude()
        print(f"yaw={att.yaw_deg:.1f} pitch={att.pitch_deg:.1f} roll={att.roll_deg:.1f}")

if __name__ == "__main__":
    asyncio.run(main())
```

`examples/set_attitude.py`:
```python
"""Move the gimbal to yaw=30°, pitch=-45°, return to centre."""
import asyncio
from siyi_sdk import connect_udp

async def main() -> None:
    async with await connect_udp() as client:
        ack = await client.set_attitude(yaw_deg=30.0, pitch_deg=-45.0)
        print(f"moved to yaw={ack.yaw_deg} pitch={ack.pitch_deg}")
        await asyncio.sleep(2)
        await client.one_key_centering()

if __name__ == "__main__":
    asyncio.run(main())
```

`examples/subscribe_attitude_stream.py`:
```python
"""Subscribe to attitude push stream at 10 Hz for 5 seconds."""
import asyncio
from siyi_sdk import connect_udp
from siyi_sdk.models import GimbalDataType, DataStreamFreq

async def main() -> None:
    async with await connect_udp() as client:
        def on_att(att):
            print(f"yaw={att.yaw_deg:.1f} pitch={att.pitch_deg:.1f}")
        unsub = client.on_attitude(on_att)
        await client.request_gimbal_stream(GimbalDataType.ATTITUDE, DataStreamFreq.HZ10)
        await asyncio.sleep(5)
        unsub()
        await client.request_gimbal_stream(GimbalDataType.ATTITUDE, DataStreamFreq.OFF)

if __name__ == "__main__":
    asyncio.run(main())
```

`examples/thermal_spot_temperature.py`:
```python
"""Read spot temperature at pixel (640, 360) on thermal sensor."""
import asyncio
from siyi_sdk import connect_udp
from siyi_sdk.models import TempMeasureFlag

async def main() -> None:
    async with await connect_udp() as client:
        tp = await client.temp_at_point(640, 360, TempMeasureFlag.MEASURE_ONCE)
        print(f"temperature at ({tp.x},{tp.y}) = {tp.temperature_c:.2f}°C")

if __name__ == "__main__":
    asyncio.run(main())
```

`examples/laser_ranging.py`:
```python
"""Enable laser ranging, poll distance for 5 seconds."""
import asyncio
from siyi_sdk import connect_udp

async def main() -> None:
    async with await connect_udp() as client:
        await client.set_laser_ranging_state(True)
        for _ in range(5):
            d = await client.get_laser_distance()
            print("out of range" if d.distance_m is None else f"{d.distance_m:.1f} m")
            await asyncio.sleep(1)
        await client.set_laser_ranging_state(False)

if __name__ == "__main__":
    asyncio.run(main())
```

#### `CHANGELOG.md` — update `[Unreleased]` to `[0.1.0] - <today>`

Populate Added/Changed sections by phase:
- **Added** (grouped by feature area):
  - Scaffolding: `pyproject.toml`, ruff + black + mypy config, hatch envs, pre-commit, CI workflows.
  - Protocol foundation: `constants.py` (all 75+ CMD_IDs, CRC table), `models.py` (all enums and dataclasses), `exceptions.py` (full hierarchy), `protocol/{crc,frame,parser}.py` (CRC-16/XMODEM, streaming state machine).
  - Logging: `logging_config.py` with structlog JSON output, `SIYI_LOG_LEVEL`, `SIYI_PROTOCOL_TRACE` hex dumps.
  - Transports: `AbstractTransport` ABC plus UDP, TCP (with heartbeat), Serial (pyserial-asyncio), Mock.
  - Commands: all encoders/decoders for 0x00–0x82 (system, focus, zoom, gimbal, attitude, camera, video, thermal, laser, rc, debug, ai).
  - High-level API: `SIYIClient` with async method per command, per-CMD_ID lock dispatch, stream subscriptions (`on_attitude`, `on_laser_distance`, `on_function_feedback`, `on_ai_tracking`), optional auto-reconnect, 0xFFFF SEQ wrap.
  - Convenience factories: `connect_udp`, `connect_tcp`, `connect_serial`.
  - Tests: unit + integration + property (hypothesis ≥10 000 examples) + HIL scaffolding + throughput benchmark.
  - Docs: README API reference, `docs/quickstart.md`, `docs/protocol.md`, 5 runnable examples.

#### `pyproject.toml` audit
Verify and fix as needed:
- `name = "siyi-sdk"`.
- `version = "0.1.0"` (bumped from `0.0.0`).
- `description`, `readme = "README.md"`, `requires-python = ">=3.10"`, `license = {text = "MIT"}`.
- `authors = [...]` populated.
- `classifiers`: Development Status :: 4 - Beta (bumped from 3), Framework :: AsyncIO, Intended Audience :: Developers, License :: OSI Approved :: MIT, Operating System :: POSIX :: Linux, Programming Language :: Python :: 3.10/3.11/3.12/3.13, Topic :: Scientific/Engineering, Typing :: Typed.
- Runtime deps pinned exactly as in plan §10 (`structlog>=24.0,<26`, `pyserial-asyncio>=0.6,<1`, `typing-extensions>=4.10`).
- `[project.urls]` Homepage / Repository / Changelog populated.
- If any field is missing or stale, fix it.

### Acceptance Criteria
- `python -m py_compile examples/*.py` succeeds for all 5 examples.
- `pytest --collect-only examples/` collects without error (tests may run against `MockTransport`).
- `python -m build` produces `dist/siyi_sdk-0.1.0-py3-none-any.whl` and `dist/siyi_sdk-0.1.0.tar.gz` without warnings.
- `twine check dist/*` → `PASSED`.
- `README.md` API reference table row count matches the count of public `SIYIClient` methods (verify programmatically or by inspection).
- `CHANGELOG.md` has a populated `[0.1.0]` section dated today.
- `docs/quickstart.md` doctests pass: `pytest --doctest-glob='*.md' docs/`.

### Coding Standards
- Python 3.11+, type annotations on every function and method
- mypy strict — zero errors
- ruff format + ruff check — zero violations
- Google-style docstrings on every public class and function
- 100-character line length
- No bare `except` clauses
- No magic numbers — use siyi_sdk/constants.py for everything
- Every public function must have at least one test

### Logging Requirements
- Obtain logger with: logger = structlog.get_logger(__name__)
- DEBUG: every frame sent and received — include direction (TX/RX),
  cmd_id (hex), seq_num, payload hex dump
- INFO: every command dispatched and acknowledged
- WARNING: retries, unexpected response codes, heartbeat gaps
- ERROR: transport failures, CRC mismatches, NACK responses

After completing all tasks output a DONE REPORT in this exact format:
DONE REPORT — siyi-sdk-docs-and-release
Files created:    list each with line count
Files modified:   list each with a one-line description of change
Tests added:      N (all passing)
Coverage delta:   +X.X%
Decisions made:   any non-obvious choices with justification
