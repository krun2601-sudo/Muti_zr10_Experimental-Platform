---
name: siyi-sdk-protocol-layer
description: Implements the SIYI binary protocol foundation — constants, models, exceptions, CRC16/XMODEM, Frame, and streaming FrameParser — Phase 1.
model: claude-opus-4-5
---

### Context
**Phase 1.** Scaffolding (Phase 0) is complete: `pyproject.toml`, CI, empty package tree, and `siyi_sdk/logging_config.py` exist. You now implement the protocol foundation — the lowest layer every other module depends on. No transport code, no command encoders, no client. Only: `constants.py`, `models.py`, `exceptions.py`, `protocol/crc.py`, `protocol/frame.py`, `protocol/parser.py`, plus their unit and property tests.

### Protocol Reference — Frame Structure (Appendix A)

```
Offset  Bytes  Field     Type     Endianness  Valid values
------  -----  --------  -------  ----------  -----------------------------------
0       2      STX       uint16   LE          0x6655 (wire bytes: 0x55 0x66)
2       1      CTRL      uint8    -           bit0=need_ack, bit1=ack_pack, 2..7 reserved
3       2      Data_len  uint16   LE          0 .. 65 535 (payload length in bytes)
5       2      SEQ       uint16   LE          0 .. 65 535 (wraps)
7       1      CMD_ID    uint8    -           see §B
8       N      DATA      bytes    -           N = Data_len
8+N     2      CRC16     uint16   LE          CRC-16/XMODEM over bytes 0 .. 7+N
```
Minimum frame length: 10 bytes (empty payload). CTRL=0 means "request requiring ACK"; CTRL=1 means "this is the ACK". Bits 2–7 reserved, must be 0.

Header layout constants:
- `STX = 0x6655` (on wire little-endian: `0x55 0x66`).
- `HEADER_LEN = 8` (STX:2, CTRL:1, Data_len:2, SEQ:2, CMD_ID:1).
- `CRC_LEN = 2`.
- `MIN_FRAME_LEN = 10`.
- `CTRL_NEED_ACK = 0`, `CTRL_ACK_PACK = 1`.

### Protocol Reference — CRC Algorithm (Appendix D)

Algorithm: **CRC-16/XMODEM** — polynomial `X¹⁶+X¹²+X⁵+1 = 0x1021`, initial value `0x0000`, no reflect-in, no reflect-out, no final XOR. Table-driven (256-entry `crc16_tab`) per spec Chapter 4.

Reference implementation:
```python
def crc16(buf: bytes) -> int:
    crc = 0
    for b in buf:
        temp = (crc >> 8) & 0xFF
        crc = ((crc << 8) & 0xFFFF) ^ CRC16_TABLE[b ^ temp]
    return crc
```
Seed `0x0000`. No final XOR. Output appended little-endian to the frame.

**Ambiguity resolutions applied (from plan §11.G):**
- CRC initial value is `0x0000`. The spec's `crc_check_16bites` calls with seed 0; honour that. Expose `init` only as an optional param on the low-level helper for testability.
- No final XOR (spec has `crc = ~crc;` commented out — matches XMODEM and the Chapter-4 test vectors).

**`CRC16_TABLE`**: The 256-entry lookup table must be transcribed **verbatim** from Chapter 4 of `SIYI_SDK_PROTOCOL.pdf` into `siyi_sdk/constants.py` as `CRC16_TABLE: Final[tuple[int, ...]]`. Read the PDF to extract the exact hex values — this is non-negotiable. Do not generate the table from the polynomial in code; use the literal table to match the spec byte-for-byte, and validate against it with a bit-by-bit reference in tests.

**Test vectors (input = frame bytes 0..7+N-1, i.e. everything except the CRC; output little-endian):**

