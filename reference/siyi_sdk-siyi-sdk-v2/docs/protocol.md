# SIYI Gimbal Camera External SDK Protocol v0.1.1

This document describes the SIYI Gimbal Camera External SDK Protocol, which governs communication with SIYI gimbal camera systems including ZT30, ZT6, ZR10, ZR30, A8 mini, A2 mini, and Quad-Spectrum products.

## Frame Structure

All communication uses a fixed binary frame structure with byte-level serialization:

```
┌─────┬─────┬─────┬──────────┬──────────┬──────────┬───────────┬───────────┬─────┐
│ STX │CTRL │ SEQ │ CMD_ID   │ LEN_L    │ LEN_H    │ PAYLOAD   │ CRC_L     │ CRC_H │
├─────┼─────┼─────┼──────────┼──────────┼──────────┼───────────┼───────────┼─────┤
│  1B │ 1B  │ 1B  │   1B     │   1B     │   1B     │ 0..200 B  │    1B     │  1B │
│0x55 │ --- │ --- │ ---------- Varies by command (see Command Catalogue) │ --- │
└─────┴─────┴─────┴──────────┴──────────┴──────────┴───────────┴───────────┴─────┘
```

### Field Descriptions

| Field | Size | Description |
|-------|------|-------------|
| **STX** | 1B | Start byte, always `0x55` (fixed sentinel). |
| **CTRL** | 1B | Control byte (bit structure: bit 7 = DIR, bits 6–1 = RES, bit 0 = ACK). DIR=1 means host→device; DIR=0 means device→host. RES bits reserved (send 0, ignore on RX). ACK=0 means request, ACK=1 means ACK. |
| **SEQ** | 1B | Sequence number (0x00–0xFF, free-running, wraps). Echoed in ACK by device. |
| **CMD_ID** | 1B | Command identifier (0x00–0xFF). |
| **LEN_L** | 1B | Payload length, low byte (little-endian). |
| **LEN_H** | 1B | Payload length, high byte. |
| **PAYLOAD** | 0–200 B | Command-specific data (0 bytes for heartbeat). |
| **CRC_L** | 1B | CRC-16/XMODEM checksum, low byte. |
| **CRC_H** | 1B | CRC-16/XMODEM checksum, high byte. |

### Frame Encoding and CRC

Frames are constructed as follows:

1. **Build frame** with fields STX, CTRL, SEQ, CMD_ID, LEN_L, LEN_H, PAYLOAD (8 + payload_len bytes).
2. **Compute CRC-16/XMODEM** over all frame bytes up to (but not including) the CRC itself.
3. **Append CRC** in little-endian order (low byte first, high byte second).

Total frame size = 8 + payload_len + 2.

### Example Frame

A heartbeat frame from host to device:

```
55 80 00 00 00 00 13 34
│  │  │  │  │  │  │  │
STX CTRL SEQ CMD_ID LEN_L LEN_H CRC_L CRC_H
```

- STX = `0x55`
- CTRL = `0x80` (bit 7 = 1 for host→device, bits 6–0 = 0)
- SEQ = `0x00`
- CMD_ID = `0x00` (heartbeat)
- LEN_L = `0x00`, LEN_H = `0x00` (no payload)
- CRC = `0x3413` (computed over first 6 bytes)

## CRC-16/XMODEM Algorithm

The CRC-16/XMODEM algorithm is used for frame integrity:

- **Polynomial**: `0x1021`
- **Initial seed**: `0x0000`
- **Final XOR**: none (output used directly)
- **Input reflection**: none
- **Output reflection**: none

### Reference Implementation (Table-Driven)

```python
# Pre-computed CRC lookup table for polynomial 0x1021
_CRC16_TABLE = (
    0x0000, 0x1021, 0x2042, 0x3063, 0x4084, 0x50a5, 0x60c6, 0x70e7,
    0x8108, 0x9129, 0xa14a, 0xb16b, 0xc18c, 0xd1ad, 0xe1ce, 0xf1ef,
    # ... (256 entries total)
)

def crc16_xmodem(data: bytes) -> int:
    """Compute CRC-16/XMODEM over data bytes."""
    crc = 0x0000
    for byte in data:
        tbl_idx = (crc >> 8) ^ byte
        crc = ((crc << 8) ^ _CRC16_TABLE[tbl_idx]) & 0xFFFF
    return crc
```

