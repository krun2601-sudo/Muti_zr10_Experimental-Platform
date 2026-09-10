---
name: siyi-sdk-command-layer
description: Implements per-command encode/decode helpers covering the full SIYI catalogue (~75 CMD_IDs) — Phase 3.
model: claude-sonnet-4-5
---

### Context
**Phase 3.** Protocol foundation (Phase 1) and transports (Phase 2) are complete. You implement **all per-command encoder/decoder helpers** in `siyi_sdk/commands/*.py`. These are pure functions, no I/O. They are called by `SIYIClient` (built in Phase 4).

Every encoder validates range/domain and raises `ConfigurationError` on invalid input. Every decoder validates payload length and raises `MalformedPayloadError` on mismatch. Decoders for commands with a `sta`/`ack` status byte raise `ResponseError(cmd_id, sta)` when `sta == 0`.

### Protocol Reference — Complete Command Catalogue (Appendix B)

| CMD_ID | Name | Dir | Request payload | ACK payload | Notes |
|--------|------|-----|-----------------|-------------|-------|
| 0x00 | TCP Heartbeat | →gimbal | (empty) | none | TCP only, 1 Hz, literal `55 66 01 01 00 00 00 00 00 59 8B` |
| 0x01 | Request Firmware Version | →g | (empty) | `uint32 camera_ver, uint32 gimbal_ver, uint32 zoom_ver` | high byte of each word ignored; up to 30 s after boot returns zeros |
| 0x02 | Request Hardware ID | →g | (empty) | `uint8 hardware_id[12]` | first 2 bytes = product (`0x6B` ZR10, `0x73` A8, `0x75` A2, `0x78` ZR30, `0x7A` Quad) |
| 0x04 | Auto Focus | →g | `uint8 auto_focus, uint16 touch_x, uint16 touch_y` | `uint8 sta` | optical-zoom cameras only; split-zoom halves X range |
| 0x05 | Manual Zoom with AF | →g | `int8 zoom ∈ {-1,0,1}` | `uint16 zoom_multiple` (actual × 10) | |
| 0x06 | Manual Focus | →g | `int8 focus ∈ {-1,0,1}` | `uint8 sta` | optical zoom cameras only |
| 0x07 | Gimbal Rotation | →g | `int8 turn_yaw, int8 turn_pitch` (-100..100) | `uint8 sta` | send 0,0 to stop |
| 0x08 | One-Key Centering | →g | `uint8 center_pos ∈ {1,2,3,4}` | `uint8 sta` | 1=center,2=down,3=center,4=down |
| 0x0A | Request Camera System Info | →g | (empty) | 8 × `uint8` | reserved, hdr_sta, reserved, record_sta, gimbal_motion_mode, gimbal_mounting_dir, video_hdmi_or_cvbs, zoom_linkage |
| 0x0B | Function Feedback | g→ | (empty req) | `uint8 info_type` (0..6) | async push on photo/video events |
| 0x0C | Capture Photo / Record Video | →g | `uint8 func_type` (0..10) | none | 0=photo, 2=start rec, 3=lock, 4=follow, 5=fpv, 6=HDMI (reboot), 7=CVBS (reboot), 8=disable both, 9=tilt down, 10=zoom linkage |
| 0x0D | Request Gimbal Attitude | →g | (empty) | `int16 yaw, pitch, roll, yaw_vel, pitch_vel, roll_vel` (÷10 deg / dps) | NED, yaw→roll→pitch order |
| 0x0E | Set Gimbal Attitude | →g | `int16 yaw, int16 pitch` (deciDeg) | `int16 yaw, pitch, roll` (deciDeg) | limits per product (A2: yaw fixed; A8/ZR10: ±135°; ZR30: ±270°; ZT30: unlimited; pitch: −90..25°) |
| 0x0F | Absolute Zoom AF | →g | `uint8 int_part (1..0x1E), uint8 float_part (0..9)` | `uint8 ack` | zoom = int+float/10 |
| 0x10 | Request Video Stitching Mode | →g | (empty) | `uint8 vdisp_mode (0..8)` | |
| 0x11 | Set Video Stitching Mode | →g | `uint8 vdisp_mode` | `uint8 vdisp_mode` | |
| 0x12 | Get Temp at Point | →g | `uint16 x, uint16 y, uint8 get_temp_flag` | `uint16 temp(÷100), uint16 x, uint16 y` | |
| 0x13 | Local Temp Measurement | →g | `uint16 startx, starty, endx, endy; uint8 flag` | 10 × `uint16` (rect + max/min temp ÷100 + their coords) | |
| 0x14 | Global Temp Measurement | →g | `uint8 get_temp_flag` | 6 × `uint16` (max/min ÷100 + coords) | |
| 0x15 | Request Laser Distance | →g | (empty) | `uint16 laser_distance` (unit dm, min 50) | 5 m..1200 m; outside → 0 |
| 0x16 | Request Zoom Range | →g | (empty) | `uint8 max_int, uint8 max_float` | zoom cameras only |
| 0x17 | Request Laser Target Lon/Lat | →g | (empty) | `int32 lon_degE7, int32 lat_degE7` | WGS84/EGM96 |
| 0x18 | Request Current Zoom | →g | (empty) | `uint8 zoom_int, uint8 zoom_float` | |
| 0x19 | Request Current Gimbal Mode | →g | (empty) | `uint8 gimbal_mode` (0/1/2) | |
| 0x1A | Request Pseudo Color | →g | (empty) | `uint8 pseudo_color` (0..11) | |
| 0x1B | Set Pseudo Color | →g | `uint8 pseudo_color` | `uint8 pseudo_color` | |
| 0x20 | Request Encoding Params | →g | `uint8 req_stream_type` (0/1/2) | `uint8 stream_type, uint8 VideoEncType (1=H264,2=H265), uint16 Resolution_L, uint16 Resolution_H, uint16 VideoBitrate (kbps), uint8 FrameRate` | |
| 0x21 | Set Encoding Params | →g | `uint8 stream_type, uint8 enc_type, uint16 res_L, uint16 res_H, uint16 bitrate, uint8 reserve` | `uint8 stream_type, uint8 sta` | Resolution options: 1920×1080 / 1280×720; recording enc_type unchangeable |
| 0x22 | Send Aircraft Attitude | ←fc | `uint32 time_boot_ms, float roll, pitch, yaw, rollspeed, pitchspeed, yawspeed` (rad, rad/s, NED) | none | 20–50 Hz recommended |
| 0x23 | Send RC Channels | ←fc | 18 × `uint16 chanN_raw (µs), uint8 chancount, uint8 rssi` | none | "Not in use" per spec |
| 0x24 | Request FC → Gimbal Stream | →g | `uint8 data_type ∈ {1,2}, uint8 data_freq ∈ {0..7}` | `uint8 data_type` | freqs: 0=off,1=2Hz,2=4Hz,3=5Hz,4=10Hz,5=20Hz,6=50Hz,7=100Hz |
| 0x25 | Request Gimbal → Stream | →g | `uint8 data_type ∈ {1..4}, uint8 data_freq` | `uint8 data_type` | laser (2) ignores freq |
| 0x26 | Request Magnetic Encoder Angles | →g | (empty) | `int16 yaw, pitch, roll` (÷10) | |
| 0x27 | Request Control Mode | →g | (empty) | `uint8 Control_mode ∈ {0..4}` | ArduPilot only |
| 0x28 | Request Weak Threshold | →g | (empty) | 3 × `int16` (limit 10..50, voltage 20..50, ang_err 30..300, all ÷10) | ArduPilot only |
| 0x29 | Set Weak Threshold | →g | 3 × `int16` as 0x28 | `uint8 sta` | ArduPilot only |
| 0x2A | Request Motor Voltage | →g | (empty) | `int16 yaw, pitch, roll` (÷1000 V) | ArduPilot only |
| 0x30 | Set UTC Time | →g | `uint64 timestamp` (unix µs) | `int8 ack` (1 ok / 0 bad format) | |
| 0x31 | Request Gimbal System Info | →g | (empty) | `uint8 laser_state` | |
| 0x32 | Set Laser Ranging State | →g | `uint8 laser_state` | `uint8 sta` | |
| 0x33 | Request Thermal Output Mode | →g | (empty) | `uint8 mode ∈ {0,1}` | 0=30fps,1=25fps+temp |
| 0x34 | Set Thermal Output Mode | →g | `uint8 mode` | `uint8 mode` | |
| 0x35 | Get Single Temp Frame | →g | (empty) | `uint8 ack` (1 ok) | |
| 0x37 | Request Thermal Gain | →g | (empty) | `uint8 Ir_gain ∈ {0,1}` | |
| 0x38 | Set Thermal Gain | →g | `uint8 Ir_gain` | `uint8 Ir_gain` | |
| 0x39 | Request Env Correction Params | →g | (empty) | 5 × `uint16` (Dist m, Ems %, Hum %, Ta °C, Tu °C — all ÷100) | |
| 0x3A | Set Env Correction Params | →g | 5 × `uint16` as 0x39 | `uint8 ack` | |
| 0x3B | Request Env Correction Switch | →g | (empty) | `uint8 EnvCorrect` | |
| 0x3C | Set Env Correction Switch | →g | `uint8 EnvCorrect` | `uint8 EnvCorrect` | |
| 0x3E | Send Raw GPS | ←fc | `uint32 time_boot_ms, int32 lat_degE7, lon_degE7, alt_msl_cm, alt_ell_cm, vn_mE3, ve_mE3, vd_mE3` | none | ZR10/ZR30/A8 mini: no response |
| 0x40 | Request System Time | →g | (empty) | `uint64 time_unix_usec, uint32 time_boot_ms` | |
| 0x41 | Single-Axis Attitude | →g | `int16 angle, uint8 single_control_flag` (0=yaw,1=pitch) | `int16 yaw, pitch, roll` | A8 responds with 0x0E |
| 0x42 | Get IR Thresh Map Status | →g | (empty) | `uint8 ir_thresh_sta` | |
| 0x43 | Set IR Thresh Map Status | →g | `uint8 ir_thresh_sta` | `uint8 ir_thresh_sta` | |
| 0x44 | Get IR Thresh Params | →g | (empty) | 3 × (uint8 switch + int16[2] temp + uint8[3] color) | |
| 0x45 | Set IR Thresh Params | →g | same shape | `uint8 ack` | |
| 0x46 | Get IR Thresh Precision | →g | (empty) | `uint8 precision ∈ {1,2,3}` | |
| 0x47 | Set IR Thresh Precision | →g | `uint8 precision` | `uint8 precision` | |
| 0x48 | Format SD Card | →g | `uint8 format_sta` | `uint8 format_sta` | ZT30/ZR30/A8: no response |
| 0x49 | Get Picture Name Type | →g | `uint8 File_type` | `uint8 File_type, uint8 File_name_type` | |
| 0x4A | Set Picture Name Type | →g | `uint8 File_type, uint8 File_name_type` | same | |
| 0x4B | Get HDMI OSD Status | →g | (empty) | `uint8 Osd_sta` | |
| 0x4C | Set HDMI OSD Status | →g | `uint8 Osd_sta` | `uint8 Osd_sta` | |
| 0x4D | Get AI Mode Status | →g | (empty) | `uint8 sta` (0/1) | AI module required |
| 0x4E | Get AI Tracking Stream Status | →g | (empty) | `uint8 sta` (0..3) | |
| 0x4F | Manual Thermal Shutter | →g | (empty) | `uint8 ack` | |
| 0x50 | AI Tracking Stream Push | g→ | (auto) | `uint16 pos_x, pos_y, pos_width, pos_height, uint8 Target_ID, uint8 Track_Sta` | origin = box center; frame 1280×720 |
| 0x51 | Set AI Tracking Stream Output | →g | `uint8 track_action` (1=on,0=off) | `uint8 sta` | |
| 0x70 | Request Weak Control Mode | →g | (empty) | `uint8 Weak_mode_state` | |
| 0x71 | Set Weak Control Mode | →g | `uint8 Weak_mode_state` | `uint8 sta, uint8 Weak_mode_state` | |
| 0x80 | Gimbal Camera Soft Reboot | →g | `uint8 Camera_reboot, uint8 Gimbal_reset` | same | |
| 0x81 | Get IP Address | →g | (empty) | `uint32 IP, uint32 Mask, uint32 Gateway` | |
| 0x82 | Set IP Address | →g | `uint32 IP, uint32 Mask, uint32 Gateway` | `uint8 ack` | |