| # | Description | Input hex | CRC | Wire bytes |
|---|-------------|-----------|-----|------------|
| 1 | Request fw version | `55 66 01 00 00 00 00 00 01` | `0xC464` | `64 C4` |
| 2 | Request hardware ID | `55 66 01 00 00 00 00 00 02` | `0xF407` | `07 F4` |
| 3 | Manual zoom +1 | `55 66 01 01 00 00 00 00 05 01` | `0x648D` | `8D 64` |
| 4 | Take photo | `55 66 01 01 00 00 00 00 0C 00` | `0xCE34` | `34 CE` |
| 5 | TCP heartbeat | `55 66 01 01 00 00 00 00 00` | `0x8B59` | `59 8B` |
| 6 | Pan/Tilt 100,100 | `55 66 01 02 00 00 00 00 07 64 64` | `0xCF3D` | `3D CF` |
| 7 | One-key centering | `55 66 01 01 00 00 00 00 08 01` | `0x12D1` | `D1 12` |

Also required: `crc16(b"") == 0x0000`.

### Protocol Reference — Enumerations and Data Types (Appendix C → models.py)

Enumerations (all `IntEnum`, member values verbatim):
- `ProductID`: `ZR10=0x6B, A8_MINI=0x73, A2_MINI=0x75, ZR30=0x78, QUAD_SPECTRUM=0x7A`.
- `GimbalMotionMode`: `LOCK=0, FOLLOW=1, FPV=2`.
- `MountingDirection`: `RESERVED=0, NORMAL=1, INVERTED=2`.
- `HDMICVBSOutput`: `HDMI_ON_CVBS_OFF=0, HDMI_OFF_CVBS_ON=1`.
- `RecordingState`: `NOT_RECORDING=0, RECORDING=1, NO_TF_CARD=2, DATA_LOSS=3`.
- `FunctionFeedback`: `PHOTO_OK=0, PHOTO_FAILED=1, HDR_ON=2, HDR_OFF=3, RECORDING_FAILED=4, RECORDING_STARTED=5, RECORDING_STOPPED=6`.
- `CaptureFuncType`: `PHOTO=0, HDR_TOGGLE=1, START_RECORD=2, LOCK_MODE=3, FOLLOW_MODE=4, FPV_MODE=5, ENABLE_HDMI=6, ENABLE_CVBS=7, DISABLE_HDMI_CVBS=8, TILT_DOWNWARD=9, ZOOM_LINKAGE=10`.
- `CenteringAction`: `ONE_KEY_CENTER=1, CENTER_DOWNWARD=2, CENTER=3, DOWNWARD=4`.
- `VideoEncType`: `H264=1, H265=2`.
- `StreamType`: `RECORDING=0, MAIN=1, SUB=2`.
- `VideoStitchingMode`: 9 members `MODE_0..MODE_8` (per 0x10/0x11).
- `PseudoColor`: `WHITE_HOT=0, RESERVED=1, SEPIA=2, IRONBOW=3, RAINBOW=4, NIGHT=5, AURORA=6, RED_HOT=7, JUNGLE=8, MEDICAL=9, BLACK_HOT=10, GLORY_HOT=11`.
- `TempMeasureFlag`: `DISABLE=0, MEASURE_ONCE=1, CONTINUOUS_5HZ=2`.
- `ThermalOutputMode`: `FPS30=0, FPS25_PLUS_TEMP=1`.
- `ThermalGain`: `LOW=0, HIGH=1`.
- `IRThreshPrecision`: `MAX=1, MID=2, MIN=3`.
- `FCDataType`: `ATTITUDE=1, RC_CHANNELS=2`.
- `GimbalDataType`: `ATTITUDE=1, LASER_RANGE=2, MAGNETIC_ENCODER=3, MOTOR_VOLTAGE=4`.
- `DataStreamFreq`: `OFF=0, HZ2=1, HZ4=2, HZ5=3, HZ10=4, HZ20=5, HZ50=6, HZ100=7`.
- `ControlMode`: `ATTITUDE=0, WEAK=1, MIDDLE=2, FPV=3, MOTOR_CLOSE=4`.
- `AITargetID`: `HUMAN=0, CAR=1, BUS=2, TRUCK=3, ANY=255`.
- `AITrackStatus`: `NORMAL_AI=0, INTERMITTENT_LOSS=1, LOST=2, USER_CANCELED=3, NORMAL_ANY=4`.
- `AIStreamStatus`: `DISABLED=0, STREAMING=1, AI_NOT_ENABLED=2, TRACKING_NOT_ENABLED=3`.
- `FileType`: `PICTURE=0, TEMP_RAW=1, RECORD_VIDEO=2`.
- `FileNameType`: `RESERVE=0, INDEX=1, TIMESTAMP=2`.

