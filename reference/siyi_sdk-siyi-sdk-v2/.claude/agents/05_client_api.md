---
name: siyi-sdk-client-api
description: Implements the high-level SIYIClient async API (one method per command) and convenience factories — Phase 4.
model: claude-sonnet-4-5
---

### Context
**Phase 4.** Phases 0–3 are complete: scaffolding, protocol, transports, and per-command encoders/decoders. You implement `siyi_sdk/client.py` (the `SIYIClient` class) and `siyi_sdk/convenience.py` (UDP/TCP/Serial factory helpers).

The client owns an `AbstractTransport`, runs an async receive loop, routes ACK frames to pending futures by CMD_ID (not SEQ — the protocol does not tag ACKs by SEQ), and dispatches unsolicited stream frames to subscribed callbacks.

### Protocol Reference — Command Summary

CMD_ID | Name | Direction
-------|------|----------
0x00 | TCP Heartbeat | →g (TCP only, 1 Hz, no ACK)
0x01 | Request Firmware Version | →g, ACK
0x02 | Request Hardware ID | →g, ACK
0x04 | Auto Focus | →g, ACK sta
0x05 | Manual Zoom with AF | →g, ACK uint16
0x06 | Manual Focus | →g, ACK sta
0x07 | Gimbal Rotation | →g, ACK sta
0x08 | One-Key Centering | →g, ACK sta
0x0A | Request Camera System Info | →g, ACK
0x0B | Function Feedback | g→ (async push)
0x0C | Capture Photo / Record Video | →g, **no ACK**
0x0D | Request Gimbal Attitude | →g, ACK (also pushed when subscribed)
0x0E | Set Gimbal Attitude | →g, ACK
0x0F | Absolute Zoom AF | →g, ACK
0x10 | Request Video Stitching Mode | →g, ACK
0x11 | Set Video Stitching Mode | →g, ACK
0x12 | Get Temp at Point | →g, ACK
0x13 | Local Temp Measurement | →g, ACK
0x14 | Global Temp Measurement | →g, ACK
0x15 | Request Laser Distance | →g, ACK (also pushed)
0x16 | Request Zoom Range | →g, ACK
0x17 | Request Laser Target Lon/Lat | →g, ACK
0x18 | Request Current Zoom | →g, ACK
0x19 | Request Current Gimbal Mode | →g, ACK
0x1A | Request Pseudo Color | →g, ACK
0x1B | Set Pseudo Color | →g, ACK
0x20 | Request Encoding Params | →g, ACK
0x21 | Set Encoding Params | →g, ACK sta
0x22 | Send Aircraft Attitude | ←fc, **no ACK**
0x23 | Send RC Channels | ←fc, **no ACK** (deprecated)
0x24 | Request FC → Gimbal Stream | →g, ACK
0x25 | Request Gimbal → Stream | →g, ACK (subscribes to 0x0D/0x15/0x26/0x2A pushes)
0x26 | Request Magnetic Encoder | →g, ACK (also pushed)
0x27 | Request Control Mode (ArduPilot) | →g, ACK
0x28 | Request Weak Threshold (AP) | →g, ACK
0x29 | Set Weak Threshold (AP) | →g, ACK sta
0x2A | Request Motor Voltage (AP) | →g, ACK (also pushed)
0x30 | Set UTC Time | →g, ACK
0x31 | Request Gimbal System Info | →g, ACK
0x32 | Set Laser Ranging State | →g, ACK sta
0x33–0x3C | Thermal commands | →g, ACK
0x3E | Send Raw GPS | ←fc, **no ACK** (ZR10/ZR30/A8)
0x40 | Request System Time | →g, ACK
0x41 | Single-Axis Attitude | →g, ACK (A8 responds with 0x0E)
0x42–0x47 | IR Thresh | →g, ACK
0x48 | Format SD | →g, ACK (ZT30/ZR30/A8: no response)
0x49–0x4C | Pic/OSD | →g, ACK
0x4D–0x4F | AI/Shutter | →g, ACK
0x50 | AI Tracking Stream Push | g→ (async push)
0x51 | Set AI Tracking Stream Output | →g, ACK sta
0x70–0x71 | Weak Control Mode | →g, ACK
0x80 | Soft Reboot | →g, ACK
0x81 | Get IP | →g, ACK
0x82 | Set IP | →g, ACK

### Protocol Reference — Timing and Heartbeat (Appendix E)