### Test Vectors

All implementations must validate against these byte sequences:

| Input | Expected CRC (hex) |
|-------|------------------|
| (empty) | `0x0000` |
| `0x55` | `0xCD40` |
| `0x55 0x80 0x00 0x00 0x00 0x00` | `0x3413` |
| `0x55 0x00 0x01 0x01 0x00 0x00` | `0x55ED` |
| `0x55 0x80 0x09 0x04 0x01 0x00` | `0x8D7B` |
| `0x55 0x00 0x08 0x01 0x00 0x00` | `0x64CE` |
| `0x55 0x80 0x0F 0x0C 0x02 0x00 0x01 0x00` | `0x7EB4` |

Each test vector checks CRC correctness over different message lengths and CTRL byte values.

## Command Catalogue

The SIYI protocol defines 80+ commands spanning system, focus, zoom, gimbal, attitude, camera, video, thermal, laser, RC, and AI subsystems. Commands are identified by CMD_ID (0x00–0x82) and classified as Request/ACK pairs.

### Command ID Reference Table

| CMD_ID | Name | Direction | Payload | Description |
|--------|------|-----------|---------|-------------|
| 0x00 | HEARTBEAT | Host → Device | 0 B | Keep-alive (TCP only). |
| 0x01 | REQUEST_FIRMWARE_VERSION | Host → Device | 0 B | Query firmware versions (camera, gimbal, zoom). |
| 0x02 | REQUEST_HARDWARE_ID | Host → Device | 0 B | Query hardware ID (SN, model). |
| 0x04 | AUTO_FOCUS | Host → Device | 4 B | Touch-to-focus at pixel (x, y). |
| 0x05 | MANUAL_ZOOM | Host → Device | 1 B | Zoom in/out (dir: +/−). |
| 0x06 | MANUAL_FOCUS | Host → Device | 1 B | Focus in/out (dir: +/−). |
| 0x07 | GIMBAL_ROTATE | Host → Device | 2 B | Rotate gimbal (yaw, pitch in 0.1° steps). |
| 0x08 | ONE_KEY_CENTERING | Host → Device | 1 B | Center gimbal (action: center/down/up). |
| 0x0A | REQUEST_CAMERA_SYSTEM_INFO | Host → Device | 0 B | Query camera system info (sensor, lens). |
| 0x0B | FUNCTION_FEEDBACK | Device → Host | ≥3 B | Unsolicited feedback (capture status, etc.). |
| 0x0C | CAPTURE_PHOTO_RECORD_VIDEO | Host → Device | 1 B | Capture photo or record video. |
| 0x0D | REQUEST_GIMBAL_ATTITUDE | Bidirectional | 0/12 B | Query gimbal attitude (yaw, pitch, roll, speeds). |
| 0x0E | SET_ATTITUDE | Host → Device | 8 B | Move gimbal to target angles (yaw, pitch). |
| 0x0F | ABSOLUTE_ZOOM | Host → Device | 1 B | Set zoom magnification (1x–100x in 0.1x steps). |
| 0x10 | REQUEST_VIDEO_STITCHING_MODE | Host → Device | 0 B | Query video stitching mode. |
| 0x11 | SET_VIDEO_STITCHING_MODE | Host → Device | 1 B | Set video stitching (OFF/2x/3x/4x/6x). |
| 0x12 | TEMPERATURE_AT_POINT | Host → Device | 5 B | Get spot temperature at pixel (x, y). |
| 0x13 | TEMPERATURE_REGION | Host → Device | 9 B | Get average temp in rectangular region. |
| 0x14 | TEMPERATURE_GLOBAL | Host → Device | 1 B | Get global min/max/avg temperature. |
| 0x15 | REQUEST_LASER_DISTANCE | Bidirectional | 0/2 B | Query laser distance (meters). |
| 0x16 | REQUEST_ZOOM_RANGE | Host → Device | 0 B | Query min/max zoom magnification. |
| 0x17 | REQUEST_LASER_LATLON | Host → Device | 0 B | Query laser target lat/lon. |
| 0x18 | REQUEST_ZOOM_MAGNIFICATION | Host → Device | 0 B | Query current zoom magnification. |
| 0x19 | REQUEST_GIMBAL_MODE | Host → Device | 0 B | Query gimbal motion mode. |
| 0x1A | REQUEST_PSEUDO_COLOR | Host → Device | 0 B | Query pseudo-color mode. |
| 0x1B | SET_PSEUDO_COLOR | Host → Device | 1 B | Set pseudo-color (OFF/BW/IRON/JET/etc.). |
| 0x20 | REQUEST_ENCODING_PARAMS | Host → Device | 1 B | Query video encoding params (stream). |
| 0x21 | SET_ENCODING_PARAMS | Host → Device | 8 B | Set resolution, fps, bitrate. |
| 0x22 | SEND_AIRCRAFT_ATTITUDE | Host → Device | 12 B | Send drone attitude (heading, pitch, roll). |
| 0x23 | SEND_RC_CHANNELS | Host → Device | 36 B | Send RC channels (18 × 2 B). **Deprecated.** |
| 0x24 | REQUEST_FC_DATA_STREAM | Host → Device | 2 B | Subscribe to FC data (attitude/velocity). |
| 0x25 | REQUEST_GIMBAL_DATA_STREAM | Host → Device | 2 B | Subscribe to gimbal attitude stream. |
| 0x26 | REQUEST_MAGNETIC_ENCODER | Bidirectional | 0/6 B | Query magnetic encoder angles. |
| 0x27 | REQUEST_CONTROL_MODE | Host → Device | 0 B | Query control mode (follow/lock). |
| 0x28 | REQUEST_WEAK_CONTROL_THRESHOLD | Host → Device | 0 B | Query weak control threshold. |
| 0x29 | SET_WEAK_CONTROL_THRESHOLD | Host → Device | 2 B | Set weak control threshold (yaw, pitch). |
| 0x2A | REQUEST_MOTOR_VOLTAGE | Bidirectional | 0/2 B | Query motor voltage. |
| 0x30 | SET_UTC_TIME | Host → Device | 8 B | Set system time (Unix timestamp). |
| 0x31 | REQUEST_GIMBAL_SYSTEM_INFO | Host → Device | 0 B | Query gimbal system (pan limits, etc.). |
| 0x32 | SET_LASER_RANGING_STATE | Host → Device | 1 B | Enable/disable laser ranging. |
| 0x33 | REQUEST_THERMAL_OUTPUT_MODE | Host → Device | 0 B | Query thermal output mode. |
| 0x34 | SET_THERMAL_OUTPUT_MODE | Host → Device | 1 B | Set thermal output (visible/thermal/fusion). |
| 0x37 | REQUEST_THERMAL_GAIN | Host → Device | 0 B | Query thermal gain (auto/mid/high). |
| 0x38 | SET_THERMAL_GAIN | Host → Device | 1 B | Set thermal gain. |
| 0x39 | REQUEST_ENV_CORRECTION_PARAMS | Host → Device | 0 B | Query environmental correction (temp, emissivity). |
| 0x3A | SET_ENV_CORRECTION_PARAMS | Host → Device | 8 B | Set environmental correction. |
| 0x3B | REQUEST_ENV_CORRECTION_SWITCH | Host → Device | 0 B | Query thermal correction on/off. |
| 0x3C | SET_ENV_CORRECTION_SWITCH | Host → Device | 1 B | Enable/disable thermal correction. |
| 0x3E | SEND_RAW_GPS | Host → Device | 16 B | Send GPS coordinates (lat, lon, alt). |
| 0x40 | REQUEST_SYSTEM_TIME | Host → Device | 0 B | Query system time (Unix timestamp). |
| 0x41 | SET_GIMBAL_CONTROL_SINGLE_AXIS | Host → Device | 4 B | Move single gimbal axis (yaw/pitch, angle, duration). |
| 0x42 | GET_IR_THRESH_MAP_STATE | Host → Device | 0 B | Query IR threshold mapping on/off. |
| 0x43 | SET_IR_THRESH_MAP_STATE | Host → Device | 1 B | Enable/disable IR threshold mapping. |
| 0x44 | GET_IR_THRESH_PARAM | Host → Device | 0 B | Query IR threshold range (low, high). |
| 0x45 | SET_IR_THRESH_PARAM | Host → Device | 4 B | Set IR threshold range. |
| 0x46 | GET_IR_THRESH_PRECISION | Host → Device | 0 B | Query IR threshold precision (0.1–5°C). |
| 0x47 | SET_IR_THRESH_PRECISION | Host → Device | 1 B | Set IR threshold precision. |
| 0x48 | FORMAT_SD_CARD | Host → Device | 0 B | Erase SD card. |
| 0x49 | GET_PICTURE_NAME_TYPE | Host → Device | 1 B | Query picture naming convention. |
| 0x4A | SET_PICTURE_NAME_TYPE | Host → Device | 2 B | Set picture naming (file type, naming). |
| 0x4B | GET_MAVLINK_OSD_FLAG | Host → Device | 0 B | Query HDMI OSD flag. |
| 0x4C | SET_MAVLINK_OSD_FLAG | Host → Device | 1 B | Enable/disable HDMI OSD. |
| 0x4D | GET_AI_MODE_STA | Host → Device | 0 B | Query AI tracking mode on/off. |
| 0x4E | GET_AI_TRACK_STREAM_STA | Host → Device | 0 B | Query AI tracking stream on/off. |
| 0x4F | MANUAL_THERMAL_SHUTTER | Host → Device | 0 B | Trigger manual thermal shutter. |
| 0x50 | AI_TRACK_STREAM | Device → Host | ≥5 B | AI tracking push (unsolicited). |
| 0x51 | SET_AI_STREAM_OUTPUT | Host → Device | 1 B | Enable/disable AI tracking stream. |
| 0x70 | GET_WEAK_CONTROL_MODE | Host → Device | 0 B | Query weak control mode. |
| 0x71 | SET_WEAK_CONTROL_MODE | Host → Device | 1 B | Enable/disable weak control. |
| 0x80 | SOFT_REBOOT | Host → Device | 1 B | Reboot camera or gimbal or both. |
| 0x81 | GET_IP | Host → Device | 0 B | Query IP configuration (address, gateway, DNS). |
| 0x82 | SET_IP | Host → Device | 12 B | Set IP configuration. |

