---
name: siyi-sdk-final-qa
description: Release-gate audit — static analysis, test suite, protocol-fidelity audit, API surface, docs, build — Phase 7.
model: claude-opus-4-5
---

### Context
**Phase 7 — release gate.** All prior agents (Phases 0–6) have completed. This agent audits the entire package end-to-end, fixes any issues surfaced, and produces a final sign-off report. **Do not add new features.** Fix only what is needed to make the checks below pass.

### Protocol Reference — Complete Command Catalogue (Appendix B — fidelity audit checklist)

| CMD_ID | Name | Dir | Request payload | ACK payload |
|--------|------|-----|-----------------|-------------|
| 0x00 | TCP Heartbeat | →g | (empty) | none |
| 0x01 | Request Firmware Version | →g | (empty) | `uint32 camera_ver, uint32 gimbal_ver, uint32 zoom_ver` |
| 0x02 | Request Hardware ID | →g | (empty) | `uint8 hardware_id[12]` |
| 0x04 | Auto Focus | →g | `uint8 auto_focus, uint16 touch_x, uint16 touch_y` | `uint8 sta` |
| 0x05 | Manual Zoom with AF | →g | `int8 zoom ∈ {-1,0,1}` | `uint16 zoom_multiple (×10)` |
| 0x06 | Manual Focus | →g | `int8 focus ∈ {-1,0,1}` | `uint8 sta` |
| 0x07 | Gimbal Rotation | →g | `int8 turn_yaw, int8 turn_pitch` | `uint8 sta` |
| 0x08 | One-Key Centering | →g | `uint8 center_pos ∈ {1..4}` | `uint8 sta` |
| 0x0A | Request Camera System Info | →g | (empty) | 8 × uint8 |
| 0x0B | Function Feedback | g→ | (empty req) | `uint8 info_type` (0..6) |
| 0x0C | Capture Photo / Record Video | →g | `uint8 func_type` (0..10) | none |
| 0x0D | Request Gimbal Attitude | →g | (empty) | 6 × int16 (÷10) |
| 0x0E | Set Gimbal Attitude | →g | `int16 yaw, int16 pitch` (deciDeg) | 3 × int16 (÷10) |
| 0x0F | Absolute Zoom AF | →g | `uint8 int_part (1..0x1E), uint8 float_part (0..9)` | `uint8 ack` |
| 0x10 | Request Video Stitching Mode | →g | (empty) | `uint8 vdisp_mode` (0..8) |
| 0x11 | Set Video Stitching Mode | →g | `uint8 vdisp_mode` | `uint8 vdisp_mode` |
| 0x12 | Get Temp at Point | →g | `uint16 x, uint16 y, uint8 flag` | `uint16 temp(÷100), uint16 x, uint16 y` |
| 0x13 | Local Temp Measurement | →g | `uint16 startx, starty, endx, endy, uint8 flag` | 10 × uint16 |
| 0x14 | Global Temp Measurement | →g | `uint8 flag` | 6 × uint16 |
| 0x15 | Request Laser Distance | →g | (empty) | `uint16 laser_distance` (dm) |
| 0x16 | Request Zoom Range | →g | (empty) | `uint8 max_int, uint8 max_float` |
| 0x17 | Request Laser Target Lon/Lat | →g | (empty) | `int32 lon_E7, int32 lat_E7` |
| 0x18 | Request Current Zoom | →g | (empty) | `uint8 int, uint8 float` |
| 0x19 | Request Current Gimbal Mode | →g | (empty) | `uint8 gimbal_mode` |
| 0x1A | Request Pseudo Color | →g | (empty) | `uint8 pseudo_color` (0..11) |
| 0x1B | Set Pseudo Color | →g | `uint8 pseudo_color` | `uint8 pseudo_color` |
| 0x20 | Request Encoding Params | →g | `uint8 stream` (0/1/2) | 9 bytes |
| 0x21 | Set Encoding Params | →g | 9 bytes | `uint8 stream, uint8 sta` |
| 0x22 | Send Aircraft Attitude | ←fc | `uint32 tb, 6 × float` (rad/rad·s) | none |
| 0x23 | Send RC Channels | ←fc | 18 × uint16 + uint8 count + uint8 rssi | none |
| 0x24 | Request FC → Gimbal Stream | →g | `uint8 data_type (1,2), uint8 freq` | `uint8 data_type` |
| 0x25 | Request Gimbal → Stream | →g | `uint8 data_type (1..4), uint8 freq` | `uint8 data_type` |
| 0x26 | Request Magnetic Encoder | →g | (empty) | 3 × int16 (÷10) |
| 0x27 | Request Control Mode | →g | (empty) | `uint8 mode (0..4)` |
| 0x28 | Request Weak Threshold | →g | (empty) | 3 × int16 (÷10) |
| 0x29 | Set Weak Threshold | →g | 3 × int16 | `uint8 sta` |
| 0x2A | Request Motor Voltage | →g | (empty) | 3 × int16 (÷1000 V) |
| 0x30 | Set UTC Time | →g | `uint64 unix_usec` | `int8 ack` |
| 0x31 | Request Gimbal System Info | →g | (empty) | `uint8 laser_state` |
| 0x32 | Set Laser Ranging State | →g | `uint8 laser_state` | `uint8 sta` |
| 0x33 | Request Thermal Output Mode | →g | (empty) | `uint8 mode (0,1)` |
| 0x34 | Set Thermal Output Mode | →g | `uint8 mode` | `uint8 mode` |
| 0x35 | Get Single Temp Frame | →g | (empty) | `uint8 ack` |
| 0x37 | Request Thermal Gain | →g | (empty) | `uint8 gain` |
| 0x38 | Set Thermal Gain | →g | `uint8 gain` | `uint8 gain` |
| 0x39 | Request Env Correction Params | →g | (empty) | 5 × uint16 (÷100) |
| 0x3A | Set Env Correction Params | →g | 5 × uint16 | `uint8 ack` |
| 0x3B | Request Env Correction Switch | →g | (empty) | `uint8` |
| 0x3C | Set Env Correction Switch | →g | `uint8` | `uint8` |
| 0x3E | Send Raw GPS | ←fc | `uint32 tb + 7 × int32` | none |
| 0x40 | Request System Time | →g | (empty) | `uint64 unix_usec + uint32 boot_ms` |
| 0x41 | Single-Axis Attitude | →g | `int16 angle, uint8 axis (0/1)` | 3 × int16 (÷10) |
| 0x42 | Get IR Thresh Map Status | →g | (empty) | `uint8` |
| 0x43 | Set IR Thresh Map Status | →g | `uint8` | `uint8` |
| 0x44 | Get IR Thresh Params | →g | (empty) | 3 × (uint8 + 2 × int16 + 3 × uint8) |
| 0x45 | Set IR Thresh Params | →g | same | `uint8 ack` |
| 0x46 | Get IR Thresh Precision | →g | (empty) | `uint8 (1/2/3)` |
| 0x47 | Set IR Thresh Precision | →g | `uint8` | `uint8` |
| 0x48 | Format SD Card | →g | `uint8` | `uint8` |
| 0x49 | Get Picture Name Type | →g | `uint8 ft` | `uint8 ft, uint8 nt` |
| 0x4A | Set Picture Name Type | →g | `uint8 ft, uint8 nt` | same |
| 0x4B | Get HDMI OSD Status | →g | (empty) | `uint8` |
| 0x4C | Set HDMI OSD Status | →g | `uint8` | `uint8` |
| 0x4D | Get AI Mode Status | →g | (empty) | `uint8 sta (0/1)` |
| 0x4E | Get AI Tracking Stream Status | →g | (empty) | `uint8 sta (0..3)` |
| 0x4F | Manual Thermal Shutter | →g | (empty) | `uint8 ack` |
| 0x50 | AI Tracking Stream Push | g→ | (auto) | 4 × uint16 + 2 × uint8 |
| 0x51 | Set AI Tracking Stream Output | →g | `uint8 track_action (0/1)` | `uint8 sta` |
| 0x70 | Request Weak Control Mode | →g | (empty) | `uint8` |
| 0x71 | Set Weak Control Mode | →g | `uint8` | `uint8 sta, uint8 state` |
| 0x80 | Soft Reboot | →g | `uint8 cam, uint8 gim` | same |
| 0x81 | Get IP Address | →g | (empty) | 3 × uint32 |
| 0x82 | Set IP Address | →g | 3 × uint32 | `uint8 ack` |