- Heartbeat (TCP only): CMD_ID `0x00`, literal `55 66 01 01 00 00 00 00 00 59 8B` (use `HEARTBEAT_FRAME` from `siyi_sdk.constants`). Interval 1 s. No ACK expected.
- Request–response: sync — client sends, waits for ACK with matching CMD_ID. Some commands fire-and-forget (0x0C, 0x22, 0x23, 0x3E).
- Streams subscribed via 0x24 / 0x25:
  - 0x25 data_type=1 → 0x0D attitude pushes at freq.
  - 0x25 data_type=2 → 0x15 laser pushes (freq ignored).
  - 0x25 data_type=3 → 0x26 magnetic encoder pushes.
  - 0x25 data_type=4 → 0x2A motor voltage pushes.
  - Freq: 0=off, 1=2 Hz, 2=4 Hz, 3=5 Hz, 4=10 Hz, 5=20 Hz, 6=50 Hz, 7=100 Hz.
- Boot grace: 30 s (firmware returns zeros before ready).
- SDK retry policy (plan §11.G): 1 automatic retry on `TimeoutError` for idempotent reads (`Request*` / `Get*`); write commands raise on first timeout.

### Concurrency and Dispatch Model (plan §4)

- **Async strategy**: asyncio, single reader coroutine.
- **Sequence number**: uint16, free-running, `0xFFFF → 0x0000` wrap; increment per sent frame. Logs use SEQ for correlation but ACKs do NOT carry matching SEQ.
- **Pending registry**: `dict[int (cmd_id), asyncio.Future]`. Per-CMD_ID `asyncio.Lock` to serialise in-flight requests sharing the same CMD_ID. Timeout via `asyncio.wait_for`.
- **Receive loop**: `_reader()` iterates `transport.stream()`, pushes into `FrameParser.feed(chunk)`, and for each parsed `Frame`:
  - If CMD_ID is a stream push (`0x0D, 0x0B, 0x15, 0x26, 0x2A, 0x50`) → dispatch to subscribers in that order of preference.
  - Else if CMD_ID has a pending future → `future.set_result(frame)`.
  - Else → log WARNING `unexpected_frame cmd_id=0x...`; if cmd_id unknown, raise `UnknownCommandError` internally (caught and logged).
- **Heartbeat task**: `_heartbeat()` started only when `transport.supports_heartbeat`; sends `HEARTBEAT_FRAME` every 1 s. Cancelled in `close()`.
- **Reconnection**: optional via `SIYIClient(auto_reconnect=True)`; exponential back-off 0.5, 1, 2, 4, 8 s; max 5 attempts then raise `ConnectionError`. On reconnect, re-issue any active `request_*_stream` subscriptions. Emits `reconnected`/`reconnect_failed` via `asyncio.Event` exposed as `client.connection_event`.

### Tasks (verbatim from plan §9 Phase 4)

- **TASK-050**: Implement `siyi_sdk/client.py` `SIYIClient.__init__`, `connect`, `close`, `__aenter__/__aexit__` — AC: context-manager usage with `MockTransport` opens and closes without leaks.
- **TASK-051**: Implement `_reader()` receive loop and per-CMD_ID pending-future registry with timeouts — AC: two concurrent `get_firmware_version()` calls serialise correctly via per-CMD_ID lock; timeout raises `TimeoutError(cmd_id, timeout_s)`.
- **TASK-052**: Implement `_heartbeat()` task, started only when `transport.supports_heartbeat` — AC: over 3 s with TCP transport, exactly 3 heartbeat frames appear in `MockTransport.sent_frames`; with UDP, 0 appear.
- **TASK-053**: Implement sequence-number incrementer with 0xFFFF wrap — AC: property test — sending 70 000 frames yields 70 000 unique SEQ modulo 65 536.
- **TASK-054**: Wire every `SIYIClient` method listed in §3 to its `commands/*` encoder/decoder — AC: each method has a passing happy-path test in `tests/test_client.py`.
- **TASK-055**: Implement stream-subscription API (`on_attitude`, `on_function_feedback`, `on_laser_distance`, `on_ai_tracking`) with `Unsubscribe` returns — AC: subscribing, receiving 5 pushed frames, then unsubscribing → no further callbacks.
- **TASK-056**: Implement optional auto-reconnect with back-off 0.5/1/2/4/8 s, max 5 attempts — AC: killing the mock transport triggers reconnect; stream subscriptions survive.
- **TASK-057**: Implement `siyi_sdk/convenience.py` factory helpers — AC: `connect_udp()` returns a connected `SIYIClient`.

### Files to Implement

#### `siyi_sdk/client.py`