### Protocol Reference — Data Types and Scale Factors (Appendix C)

- Angles: ÷10 (deciDeg); aircraft attitude 0x22 in **radians** (IEEE-754 little-endian floats).
- Temperatures: ÷100.
- Motor voltage: ÷1000 (volts).
- GPS lat/lon: ×10⁷ (int32); altitude cm (int32); velocity mm/s (int32).
- Zoom: ÷10 for 0x05 ACK `zoom_multiple`; `int_part + float_part/10` for 0x0F / 0x16 / 0x18.
- Laser distance: decimetres (uint16), raw ≥ 50 means valid; raw 0 (or <50) → out of range → `LaserDistance(distance_m=None)`.
- Boot grace: 30 s (fw returns zeros before then).

### Ambiguity resolutions affecting encoders (plan §11.G)

- 0x22 float endianness: **little-endian** (matches the rest of the protocol).
- 0x23 RC channels: marked "Not in use" in spec — implement encoder/decoder; call site (client) raises `DeprecationWarning`.
- 0x0E A2_MINI yaw fixed: no SDK-side rejection, log DEBUG note if product==A2 and yaw != 0 (deferred to client).
- 0x21 resolution constraints: encoder validates 1920×1080 or 1280×720 only; other combos raise `ConfigurationError`.
- 0x15 laser out-of-range: raw 0 → `distance_m=None`, never raise.