All commands follow a request-response pattern with ACK, except fire-and-forget commands (0x0C, 0x22, 0x23, 0x3E) and stream push commands (0x0B, 0x0D, 0x15, 0x26, 0x2A, 0x50) which are unsolicited device→host transmissions.

## Timing and Heartbeat

### Sequence Number (SEQ)

- **Range**: 0x00–0xFF (8-bit)
- **Behavior**: Free-running, increments with each outgoing frame, wraps from 0xFF to 0x00
- **ACK**: Device echoes SEQ in ACK frame

### Timeouts

- **Default timeout**: 1 second for all commands
- **Retries**: Idempotent reads (`Request*` / `Get*`) retry once on timeout; writes fail immediately

### Heartbeat (TCP Only)

- **Trigger**: TCP connections only (`transport.supports_heartbeat == True`)
- **Interval**: 1 Hz (every 1 second)
- **Frame**: Standard heartbeat `0x55 0x80 0x00 0x00 0x00 0x00 0x13 0x34`
- **Purpose**: Keep TCP connection alive

### Response Latency

- **Typical**: 10–50 ms for gimbal attitude, 20–100 ms for camera commands
- **Network overhead**: UDP ≈ 5 ms RTT, TCP ≈ 10 ms (with handshake), Serial ≈ 5–20 ms