```python
class SIYIClient:
    def __init__(
        self,
        transport: AbstractTransport,
        *,
        default_timeout: float = 1.0,
        max_retries: int = 1,             # for idempotent reads only
        retry_base_delay: float = 0.1,
        auto_reconnect: bool = False,
        logger: structlog.stdlib.BoundLogger | None = None,
    ) -> None: ...

    async def __aenter__(self) -> "SIYIClient": ...
    async def __aexit__(self, *exc_info: object) -> None: ...
    async def connect(self) -> None: ...
    async def close(self) -> None: ...

    # Internal
    async def _send_command(
        self, cmd_id: int, payload: bytes, *, expect_response: bool = True, timeout: float | None = None
    ) -> bytes: ...          # returns ACK payload bytes; applies retry for idempotent reads
    async def _reader(self) -> None: ...
    async def _heartbeat(self) -> None: ...
    def _next_seq(self) -> int: ...
```

Public API — one async method per protocol command, names exactly as listed in plan §3:

```python
# System (0x00, 0x01, 0x02, 0x40, 0x30, 0x31, 0x80, 0x81, 0x82)
async def heartbeat(self) -> None
async def get_firmware_version(self) -> FirmwareVersion
async def get_hardware_id(self) -> HardwareID
async def get_system_time(self) -> SystemTime
async def set_utc_time(self, unix_usec: int) -> bool
async def get_gimbal_system_info(self) -> GimbalSystemInfo
async def soft_reboot(self, *, camera: bool = False, gimbal: bool = False) -> tuple[bool, bool]
async def get_ip_config(self) -> IPConfig
async def set_ip_config(self, cfg: IPConfig) -> None

# Focus / Zoom (0x04, 0x05, 0x06, 0x0F, 0x16, 0x18)
async def auto_focus(self, touch_x: int, touch_y: int) -> None
async def manual_zoom(self, direction: int) -> float
async def manual_focus(self, direction: int) -> None
async def absolute_zoom(self, zoom: float) -> None
async def get_zoom_range(self) -> ZoomRange
async def get_current_zoom(self) -> float

# Gimbal (0x07, 0x08, 0x0E, 0x19, 0x41)
async def rotate(self, yaw: int, pitch: int) -> None
async def one_key_centering(self, action: CenteringAction = CenteringAction.CENTER) -> None
async def set_attitude(self, yaw_deg: float, pitch_deg: float) -> SetAttitudeAck
async def set_single_axis(self, axis: Literal["yaw","pitch"], angle_deg: float) -> SetAttitudeAck
async def get_gimbal_mode(self) -> GimbalMotionMode

# Attitude / Streams (0x0D, 0x22, 0x24, 0x25, 0x26, 0x3E)
async def get_gimbal_attitude(self) -> GimbalAttitude
async def send_aircraft_attitude(self, att: AircraftAttitude) -> None
async def request_fc_stream(self, data_type: FCDataType, freq: DataStreamFreq) -> None
async def request_gimbal_stream(self, data_type: GimbalDataType, freq: DataStreamFreq) -> None
async def get_magnetic_encoder(self) -> MagneticEncoderAngles
async def send_raw_gps(self, gps: RawGPS) -> None
def on_attitude(self, cb: Callable[[GimbalAttitude], None]) -> Unsubscribe
def on_laser_distance(self, cb: Callable[[LaserDistance], None]) -> Unsubscribe

# Camera (0x0A, 0x0B, 0x0C, 0x20, 0x21, 0x48, 0x49, 0x4A, 0x4B, 0x4C)
async def get_camera_system_info(self) -> CameraSystemInfo
def on_function_feedback(self, cb: Callable[[FunctionFeedback], None]) -> Unsubscribe
async def capture(self, func: CaptureFuncType) -> None
async def get_encoding_params(self, stream: StreamType) -> EncodingParams
async def set_encoding_params(self, params: EncodingParams) -> bool
async def format_sd_card(self) -> bool
async def get_picture_name_type(self, ft: FileType) -> FileNameType
async def set_picture_name_type(self, ft: FileType, nt: FileNameType) -> None
async def get_osd_flag(self) -> bool
async def set_osd_flag(self, on: bool) -> bool

# Video stitching (0x10, 0x11)
async def get_video_stitching_mode(self) -> VideoStitchingMode
async def set_video_stitching_mode(self, mode: VideoStitchingMode) -> VideoStitchingMode

# Thermal (0x12-0x14, 0x1A, 0x1B, 0x33-0x3C, 0x42-0x47, 0x4F)
async def temp_at_point(self, x: int, y: int, flag: TempMeasureFlag) -> TempPoint
async def temp_region(self, region: tuple[int,int,int,int], flag: TempMeasureFlag) -> TempRegion
async def temp_global(self, flag: TempMeasureFlag) -> TempGlobal
async def get_pseudo_color(self) -> PseudoColor
async def set_pseudo_color(self, c: PseudoColor) -> PseudoColor
async def get_thermal_output_mode(self) -> ThermalOutputMode
async def set_thermal_output_mode(self, m: ThermalOutputMode) -> ThermalOutputMode
async def get_single_temp_frame(self) -> bool
async def get_thermal_gain(self) -> ThermalGain
async def set_thermal_gain(self, g: ThermalGain) -> ThermalGain
async def get_env_correction_params(self) -> EnvCorrectionParams
async def set_env_correction_params(self, p: EnvCorrectionParams) -> bool
async def get_env_correction_switch(self) -> bool
async def set_env_correction_switch(self, on: bool) -> bool
async def get_ir_thresh_map_state(self) -> bool
async def set_ir_thresh_map_state(self, on: bool) -> bool
async def get_ir_thresh_params(self) -> IRThreshParams
async def set_ir_thresh_params(self, p: IRThreshParams) -> bool
async def get_ir_thresh_precision(self) -> IRThreshPrecision
async def set_ir_thresh_precision(self, p: IRThreshPrecision) -> IRThreshPrecision
async def manual_thermal_shutter(self) -> bool

# Laser (0x15, 0x17, 0x32)
async def get_laser_distance(self) -> LaserDistance
async def get_laser_target_latlon(self) -> LaserTargetLatLon
async def set_laser_ranging_state(self, on: bool) -> bool

# RC (0x23, 0x24)
async def send_rc_channels(self, ch: RCChannels) -> None   # emits DeprecationWarning

# AI (0x4D, 0x4E, 0x50, 0x51)
async def get_ai_mode(self) -> bool
async def get_ai_stream_status(self) -> AIStreamStatus
async def set_ai_stream_output(self, on: bool) -> bool
def on_ai_tracking(self, cb: Callable[[AITrackingTarget], None]) -> Unsubscribe

# Debug / ArduPilot-only (0x27, 0x28, 0x29, 0x2A, 0x70, 0x71)
async def get_control_mode(self) -> ControlMode
async def get_weak_threshold(self) -> WeakControlThreshold
async def set_weak_threshold(self, t: WeakControlThreshold) -> bool
async def get_motor_voltage(self) -> MotorVoltage
async def get_weak_control_mode(self) -> bool
async def set_weak_control_mode(self, on: bool) -> bool
```