### Tasks (verbatim from plan §9 Phase 3)

- **TASK-030**: Implement `commands/system.py` (0x00, 0x01, 0x02, 0x30, 0x31, 0x40, 0x80, 0x81, 0x82) — AC: fw decode of `0x6E030203 → FirmwareVersion(*, *, *)` equals `v3.2.3` (low 3 bytes); Chapter-4 Retrieve-Firmware-Version example byte-exactly encoded.
- **TASK-031**: Implement `commands/focus.py` (0x04, 0x06) — AC: `auto_focus(1, 300, 100)` encodes to `04 01 2C 01 64 00` payload matching Chapter 4 example.
- **TASK-032**: Implement `commands/zoom.py` (0x05, 0x0F, 0x16, 0x18) — AC: `absolute_zoom(4.5)` encodes to `0F 04 05` matching Chapter 4 example; `current_zoom` decode returns `1.0` for `{01, 00}`.
- **TASK-033**: Implement `commands/gimbal.py` (0x07, 0x08, 0x0E, 0x19, 0x41) — AC: `rotate(100,100)` matches Chapter-4 `07 64 64`; `set_attitude(-90.0, 0.0)` encodes pitch field = `0xFC7C` (−900 int16 LE).
- **TASK-034**: Implement `commands/attitude.py` (0x0D, 0x22, 0x24, 0x25, 0x26, 0x3E) — AC: `GimbalAttitude` decoder divides raw int16 by 10; Chapter-4 GPS example round-trips.
- **TASK-035**: Implement `commands/camera.py` (0x0A, 0x0B, 0x0C, 0x20, 0x21, 0x48, 0x49, 0x4A, 0x4B, 0x4C) — AC: Chapter-4 "Set Camera Encoding Params Main Stream HD H.265 1.5M" fixture encodes byte-exactly.
- **TASK-036**: Implement `commands/video.py` (0x10, 0x11) — AC: all 9 stitching modes enum round-trip.
- **TASK-037**: Implement `commands/thermal.py` (0x12–0x14, 0x1A, 0x1B, 0x33–0x3C, 0x42–0x47, 0x4F) — AC: `temp_at_point` divides raw /100; all 12 pseudo-colours round-trip.
- **TASK-038**: Implement `commands/laser.py` (0x15, 0x17, 0x32) — AC: raw 0 → `LaserDistance(None)`; raw 100 → 10.0 m; raw below 50 → `None` per spec.
- **TASK-039**: Implement `commands/rc.py` (0x23, 0x24) — AC: 18 channels + chancount + rssi pack into 20+2 bytes correctly. Note: `20 bytes` = 18×uint8 is wrong — the plan says 18×uint16 = 36 bytes + 2 status bytes = 38 bytes. Wait, re-check: spec §0x23 says "18 × `uint16 chanN_raw (µs)`, `uint8 chancount`, `uint8 rssi`". Implement as 18×2 + 2 = 38 bytes total.
- **TASK-040**: Implement `commands/debug.py` (0x27–0x2A, 0x70, 0x71) — AC: motor voltage /1000 conversion; threshold /10 conversion.
- **TASK-041**: Implement `commands/ai.py` (0x4D, 0x4E, 0x50, 0x51) — AC: AI tracking stream decode matches §0x50 structure; `AITargetID(255).name == "ANY"`.