Dataclasses (all `frozen=True, slots=True`):
- `FirmwareVersion(camera: int, gimbal: int, zoom: int)` + classmethod/helper `decode_word(word: int) -> tuple[int, int, int]` (split low 3 bytes of a `uint32` into `(major, minor, patch)`, discarding the high byte per spec §0x01 note).
- `HardwareID(raw: bytes)` with property `product_id -> ProductID` (first byte of `raw`).
- `CameraSystemInfo(reserved_a: int, hdr_sta: int, reserved_b: int, record_sta: RecordingState, gimbal_motion_mode: GimbalMotionMode, gimbal_mounting_dir: MountingDirection, video_hdmi_or_cvbs: HDMICVBSOutput, zoom_linkage: int)` — 8 fields per §0x0A.
- `GimbalAttitude(yaw_deg: float, pitch_deg: float, roll_deg: float, yaw_rate_dps: float, pitch_rate_dps: float, roll_rate_dps: float)` — raw int16 ÷10 applied by decoder.
- `SetAttitudeAck(yaw_deg: float, pitch_deg: float, roll_deg: float)`.
- `AircraftAttitude(time_boot_ms: int, roll_rad: float, pitch_rad: float, yaw_rad: float, rollspeed: float, pitchspeed: float, yawspeed: float)`.
- `RCChannels(chans: tuple[int, ...], chancount: int, rssi: int)` — 18 channels.
- `EncodingParams(stream_type: StreamType, enc_type: VideoEncType, resolution_w: int, resolution_h: int, bitrate_kbps: int, frame_rate: int)`.
- `TempPoint(x: int, y: int, temperature_c: float)`.
- `TempRegion(startx: int, starty: int, endx: int, endy: int, max_c: float, min_c: float, max_x: int, max_y: int, min_x: int, min_y: int)` — 10-field.
- `TempGlobal(max_c: float, min_c: float, max_x: int, max_y: int, min_x: int, min_y: int)` — 6-field.
- `EnvCorrectionParams(distance_m: float, emissivity_pct: float, humidity_pct: float, ambient_c: float, reflective_c: float)` — all raw uint16 ÷100.
- `LaserDistance(distance_m: float | None)` — raw decimetres ÷10, `None` if raw<50 or ==0.
- `LaserTargetLatLon(lat_e7: int, lon_e7: int)`.
- `ZoomRange(max_int: int, max_float: int)` with `.max_zoom -> float` property = `max_int + max_float/10`.
- `CurrentZoom(integer: int, decimal: int)` with `.zoom -> float` property.
- `RawGPS(time_boot_ms: int, lat_e7: int, lon_e7: int, alt_msl_cm: int, alt_ellipsoid_cm: int, vn_mmps: int, ve_mmps: int, vd_mmps: int)`.
- `MagneticEncoderAngles(yaw: float, pitch: float, roll: float)` — /10.
- `MotorVoltage(yaw: float, pitch: float, roll: float)` — /1000 V.
- `WeakControlThreshold(limit: float, voltage: float, angular_error: float)` — limit 10..50/10, voltage 20..50/10, ang_err 30..300/10.
- `SystemTime(unix_usec: int, boot_ms: int)`.
- `GimbalSystemInfo(laser_state: bool)`.
- `IRThreshParams(...)` — 3 regions × (switch + int16[2] temp range + uint8[3] colour).
- `AITrackingTarget(x: int, y: int, w: int, h: int, target_id: AITargetID, status: AITrackStatus)`.
- `IPConfig(ip: IPv4Address, mask: IPv4Address, gateway: IPv4Address)`.
- `AngleLimits(yaw_min: float, yaw_max: float, pitch_min: float, pitch_max: float)` + per-product table `ANGLE_LIMITS: dict[ProductID, AngleLimits]`:
  - A8_MINI, ZR10: yaw ±135°, pitch -90..+25°.
  - ZR30: yaw ±270°, pitch -90..+25°.
  - A2_MINI: yaw fixed (0..0), pitch -90..+25°.
  - QUAD_SPECTRUM: unlimited yaw (use ±360°), pitch -90..+25°.