Implementation notes:
- Every method follows the pattern: `payload = commands.<group>.encode_<name>(args...); ack = await self._send_command(CMD_<NAME>, payload); return commands.<group>.decode_<name>_ack(ack)` (or the decoder for read commands).
- `_send_command`:
  - Build `Frame` via `Frame.build(cmd_id, payload, seq=self._next_seq(), need_ack=True)`.
  - Raise `NotConnectedError` if transport not connected.
  - If `expect_response=False`, send and return `b""`.
  - Else register future under `cmd_id`, acquire per-CMD_ID lock, send, `await asyncio.wait_for(fut, timeout)`.
  - Retry once for idempotent reads (`cmd_id` in set of CMD_REQUEST_* / CMD_GET_*) on `TimeoutError`.
  - Log INFO on dispatch, INFO on ACK, ERROR on timeout.
- `_reader`: async for chunk in transport.stream(): parser.feed(chunk) → for each frame: dispatch.
- Stream dispatch list (CMD_IDs routed to callbacks):
  - `0x0D` → `_attitude_callbacks`
  - `0x0B` → `_function_feedback_callbacks`
  - `0x15` → `_laser_callbacks`
  - `0x26` → `_magnetic_encoder_callbacks` (not in public API but receive-and-log)
  - `0x2A` → `_motor_voltage_callbacks` (same)
  - `0x50` → `_ai_tracking_callbacks`
- `on_*` methods register a callback and return an `Unsubscribe` closure that removes it.
- `_heartbeat`: `while True: await asyncio.sleep(1); await transport.send(HEARTBEAT_FRAME); logger.debug("tx heartbeat")`.
- `_next_seq`: `self._seq = (self._seq + 1) & 0xFFFF`.
- `auto_reconnect`: on reader/send exception, enter reconnect loop with delays `[0.5, 1, 2, 4, 8]`; after success, replay subscription table (`self._active_streams: dict[GimbalDataType | FCDataType, DataStreamFreq]`); on exhaustion raise `ConnectionError` and set `self.connection_event` with fail marker.