### Files to Implement — one per command group

For every module below, use `struct.pack`/`unpack` with explicit `"<"` little-endian prefix. Import `CMD_*` constants from `siyi_sdk.constants`. Import dataclasses/enums from `siyi_sdk.models`. Raise `ConfigurationError` on bad encode input, `MalformedPayloadError` on bad decode input, `ResponseError(cmd_id, sta)` when `sta == 0`.

#### `siyi_sdk/commands/system.py` (0x00, 0x01, 0x02, 0x30, 0x31, 0x40, 0x80, 0x81, 0x82)

```python
def encode_heartbeat() -> bytes                                        # CMD 0x00, payload b""
def encode_firmware_version() -> bytes                                 # CMD 0x01, payload b""
def decode_firmware_version(payload: bytes) -> FirmwareVersion         # 12 bytes: 3 × uint32 LE
def encode_hardware_id() -> bytes                                      # CMD 0x02, payload b""
def decode_hardware_id(payload: bytes) -> HardwareID                   # 12-byte raw
def encode_set_utc_time(unix_usec: int) -> bytes                       # CMD 0x30, 8 bytes LE
def decode_set_utc_time_ack(payload: bytes) -> bool                    # int8; raise ResponseError on 0
def encode_gimbal_system_info() -> bytes                               # CMD 0x31, payload b""
def decode_gimbal_system_info(payload: bytes) -> GimbalSystemInfo      # 1 byte laser_state
def encode_system_time() -> bytes                                      # CMD 0x40, payload b""
def decode_system_time(payload: bytes) -> SystemTime                   # uint64 + uint32
def encode_soft_reboot(camera: bool, gimbal: bool) -> bytes            # CMD 0x80, 2 bytes
def decode_soft_reboot_ack(payload: bytes) -> tuple[bool, bool]        # 2 bytes
def encode_get_ip() -> bytes                                           # CMD 0x81, payload b""
def decode_get_ip(payload: bytes) -> IPConfig                          # 3 × uint32 LE → IPv4Address
def encode_set_ip(cfg: IPConfig) -> bytes                              # CMD 0x82, 12 bytes
def decode_set_ip_ack(payload: bytes) -> None                          # uint8 ack; raise ResponseError on 0
```