## Known Quirks and Implementation Notes

### 1. CRC Seed and Final XOR
- **Seed**: `0x0000` (zero)
- **Final XOR**: None (output is used directly)
- Always initialize the CRC state to zero; do not XOR the result.

### 2. CTRL Byte Reserved Bits
- Host sends reserved bits (bits 6–1) as **0**
- Device may send non-zero reserved bits; implementations **log a WARNING but accept the frame**
- Behavior: No error raised, frame is processed normally

### 3. Sequence Number Wrapping
- SEQ is free-running (0x00 → 0xFF → 0x00 → ...)
- No special handling needed; simple byte increment
- ACK frames echo the request's SEQ

### 4. Firmware Version Byte Interpretation
- **Format**: 32-bit unsigned integers (4 bytes each)
- **Quirk**: High byte of each 32-bit word is **ignored** (firmware always zeros it)
- **Example**: `0x01 0x02 0x03 0x04` → version is actually `0x010203` (high byte dropped)

### 5. Retry Logic
- **Idempotent reads** (CMD_IDs in `_IDEMPOTENT_READS` set) retry once on `TimeoutError`
- **Write commands** fail immediately to prevent unintended side effects (e.g., double-capture)
- **Fire-and-forget** commands (0x0C, 0x22, 0x23, 0x3E) send without waiting for ACK