### Checks to Execute (in order — fix failures before proceeding)

#### 1. Static Analysis
- `ruff check siyi_sdk/ tests/` → zero errors.
- `ruff format --check siyi_sdk/ tests/` → zero violations.
- `mypy siyi_sdk/ --strict` → zero errors.

If any fail: fix the specific issue, re-run. Do not silence with `# noqa` or `# type: ignore` unless the issue is a known false positive (document in DONE REPORT).

#### 2. Full Test Suite
- `pytest tests/ -v --tb=short --cov=siyi_sdk --cov-report=term-missing`.
- Required: all tests pass; overall coverage ≥ 90%.
- If any test is flaky, diagnose and fix — do not skip.

#### 3. Protocol Fidelity Audit
For **every row in the command catalogue above**, verify:
- [ ] A `CMD_<NAME>` constant exists in `siyi_sdk/constants.py` with the correct value.
- [ ] An encoder `encode_*` and (if the command has an ACK) a decoder `decode_*` exist in the correct `siyi_sdk/commands/*.py` module.
- [ ] The encoder's output byte layout matches the Request payload column.
- [ ] The decoder's interpretation matches the ACK payload column (field order, types, scale factors).
- [ ] The command is exposed as a public async method on `SIYIClient` with a name that matches plan §3.
- [ ] The method appears in `README.md`'s API reference table.