Firmware decode details: each `uint32` low 3 bytes → `(major, minor, patch)`. Example `0x6E030203` → `(0x03, 0x02, 0x03)` → v3.2.3. (The ordering in the example byte `03 02 03 6E` little-endian → `0x6E030203`; low 3 bytes = `0x030203` → interpret as `patch=0x03, minor=0x02, major=0x03`.) Confirm by cross-checking against `SIYI_SDK_PROTOCOL.pdf` §0x01 — the spec shows fields `{patch, minor, major, ignored}` in byte order; the dataclass uses `major, minor, patch`.

#### `siyi_sdk/commands/focus.py` (0x04, 0x06)

```python
def encode_auto_focus(auto_focus: int, touch_x: int, touch_y: int) -> bytes
    # validates 0 <= auto_focus <= 255, 0 <= touch_x/y <= 0xFFFF; 5 bytes: uint8 + 2 × uint16 LE
def decode_auto_focus_ack(payload: bytes) -> None                      # sta; ResponseError on 0
def encode_manual_focus(direction: int) -> bytes                        # direction ∈ {-1,0,1}; int8
def decode_manual_focus_ack(payload: bytes) -> None
```
Chapter-4 example to test: `auto_focus(1, 300, 100)` → payload bytes `01 2C 01 64 00`.

#### `siyi_sdk/commands/zoom.py` (0x05, 0x0F, 0x16, 0x18)

```python
def encode_manual_zoom(direction: int) -> bytes                        # int8 ∈ {-1,0,1}
def decode_manual_zoom_ack(payload: bytes) -> float                    # uint16 LE → / 10.0
def encode_absolute_zoom(zoom: float) -> bytes
    # int_part = int(zoom) ∈ [1,0x1E], float_part = int(round((zoom%1)*10)) ∈ [0..9]
def decode_absolute_zoom_ack(payload: bytes) -> None                   # uint8 ack; ResponseError on 0
def encode_zoom_range() -> bytes                                       # CMD 0x16 empty
def decode_zoom_range(payload: bytes) -> ZoomRange                     # 2 × uint8
def encode_current_zoom() -> bytes                                     # CMD 0x18 empty
def decode_current_zoom(payload: bytes) -> CurrentZoom                 # 2 × uint8
```
Chapter-4 example: `absolute_zoom(4.5)` → payload `04 05`.

#### `siyi_sdk/commands/gimbal.py` (0x07, 0x08, 0x0E, 0x19, 0x41)

```python
def encode_rotation(yaw: int, pitch: int) -> bytes
    # int8 × 2; validates -100 ≤ x ≤ 100
def decode_rotation_ack(payload: bytes) -> None                        # uint8 sta; ResponseError on 0
def encode_one_key_centering(action: CenteringAction) -> bytes         # uint8 ∈ {1..4}
def decode_one_key_centering_ack(payload: bytes) -> None               # ResponseError on 0
def encode_set_attitude(yaw_deg: float, pitch_deg: float) -> bytes
    # int16 LE × 2; multiply by 10, round to int
def decode_set_attitude_ack(payload: bytes) -> SetAttitudeAck          # 3 × int16 LE / 10.0
def encode_gimbal_mode() -> bytes                                      # CMD 0x19 empty
def decode_gimbal_mode(payload: bytes) -> GimbalMotionMode             # uint8
def encode_single_axis(angle_deg: float, axis: int) -> bytes
    # int16 LE + uint8; axis ∈ {0,1}
def decode_single_axis_ack(payload: bytes) -> SetAttitudeAck           # 3 × int16 / 10
```
Chapter-4 fixtures to test:
- `rotate(100,100)` → payload `64 64`.
- `set_attitude(-90.0, 0.0)` → pitch field (2nd int16) should be `0x0000`; if you swap fields, yaw = −90° = −900 deciDeg → LE `7C FC` (i.e. `0xFC7C`). Plan wording: "set_attitude(-90.0, 0.0) encodes pitch field = 0xFC7C (−900 int16 LE)" — implementers should match the plan's convention: signature `(yaw_deg, pitch_deg)` → wire `int16(yaw*10), int16(pitch*10)`. Per plan example: signature is `(yaw=−90, pitch=0)` → `yaw_raw=−900=0xFC7C`, `pitch_raw=0=0x0000` → payload bytes `7C FC 00 00`. Implement this ordering.