- `PicName` alias of `FileNameType`.

### Protocol Reference — Error Codes (Appendix F)

The spec does not define a NACK frame or error-code enumeration. Error signalling is limited to a per-command `sta` or `ack` byte in the ACK payload. Observed "failure" values:
- `0` in `sta`/`ack` for: 0x04, 0x06, 0x07, 0x08, 0x21, 0x29, 0x30 (`0` = invalid time format), 0x32, 0x3A, 0x45, 0x48, 0x71, 0x82.
- `0` in `record_sta` (0x0A) can indicate "Not recording" (normal) — not an error. Values: 2=No TF, 3=Data loss → WARNING.
- Laser distance raw `0` → out of range, not an error.

### Exception Hierarchy (plan §5)

```
SIYIError (base)
├── ProtocolError
│   ├── FramingError                          # parser.py on bad STX / truncation
│   ├── CRCError(expected: int, actual: int, frame_hex: str)
│   ├── UnknownCommandError(cmd_id: int)
│   └── MalformedPayloadError(cmd_id: int, reason: str)
├── TransportError
│   ├── ConnectionError
│   ├── TimeoutError(cmd_id: int, timeout_s: float)
│   ├── SendError
│   └── NotConnectedError
├── CommandError
│   ├── NACKError(cmd_id: int, error_code: int, message: str)
│   ├── ResponseError(cmd_id: int, sta: int)
│   └── UnsupportedByProductError(cmd_id: int, product: ProductID)
└── ConfigurationError
```

Each exception is a `@dataclass` so `repr()` shows fields. Every exception defines `__str__` that renders its carried context clearly. Example: `CRCError.__str__` → `"CRC mismatch: expected=0x1234 actual=0x5678 frame=55 66 01 ..."`.

### Tasks (verbatim from plan §9 Phase 1)

- **TASK-010**: Implement `siyi_sdk/constants.py` with every CMD_ID, STX, CTRL flags, endpoint defaults, CRC poly/init, hardware IDs, angle limits, and the 256-entry `CRC16_TABLE` literal from Chapter 4 — AC: mypy strict passes, no magic hex literals appear in any other module (enforced by a ruff custom rule or grep test).
- **TASK-011**: Implement `siyi_sdk/models.py` with all enumerations and dataclasses listed in §3 — AC: every enum member matches the spec integer; `pytest tests/test_models.py` green.
- **TASK-012**: Implement `siyi_sdk/exceptions.py` exception hierarchy per §5 — AC: `isinstance(CRCError(0,1,"55"), ProtocolError)` and `SIYIError`; tests green.
- **TASK-013**: Implement `siyi_sdk/protocol/crc.py` with `crc16()` per spec algorithm — AC: all 7 fixture vectors from §Appendix D match, `crc16(b"")==0`.
- **TASK-014**: Implement `siyi_sdk/protocol/frame.py` with `Frame.to_bytes/from_bytes/build` — AC: Chapter-4 examples (zoom+1, take-photo, heartbeat, pan-tilt, one-key-centering, firmware-req, hw-id-req) round-trip byte-exactly.
- **TASK-015**: Implement `siyi_sdk/protocol/parser.py` streaming state machine — AC: feeding any Chapter-4 example in 1-byte chunks yields exactly one `Frame`; injecting one bad byte mid-frame yields `CRCError` and resync.
- **TASK-016**: Add hypothesis tests in `tests/property/test_frame_roundtrip.py` and `test_parser_fuzz.py` — AC: 1000+ examples each pass; parser never throws on arbitrary bytes (only returns `[]` or raises documented errors).
- **TASK-017**: Implement `siyi_sdk/logging_config.py` with `configure_logging()` and hex-dump processor — AC: with `SIYI_PROTOCOL_TRACE=1` a TX frame log contains `payload_hex`; without it, does not. (**Note**: scaffolding agent already created the file — review it, augment if anything in §6 is missing.)