Record any gap as: `AUDIT-FAIL: <command name> — <what is missing>` in the final report. Fix the gap (add the missing piece) and re-audit.

Special cases (exempt from method-on-client requirement):
- 0x0B `Function Feedback`, 0x50 `AI Tracking Stream Push` — async-push only; exposed as `on_function_feedback` / `on_ai_tracking` subscription registrars, not as async methods. This is correct.
- 0x00 `TCP Heartbeat` — exposed as `heartbeat()` and also automatic via `_heartbeat()` task on TCP.

#### 4. API Surface Audit
- [ ] `__all__` defined and correct in `siyi_sdk/__init__.py`, `siyi_sdk/protocol/__init__.py`, `siyi_sdk/transport/__init__.py`, `siyi_sdk/commands/__init__.py`.
- [ ] `siyi_sdk/__init__.py` re-exports `SIYIClient`, `connect_udp`, `connect_tcp`, `connect_serial`, and the core models (`GimbalAttitude`, `FirmwareVersion`, etc.).
- [ ] No names starting with `_` appear in any `__all__`.
- [ ] Every public method/function has a Google-style docstring.
- [ ] Every public function/method has full type annotations (mypy --strict enforces this).
- [ ] `SIYIClient.__init__` signature matches `convenience.py` factory defaults (`default_timeout`, `auto_reconnect`).

#### 5. Documentation Audit
- [ ] `ruff check --select D siyi_sdk/` → zero violations (pydocstyle D-class rules).
- [ ] `python -m py_compile examples/*.py` → all examples compile.
- [ ] `README.md` API reference table has one row per `SIYIClient` public async method (diff against introspection of the class).
- [ ] `docs/protocol.md` mentions every CMD_ID from 0x00 to 0x82 listed in Appendix B above.
- [ ] `CHANGELOG.md` has a populated `[0.1.0]` section.

#### 6. Build Audit
- `python -m build` → produces `dist/siyi_sdk-0.1.0-py3-none-any.whl` and `dist/siyi_sdk-0.1.0.tar.gz`.
- `twine check dist/*` → `PASSED`.
- (No upload — that's the release workflow's job on tag push.)

#### 7. Final Report
Output this report as the last thing in the session, after the DONE REPORT:

```
RELEASE READINESS REPORT — siyi-sdk v0.1.0
============================================
Static analysis — ruff:    PASS / FAIL
Static analysis — mypy:    PASS / FAIL  (N errors)
Test suite:                PASS / FAIL  (N/N tests, X.X% coverage)
Protocol fidelity:         PASS / FAIL
  Commands implemented:    N / 75
  AUDIT-FAIL items:        [list or "none"]
API surface:               PASS / FAIL
Documentation:             PASS / FAIL
Build:                     PASS / FAIL
────────────────────────────────────────────
OVERALL: READY FOR RELEASE / BLOCKED
Blockers: [list or "none"]
```

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
DONE REPORT — siyi-sdk-final-qa
Files created:    list each with line count
Files modified:   list each with a one-line description of change
Tests added:      N (all passing)
Coverage delta:   +X.X%
Decisions made:   any non-obvious choices with justification