#### `siyi_sdk/commands/attitude.py` (0x0D, 0x22, 0x24, 0x25, 0x26, 0x3E)

```python
def encode_gimbal_attitude() -> bytes                                  # CMD 0x0D empty
def decode_gimbal_attitude(payload: bytes) -> GimbalAttitude           # 6 × int16 LE / 10.0
def encode_aircraft_attitude(att: AircraftAttitude) -> bytes           # uint32 + 6 × float LE
def encode_fc_stream(data_type: FCDataType, freq: DataStreamFreq) -> bytes    # 2 × uint8
def decode_fc_stream_ack(payload: bytes) -> FCDataType
def encode_gimbal_stream(data_type: GimbalDataType, freq: DataStreamFreq) -> bytes
def decode_gimbal_stream_ack(payload: bytes) -> GimbalDataType
def encode_magnetic_encoder() -> bytes                                 # empty
def decode_magnetic_encoder(payload: bytes) -> MagneticEncoderAngles   # 3 × int16 / 10
def encode_raw_gps(gps: RawGPS) -> bytes                               # uint32 + 7 × int32 LE
```

#### `siyi_sdk/commands/camera.py` (0x0A, 0x0B, 0x0C, 0x20, 0x21, 0x48, 0x49, 0x4A, 0x4B, 0x4C)

```python
def encode_camera_system_info() -> bytes                                # empty
def decode_camera_system_info(payload: bytes) -> CameraSystemInfo       # 8 × uint8 (with enums)
def decode_function_feedback(payload: bytes) -> FunctionFeedback        # uint8 → enum
def encode_capture(func: CaptureFuncType) -> bytes                      # uint8 ∈ {0..10}
def encode_get_encoding_params(stream: StreamType) -> bytes             # uint8
def decode_get_encoding_params(payload: bytes) -> EncodingParams        # 9 bytes
def encode_set_encoding_params(params: EncodingParams) -> bytes         # 9 bytes (incl. 1 reserve)
    # validate res_w×res_h ∈ {(1920,1080), (1280,720)}
def decode_set_encoding_params_ack(payload: bytes) -> bool              # 2 bytes: stream_type, sta
def encode_format_sd(format_sta: int = 1) -> bytes                      # uint8
def decode_format_sd_ack(payload: bytes) -> bool
def encode_get_pic_name_type(ft: FileType) -> bytes                     # uint8
def decode_get_pic_name_type(payload: bytes) -> FileNameType            # 2 bytes; validate ft matches
def encode_set_pic_name_type(ft: FileType, nt: FileNameType) -> bytes   # 2 bytes
def decode_set_pic_name_type_ack(payload: bytes) -> None
def encode_get_osd_flag() -> bytes                                      # empty
def decode_get_osd_flag(payload: bytes) -> bool                         # uint8
def encode_set_osd_flag(on: bool) -> bytes                              # uint8
def decode_set_osd_flag_ack(payload: bytes) -> bool
```

#### `siyi_sdk/commands/video.py` (0x10, 0x11)

```python
def encode_get_video_stitching_mode() -> bytes                          # empty
def decode_video_stitching_mode(payload: bytes) -> VideoStitchingMode   # uint8 → enum
def encode_set_video_stitching_mode(mode: VideoStitchingMode) -> bytes
def decode_set_video_stitching_mode_ack(payload: bytes) -> VideoStitchingMode
```

#### `siyi_sdk/commands/thermal.py` (0x12–0x14, 0x1A, 0x1B, 0x33–0x3C, 0x42–0x47, 0x4F)