### 6. Heartbeat Mandatory for TCP
- TCP connections **require automatic heartbeat** (client-driven, every 1 s)
- UDP connections do **not** use heartbeat
- Heartbeat frames bypass normal request-response logic; no pending future

### 7. Laser Distance Out-of-Range
- **Raw value 0**: Laser returned no valid distance (out of range, obscured, etc.)
- **Decoded**: `distance_m = None` (Python representation)
- **Example**: `get_laser_distance()` returns `LaserDistance(distance_m=None, ...)`

### 8. A2 Mini Yaw Channel
- A2 mini gimbal may report fixed yaw (no yaw motion)
- Workaround: Ignore yaw updates from `get_gimbal_attitude()` on A2 mini products
- Detection: Check hardware ID; if A2 mini, yaw should not change

### 9. Per-Command Concurrency Control
- When multiple requests share the same CMD_ID, they are **serialized** via per-CMD_ID `asyncio.Lock`
- Different CMD_IDs run concurrently
- Example: `set_attitude()` and `rotate()` (different CMD_IDs) can run in parallel; two `get_gimbal_attitude()` calls (same CMD_ID) serialize

### 10. RC Channels (0x23) Deprecated
- CMD_ID 0x23 is marked **"Not in use"** in newer protocol versions
- Kept for backward compatibility; applications should avoid sending RC channels
- SDK provides `send_rc_channels()` method; use alternatives (e.g., attitude commands) for gimbal control

### 11. Float Endianness (0x22 Aircraft Attitude)
- Aircraft attitude frames (0x22) encode floats in **little-endian** byte order
- Confirmed by round-trip tests (e.g., `[0x0A, 0xD7, 0x23, 0x43]` → 163.414 radians)
- All struct.unpack calls use `<f` (little-endian) format

### 12. Product-Specific "No Response" Entries
- Some commands listed in the protocol spec as "No Response" for certain products
- **SDK behavior**: Apply standard 1-second timeout; no special handling
- If no ACK within 1 s, raise `TimeoutError` (retryable for idempotent reads)

### 13. Resolution Validation (0x21 Encoding Params)
- Valid resolutions: **1920×1080** or **1280×720**
- Encoder validates input; raises `ConfigurationError` for invalid dimensions
- Other resolutions may not be supported by hardware

### 14. Reserved CMD_IDs
- CMD_IDs not listed in the Command Catalogue (e.g., 0x5X–0x7X ranges except specific entries)
- **SDK behavior**: Log a WARNING and drop the frame (do not error)
- Allows graceful degradation if firmware sends unknown commands

## Reference

For the complete SIYI Gimbal Camera External SDK Protocol specification, refer to the official v0.1.1 documentation from SIYI. The Python SDK implements all 80+ commands with strict protocol compliance and comprehensive error handling.