#### `siyi_sdk/convenience.py`

```python
async def connect_udp(
    ip: str = DEFAULT_IP,
    port: int = DEFAULT_UDP_PORT,
    *,
    timeout: float = 1.0,
    auto_reconnect: bool = False,
) -> SIYIClient: ...

async def connect_tcp(
    ip: str = DEFAULT_IP,
    port: int = DEFAULT_TCP_PORT,
    *,
    timeout: float = 1.0,
    auto_reconnect: bool = False,
) -> SIYIClient: ...

async def connect_serial(
    device: str,
    baud: int = 115200,
    *,
    timeout: float = 1.0,
    auto_reconnect: bool = False,
) -> SIYIClient: ...
```

Each: construct transport, construct `SIYIClient(transport, default_timeout=timeout, auto_reconnect=auto_reconnect)`, `await client.connect()`, return.

### Tests to Write — `tests/test_client.py`

All tests use `MockTransport` (queue ACK bytes, assert `sent_frames`). Use `pytest-asyncio` in `auto` mode.

Required tests:
- **Happy path for every public async method**: queue the appropriate ACK bytes, call the method, assert the decoded return value and that the right request frame was sent (check CMD_ID and payload via `sent_frames`).
- **Context manager**: `async with SIYIClient(mock) as c: ...` — `mock.is_connected` True inside, False after.
- **Timeout**: queue no response, `pytest.raises(TimeoutError) as ei; assert ei.value.cmd_id == CMD_REQUEST_FIRMWARE_VERSION and ei.value.timeout_s == 0.1`.
- **Retry on idempotent read**: first call times out, second succeeds — read method returns correctly; log has one WARNING.
- **No retry on write**: `set_pseudo_color` times out → `TimeoutError` raised immediately, no retry.
- **Concurrent same CMD_ID**: two `asyncio.gather(get_firmware_version(), get_firmware_version())` — both resolve correctly via per-CMD_ID lock; `sent_frames` has 2 entries in order.
- **Concurrent distinct CMD_ID**: `gather(get_firmware_version(), get_gimbal_attitude())` — both resolve concurrently.
- **Sequence wrap**: property test — set `client._seq = 0xFFFE`; call `_next_seq()` 3 times → `[0xFFFF, 0x0000, 0x0001]`.
- **70 000 SEQ uniqueness**: call `_next_seq()` 70 000 times; assert `len(set(s & 0xFFFF for s in results)) == 65536` (all 16-bit values produced).
- **Heartbeat TCP**: `MockTransport(supports_heartbeat=True)`; run 3.1 s → exactly 3 heartbeat frames in `sent_frames`.
- **Heartbeat disabled on UDP**: `MockTransport(supports_heartbeat=False)` → 0 heartbeats.
- **Stream subscription**: `unsub = client.on_attitude(cb)`; queue 5 attitude push frames → callback invoked 5 times; `unsub()`; queue another → not invoked.
- **Unknown CMD_ID**: queue a valid frame with `cmd_id=0x03` → logged at WARNING, reader continues.
- **Auto-reconnect**: simulate transport failure (close then new queued bytes); subscription list replayed; `connection_event` fires.
- **Fire-and-forget commands (0x0C, 0x22, 0x23, 0x3E)**: client does not wait for ACK — verify method returns immediately without timeout even if no ACK queued; `capture()` sends CMD 0x0C frame and returns `None`.

### Tests to Write — `tests/test_convenience.py`

- `connect_udp()` happy-path using a loopback UDP echo server — returns a connected `SIYIClient`.
- `connect_tcp()` against `asyncio.start_server` echo server.
- `connect_serial()` skipped if socat unavailable (mark `@pytest.mark.skipif(not shutil.which("socat"))`).

### Acceptance Criteria
- `pytest tests/test_client.py tests/test_convenience.py -v` → all green.
- `pytest tests/test_client.py tests/test_convenience.py --cov=siyi_sdk/client.py --cov=siyi_sdk/convenience.py --cov-fail-under=90`.
- `hatch run lint:lint` and `hatch run lint:typecheck` exit 0.

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
DONE REPORT — siyi-sdk-client-api
Files created:    list each with line count
Files modified:   list each with a one-line description of change
Tests added:      N (all passing)
Coverage delta:   +X.X%
Decisions made:   any non-obvious choices with justification