Full complement of encoders/decoders for all thermal commands. Use `/100` scale on all temperature uint16 fields. Example:
```python
def encode_temp_at_point(x: int, y: int, flag: TempMeasureFlag) -> bytes      # 2×uint16 + uint8
def decode_temp_at_point(payload: bytes) -> TempPoint                         # 3×uint16; temp/100
def encode_local_temp(startx: int, starty: int, endx: int, endy: int, flag: TempMeasureFlag) -> bytes
def decode_local_temp(payload: bytes) -> TempRegion                           # 10×uint16
def encode_global_temp(flag: TempMeasureFlag) -> bytes
def decode_global_temp(payload: bytes) -> TempGlobal                          # 6×uint16
def encode_get_pseudo_color() -> bytes
def decode_pseudo_color(payload: bytes) -> PseudoColor                        # uint8
def encode_set_pseudo_color(c: PseudoColor) -> bytes
def decode_set_pseudo_color_ack(payload: bytes) -> PseudoColor
def encode_get_thermal_output_mode() -> bytes
def decode_thermal_output_mode(payload: bytes) -> ThermalOutputMode
def encode_set_thermal_output_mode(m: ThermalOutputMode) -> bytes
def decode_set_thermal_output_mode_ack(payload: bytes) -> ThermalOutputMode
def encode_get_single_temp_frame() -> bytes
def decode_single_temp_frame_ack(payload: bytes) -> bool
def encode_get_thermal_gain() -> bytes
def decode_thermal_gain(payload: bytes) -> ThermalGain
def encode_set_thermal_gain(g: ThermalGain) -> bytes
def decode_set_thermal_gain_ack(payload: bytes) -> ThermalGain
def encode_get_env_correction_params() -> bytes
def decode_env_correction_params(payload: bytes) -> EnvCorrectionParams      # 5×uint16/100
def encode_set_env_correction_params(p: EnvCorrectionParams) -> bytes        # 5×uint16
def decode_set_env_correction_params_ack(payload: bytes) -> bool             # ResponseError on 0
def encode_get_env_correction_switch() -> bytes
def decode_env_correction_switch(payload: bytes) -> bool
def encode_set_env_correction_switch(on: bool) -> bytes
def decode_set_env_correction_switch_ack(payload: bytes) -> bool
def encode_get_ir_thresh_map_state() -> bytes
def decode_ir_thresh_map_state(payload: bytes) -> bool
def encode_set_ir_thresh_map_state(on: bool) -> bytes
def decode_set_ir_thresh_map_state_ack(payload: bytes) -> bool
def encode_get_ir_thresh_params() -> bytes
def decode_ir_thresh_params(payload: bytes) -> IRThreshParams                 # 3×(u8+2×i16+3×u8)
def encode_set_ir_thresh_params(p: IRThreshParams) -> bytes
def decode_set_ir_thresh_params_ack(payload: bytes) -> bool                   # ResponseError on 0
def encode_get_ir_thresh_precision() -> bytes
def decode_ir_thresh_precision(payload: bytes) -> IRThreshPrecision           # uint8 ∈ {1,2,3}
def encode_set_ir_thresh_precision(p: IRThreshPrecision) -> bytes
def decode_set_ir_thresh_precision_ack(payload: bytes) -> IRThreshPrecision
def encode_manual_thermal_shutter() -> bytes                                  # empty
def decode_manual_thermal_shutter_ack(payload: bytes) -> bool
```

#### `siyi_sdk/commands/laser.py` (0x15, 0x17, 0x32)

```python
def encode_laser_distance() -> bytes                                     # empty
def decode_laser_distance(payload: bytes) -> LaserDistance
    # raw = uint16 LE; if raw == 0 or raw < LASER_MIN_RAW_DM: distance_m=None
    # else distance_m = raw / 10.0
def encode_laser_target_latlon() -> bytes                                # empty
def decode_laser_target_latlon(payload: bytes) -> LaserTargetLatLon      # 2 × int32 LE
def encode_set_laser_ranging_state(on: bool) -> bytes                    # uint8
def decode_set_laser_ranging_state_ack(payload: bytes) -> bool           # uint8 sta; ResponseError on 0
```

#### `siyi_sdk/commands/rc.py` (0x23, 0x24)

```python
def encode_rc_channels(ch: RCChannels) -> bytes
    # 18 × uint16 LE + uint8 chancount + uint8 rssi = 38 bytes
def encode_fc_stream(...)      # delegates to attitude.encode_fc_stream (or re-export)
```

#### `siyi_sdk/commands/debug.py` (0x27–0x2A, 0x70, 0x71)