### Files to Implement

#### `siyi_sdk/constants.py`
All values as `Final[...]` from `typing`. Include:
- `STX: Final[int] = 0x6655`; `STX_BYTES: Final[bytes] = b"\x55\x66"`.
- `CTRL_NEED_ACK: Final[int] = 0`; `CTRL_ACK_PACK: Final[int] = 1`.
- `HEADER_LEN: Final[int] = 8`; `CRC_LEN: Final[int] = 2`; `MIN_FRAME_LEN: Final[int] = 10`.
- `SEQ_MAX: Final[int] = 0xFFFF`.
- `CRC16_POLY: Final[int] = 0x1021`; `CRC16_INIT: Final[int] = 0x0000`.
- Default endpoints: `DEFAULT_IP: Final[str] = "192.168.144.25"`, `DEFAULT_UDP_PORT: Final[int] = 37260`, `DEFAULT_TCP_PORT: Final[int] = 37260`, `DEFAULT_BAUD: Final[int] = 115200`.
- `HEARTBEAT_FRAME: Final[bytes] = bytes.fromhex("556601010000000000598B")`.
- `CAMERA_BOOT_SECONDS: Final[int] = 30`.
- `LASER_MIN_M: Final[int] = 5`, `LASER_MAX_M: Final[int] = 1200`, `LASER_MIN_RAW_DM: Final[int] = 50`.
- Every CMD_ID constant (names exactly as listed in plan §3, values from Appendix B):
  `CMD_TCP_HEARTBEAT=0x00, CMD_REQUEST_FIRMWARE_VERSION=0x01, CMD_REQUEST_HARDWARE_ID=0x02, CMD_AUTO_FOCUS=0x04, CMD_MANUAL_ZOOM_AUTO_FOCUS=0x05, CMD_MANUAL_FOCUS=0x06, CMD_GIMBAL_ROTATION=0x07, CMD_ONE_KEY_CENTERING=0x08, CMD_REQUEST_CAMERA_SYSTEM_INFO=0x0A, CMD_FUNCTION_FEEDBACK=0x0B, CMD_CAPTURE_PHOTO_RECORD_VIDEO=0x0C, CMD_REQUEST_GIMBAL_ATTITUDE=0x0D, CMD_SET_GIMBAL_ATTITUDE=0x0E, CMD_ABSOLUTE_ZOOM_AUTO_FOCUS=0x0F, CMD_REQUEST_VIDEO_STITCHING_MODE=0x10, CMD_SET_VIDEO_STITCHING_MODE=0x11, CMD_GET_TEMP_AT_POINT=0x12, CMD_LOCAL_TEMP_MEASUREMENT=0x13, CMD_GLOBAL_TEMP_MEASUREMENT=0x14, CMD_REQUEST_LASER_DISTANCE=0x15, CMD_REQUEST_ZOOM_RANGE=0x16, CMD_REQUEST_LASER_LATLON=0x17, CMD_REQUEST_ZOOM_MAGNIFICATION=0x18, CMD_REQUEST_GIMBAL_MODE=0x19, CMD_REQUEST_PSEUDO_COLOR=0x1A, CMD_SET_PSEUDO_COLOR=0x1B, CMD_REQUEST_ENCODING_PARAMS=0x20, CMD_SET_ENCODING_PARAMS=0x21, CMD_SEND_AIRCRAFT_ATTITUDE=0x22, CMD_SEND_RC_CHANNELS=0x23, CMD_REQUEST_FC_DATA_STREAM=0x24, CMD_REQUEST_GIMBAL_DATA_STREAM=0x25, CMD_REQUEST_MAGNETIC_ENCODER=0x26, CMD_REQUEST_CONTROL_MODE=0x27, CMD_REQUEST_WEAK_THRESHOLD=0x28, CMD_SET_WEAK_THRESHOLD=0x29, CMD_REQUEST_MOTOR_VOLTAGE=0x2A, CMD_SET_UTC_TIME=0x30, CMD_REQUEST_GIMBAL_SYSTEM_INFO=0x31, CMD_SET_LASER_RANGING_STATE=0x32, CMD_REQUEST_THERMAL_OUTPUT_MODE=0x33, CMD_SET_THERMAL_OUTPUT_MODE=0x34, CMD_GET_SINGLE_TEMP_FRAME=0x35, CMD_REQUEST_THERMAL_GAIN=0x37, CMD_SET_THERMAL_GAIN=0x38, CMD_REQUEST_ENV_CORRECTION_PARAMS=0x39, CMD_SET_ENV_CORRECTION_PARAMS=0x3A, CMD_REQUEST_ENV_CORRECTION_SWITCH=0x3B, CMD_SET_ENV_CORRECTION_SWITCH=0x3C, CMD_SEND_RAW_GPS=0x3E, CMD_REQUEST_SYSTEM_TIME=0x40, CMD_SINGLE_AXIS_ATTITUDE=0x41, CMD_GET_IR_THRESH_MAP_STA=0x42, CMD_SET_IR_THRESH_MAP_STA=0x43, CMD_GET_IR_THRESH_PARAM=0x44, CMD_SET_IR_THRESH_PARAM=0x45, CMD_GET_IR_THRESH_PRECISION=0x46, CMD_SET_IR_THRESH_PRECISION=0x47, CMD_SD_FORMAT=0x48, CMD_GET_PIC_NAME_TYPE=0x49, CMD_SET_PIC_NAME_TYPE=0x4A, CMD_GET_MAVLINK_OSD_FLAG=0x4B, CMD_SET_MAVLINK_OSD_FLAG=0x4C, CMD_GET_AI_MODE_STA=0x4D, CMD_GET_AI_TRACK_STREAM_STA=0x4E, CMD_MANUAL_THERMAL_SHUTTER=0x4F, CMD_AI_TRACK_STREAM=0x50, CMD_SET_AI_TRACK_STREAM_STA=0x51, CMD_REQUEST_WEAK_CONTROL_MODE=0x70, CMD_SET_WEAK_CONTROL_MODE=0x71, CMD_SOFT_REBOOT=0x80, CMD_GET_IP=0x81, CMD_SET_IP=0x82`.