```python
def encode_get_control_mode() -> bytes
def decode_control_mode(payload: bytes) -> ControlMode                   # uint8 ∈ {0..4}
def encode_get_weak_threshold() -> bytes
def decode_weak_threshold(payload: bytes) -> WeakControlThreshold        # 3 × int16 / 10
def encode_set_weak_threshold(t: WeakControlThreshold) -> bytes          # 3 × int16
def decode_set_weak_threshold_ack(payload: bytes) -> bool                # uint8 sta; ResponseError on 0
def encode_get_motor_voltage() -> bytes
def decode_motor_voltage(payload: bytes) -> MotorVoltage                 # 3 × int16 / 1000
def encode_get_weak_control_mode() -> bytes
def decode_weak_control_mode(payload: bytes) -> bool                     # uint8
def encode_set_weak_control_mode(on: bool) -> bytes
def decode_set_weak_control_mode_ack(payload: bytes) -> bool             # 2 bytes: sta, state; ResponseError on 0
```

#### `siyi_sdk/commands/ai.py` (0x4D, 0x4E, 0x50, 0x51)

```python
def encode_get_ai_mode() -> bytes
def decode_ai_mode(payload: bytes) -> bool                               # uint8 ∈ {0,1}
def encode_get_ai_stream_status() -> bytes
def decode_ai_stream_status(payload: bytes) -> AIStreamStatus            # uint8 ∈ {0..3}
def decode_ai_tracking(payload: bytes) -> AITrackingTarget               # 4×uint16 + 2×uint8
def encode_set_ai_stream_output(on: bool) -> bytes                       # uint8
def decode_set_ai_stream_output_ack(payload: bytes) -> bool              # uint8 sta; ResponseError on 0
```

#### `siyi_sdk/commands/__init__.py`

Re-export every public `encode_*` and `decode_*` function. Populate `__all__`.

### Tests to Write

For every command file, create `tests/commands/test_<group>.py` with:
1. **Round-trip tests**: for every encoder with an inverse decoder pair, verify `decode(encode(value)) == value` over representative inputs.
2. **Byte-exact fixtures**: every Chapter-4 example from the plan's acceptance criteria must be tested byte-exact (e.g., `encode_rotation(100,100) == bytes.fromhex("6464")`).
3. **Boundary tests**: int ranges (−100/+100 for rotation; 1/0x1E for zoom int_part; 0/9 for zoom decimal; −9000/+9000 deciDeg for set_attitude).
4. **Invalid-input tests**: `pytest.raises(ConfigurationError)` for out-of-range values.
5. **Malformed payload**: `pytest.raises(MalformedPayloadError)` when decoder receives the wrong byte count.
6. **Status byte tests**: `pytest.raises(ResponseError)` when `sta == 0` for every command with an `sta` in its ACK.
7. **Enum round-trip**: every enum member mentioned in the group is encoded and decoded back.

Specific test requirements:
- `test_system.py`: firmware decode of word `0x6E030203` → `(major=3, minor=2, patch=3)`; byte-exact Retrieve-Firmware-Version wire encoding.
- `test_focus.py`: `auto_focus(1, 300, 100)` → payload `01 2C 01 64 00`.
- `test_zoom.py`: `absolute_zoom(4.5)` → payload `04 05`; `decode_current_zoom(b"\x01\x00").zoom == 1.0`.
- `test_gimbal.py`: `encode_rotation(100,100) == bytes.fromhex("6464")`; `encode_set_attitude(-90.0, 0.0) == bytes.fromhex("7CFC0000")`; per-product angle limits table smoke-checked.
- `test_attitude.py`: `decode_gimbal_attitude` divides every raw int16 by 10; GPS round-trip.
- `test_camera.py`: Chapter-4 "Set Camera Encoding Params Main Stream HD H.265 1.5M" fixture encodes byte-exactly — read exact bytes from `SIYI_SDK_PROTOCOL.pdf` Chapter 4 and embed as the fixture.
- `test_video.py`: all 9 `VideoStitchingMode` members round-trip.
- `test_thermal.py`: all 12 `PseudoColor` members; all temperature decoders apply /100.
- `test_laser.py`: raw=0 → None; raw=49 → None; raw=50 → 5.0 m; raw=100 → 10.0 m; raw=12000 → 1200.0 m.
- `test_rc.py`: 38-byte payload exactly for 18 channels + count + rssi.
- `test_debug.py`: motor voltage /1000; threshold /10.
- `test_ai.py`: `AITargetID(255).name == "ANY"`; 0x50 tracking payload decode.

### Acceptance Criteria
- `pytest tests/commands/ -v` → all green.
- `pytest tests/commands/ --cov=siyi_sdk/commands --cov-fail-under=95`.
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
DONE REPORT — siyi-sdk-command-layer
Files created:    list each with line count
Files modified:   list each with a one-line description of change
Tests added:      N (all passing)
Coverage delta:   +X.X%
Decisions made:   any non-obvious choices with justification