- Hardware-ID first-byte product codes: `HW_ID_ZR10=0x6B, HW_ID_A8_MINI=0x73, HW_ID_A2_MINI=0x75, HW_ID_ZR30=0x78, HW_ID_QUAD_SPECTRUM=0x7A`.
- `CRC16_TABLE: Final[tuple[int, ...]]` — 256 entries transcribed from `SIYI_SDK_PROTOCOL.pdf` Chapter 4. Add a compile-time assertion: `assert len(CRC16_TABLE) == 256`.

#### `siyi_sdk/models.py`
All enumerations and dataclasses listed above. Imports: `enum.IntEnum`, `dataclasses.dataclass`, `ipaddress.IPv4Address`, `typing.Final`, `.constants.ProductID` is defined here (not in constants).

#### `siyi_sdk/exceptions.py`
Full hierarchy above. Each exception is a `@dataclass` subclass of the parent exception class. Example skeleton for `CRCError`:
```python
@dataclass
class CRCError(ProtocolError):
    expected: int
    actual: int
    frame_hex: str
    def __str__(self) -> str:
        return f"CRC mismatch: expected=0x{self.expected:04X} actual=0x{self.actual:04X} frame={self.frame_hex}"
```
Apply this pattern to every leaf exception carrying data.

#### `siyi_sdk/protocol/crc.py`
```python
from typing import Final
from ..constants import CRC16_INIT, CRC16_TABLE

def crc16(buf: bytes, init: int = CRC16_INIT) -> int: ...
def crc16_check(frame_without_crc: bytes, crc_le: bytes) -> bool: ...
```
- `crc16` implements the algorithm above.
- `crc16_check` computes `crc16(frame_without_crc)` and compares against `int.from_bytes(crc_le, "little")`.
- No logging in this module (pure function).

#### `siyi_sdk/protocol/frame.py`
```python
@dataclass(frozen=True, slots=True)
class Frame:
    ctrl: int
    seq: int
    cmd_id: int
    data: bytes

    @property
    def data_len(self) -> int: ...          # == len(self.data)
    def to_bytes(self) -> bytes: ...
    @classmethod
    def from_bytes(cls, buf: bytes) -> "Frame": ...
    @classmethod
    def build(cls, cmd_id: int, data: bytes, seq: int, *, need_ack: bool = False) -> "Frame": ...
```
- `to_bytes`: pack STX (`b"\x55\x66"`) + `ctrl` + `data_len` (LE u16) + `seq` (LE u16) + `cmd_id` + `data` + CRC (LE u16).
- `from_bytes`: validate STX, header length, `data_len`, CRC. Raise `FramingError` on bad STX/truncated; `CRCError` on CRC mismatch.
- `build`: factory setting `ctrl = CTRL_NEED_ACK if not need_ack else CTRL_NEED_ACK | 0b01` (bit0=need_ack per Appendix A). Actually: if `need_ack=False`, set `ctrl = CTRL_ACK_PACK` semantics? Read the spec carefully — `CTRL_NEED_ACK = 0` literal is the value used in most Chapter-4 request examples (ctrl byte = `0x01` in heartbeat/zoom examples, which is "ack_pack"). Match Chapter-4 fixtures: in example "Manual zoom +1" the CTRL byte is `0x01`. Therefore treat `ctrl=0x01` as the default for client-sent requests; document clearly in docstring.
- Imports: `..constants`, `..exceptions`, `.crc`.

#### `siyi_sdk/protocol/parser.py`
Streaming state machine with explicit states: `AWAIT_STX1`, `AWAIT_STX2`, `READ_CTRL`, `READ_DATA_LEN_LO`, `READ_DATA_LEN_HI`, `READ_SEQ_LO`, `READ_SEQ_HI`, `READ_CMD_ID`, `READ_DATA`, `READ_CRC_LO`, `READ_CRC_HI`, `VERIFY_CRC`.

```python
class FrameParser:
    def __init__(self, max_payload: int = 4096) -> None: ...
    def feed(self, chunk: bytes) -> list[Frame]: ...
    def reset(self) -> None: ...
```
- `feed` is non-blocking; maintains internal byte buffer; returns all complete frames parsed from the concatenation of prior residue + `chunk`.
- `data_len > max_payload` → raise `FramingError` and resync on next `0x55`.
- CRC failure → raise `CRCError`, then resync (drop bad frame's first byte, search for next STX).
- Corrupt magic bytes → silently resync (don't raise — common on cold-start streams).
- **Never** throws on partial input.
- Obtain logger `logger = structlog.get_logger(__name__)`. Log:
  - DEBUG on each complete frame parsed (direction `rx`, cmd_id, seq, payload_len, bind `payload_bytes=data`).
  - WARNING on resync after bad STX.
  - ERROR on `FramingError` and `CRCError` before re-raise.

### Tests to Write

#### `tests/test_constants.py`
- Every CMD_ID has a unique value (use `len(set(...)) == len(list(...))`).
- `CRC16_TABLE` has exactly 256 entries; every entry `0 <= v <= 0xFFFF`.
- `HEARTBEAT_FRAME` parses (compute CRC of all but last 2 bytes, compare).
- No magic hex literals outside `constants.py`: a test that greps `siyi_sdk/**/*.py` excluding `constants.py` for `0x[0-9A-Fa-f]{2,}` and asserts matches only appear in docstrings/comments (use `ast` to avoid false positives). Implement as a pragmatic check with an allowlist.

#### `tests/test_models.py`
- `ProductID(0x6B).name == "ZR10"` etc. for every enum member.
- Every dataclass has `__slots__` and is frozen.
- `AngleLimits` table has an entry per `ProductID`.

#### `tests/test_exceptions.py`
- `isinstance(CRCError(1,2,"x"), ProtocolError)`.
- `isinstance(TimeoutError(0x01, 1.0), TransportError)`.
- `isinstance(ResponseError(0x07, 0), CommandError)`.
- `str(CRCError(0x1234, 0x5678, "55 66"))` contains `"0x1234"` and `"0x5678"`.
- Field preservation (`CRCError(...).expected == ...`).

#### `tests/protocol/test_crc.py`
Parametrise over all 7 test vectors plus `crc16(b"") == 0x0000`. Also:
- Property test: for random bytes `b`, `crc16(b + crc16(b).to_bytes(2,"little"))` matches reference. Actually, XMODEM append-CRC yields a residual equal to `crc16(bytes_plus_CRC) == 0` only if the algorithm is designed to; for XMODEM that's not guaranteed — instead verify that `crc16_check(frame_without_crc, crc.to_bytes(2,"little"))` returns True iff the CRC matches.
- Parametrise a bit-by-bit reference implementation (shift-register XOR poly 0x1021) and assert equivalence with the table-driven `crc16` on 100 random inputs via hypothesis.

#### `tests/protocol/test_frame.py`
Byte-exact encode/decode of all 7 Chapter-4 examples. Each example:
- Construct `Frame.build(cmd_id=..., data=..., seq=..., need_ack=...)` with the values implied by the hex.
- Assert `.to_bytes() == bytes.fromhex(...)` for the complete wire bytes (header+data+crc).
- Assert `Frame.from_bytes(wire) == original`.

Also test: `Frame.from_bytes` raises `FramingError` on STX `5566` mis-match, truncated header, truncated data. Raises `CRCError` when last 2 bytes swapped.

#### `tests/protocol/test_parser.py`
- Feeding `HEARTBEAT_FRAME` 1 byte at a time yields exactly 1 `Frame` with `cmd_id==0x00`.
- Feeding 3 concatenated frames in a single chunk yields 3 frames in order.
- Feeding garbage prefix + valid frame yields 1 frame (resync).
- Feeding oversized `data_len` (>`max_payload`) raises `FramingError` and parser resyncs on next byte.
- Feeding a frame with one byte flipped in the payload raises `CRCError`; next valid frame still parses.
- `hypothesis` test: `tests/property/test_parser_fuzz.py` — feed arbitrary byte streams in arbitrary chunk sizes; assert parser only returns `Frame` objects or raises documented errors (`FramingError`, `CRCError`) — nothing else.

#### `tests/property/test_frame_roundtrip.py`
- `hypothesis.strategies`: `cmd_id ∈ [0x00..0xFF]`, `data ∈ binary(max_size=256)`, `seq ∈ [0..0xFFFF]`, `need_ack ∈ booleans()`. Invariant: `FrameParser().feed(Frame.build(...).to_bytes())` returns exactly `[frame_with_matching_fields]`.
- 1000+ examples.

### Acceptance Criteria
- `pytest tests/test_constants.py tests/test_models.py tests/test_exceptions.py tests/protocol/ tests/property/ -v` → all green.
- Coverage: `pytest tests/test_constants.py tests/test_models.py tests/test_exceptions.py tests/protocol/ tests/property/ --cov=siyi_sdk/constants.py --cov=siyi_sdk/models.py --cov=siyi_sdk/exceptions.py --cov=siyi_sdk/protocol --cov-fail-under=100`.
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
DONE REPORT — siyi-sdk-protocol-layer
Files created:    list each with line count
Files modified:   list each with a one-line description of change
Tests added:      N (all passing)
Coverage delta:   +X.X%
Decisions made:   any non-obvious choices with justification
