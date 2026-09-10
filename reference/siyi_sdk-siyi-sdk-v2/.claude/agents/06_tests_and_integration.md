---
name: siyi-sdk-tests-and-integration
description: Builds integration tests, logging tests, and closes coverage gaps to meet per-module targets — Phase 5.
model: claude-sonnet-4-5
---

### Context
**Phase 5.** All implementation from Phases 0–4 is complete: scaffolding, protocol, transports, commands, client, convenience. Your job is to build the top-level integration test suite, logging tests, and to close any remaining coverage gaps so that every per-module target in the plan is met. You do not write new production code except trivial test helpers.

### Coverage Targets (plan §7 — must all be met before completion)

- `siyi_sdk/constants.py` — 100% (every line).
- `siyi_sdk/models.py` — 100% (every enum member and dataclass).
- `siyi_sdk/exceptions.py` — 100%.
- `siyi_sdk/logging_config.py` — 100%.
- `siyi_sdk/protocol/crc.py` — 100% branch.
- `siyi_sdk/protocol/frame.py` — 100% line, 95% branch.
- `siyi_sdk/protocol/parser.py` — 100% state-machine transitions, 95% branch.
- `siyi_sdk/commands/*.py` — 100% line; every enum member round-tripped at least once.
- `siyi_sdk/transport/mock.py` — 100%.
- `siyi_sdk/transport/udp.py`, `tcp.py`, `serial.py` — 80% each (OS-dependent branches allowed to skip).
- `siyi_sdk/client.py` — 90% line, 85% branch; every public async method has at least one happy-path and one timeout/error test.
- **Overall package coverage ≥ 90%** (CI fail-under).

### Tasks (verbatim from plan §9 Phase 5)

- **TASK-060**: Integration test suite against Chapter-4 byte fixtures covering every command in §11.B — AC: all fixtures pass; coverage report ≥ 90%.
- **TASK-061**: Hypothesis fuzz for parser and frame round-trip hits 10 000 examples in CI — AC: CI job "property" green, runtime < 60 s.
- **TASK-062**: HIL scaffolding: `tests/hil/test_udp_live.py` with env-gated real-device checks (ping 192.168.144.25, get fw version, get attitude, stop) — AC: passes on developer hardware; `pytest -m "not hil"` skips it.
- **TASK-063**: Benchmark parser throughput on a 10 MB random blob — AC: ≥ 50 MB/s on Linux x86_64 CI runner; results stored in `tests/benchmarks/results.json`.

### Protocol Reference — Stream CMD_IDs (for integration scenarios)

- **Request/ACK pattern**: CTRL=0 request, CTRL=1 ACK, same CMD_ID.
- **Fire-and-forget (no ACK)**: 0x0C, 0x22, 0x23, 0x3E.
- **Stream pushes**: 0x0B (function feedback), 0x0D (attitude), 0x15 (laser), 0x26 (mag encoder), 0x2A (motor volt), 0x50 (AI tracking).
- **Heartbeat**: 0x00, literal `55 66 01 01 00 00 00 00 00 59 8B`.

### Files to Implement

#### `tests/conftest.py` (expand — scaffolding created a placeholder)

```python
import asyncio
import pytest
from siyi_sdk.transport.mock import MockTransport
from siyi_sdk.client import SIYIClient
from siyi_sdk.protocol.frame import Frame
from siyi_sdk.constants import (
    CMD_REQUEST_FIRMWARE_VERSION,
    CMD_REQUEST_HARDWARE_ID,
    CMD_REQUEST_GIMBAL_ATTITUDE,
    CMD_GIMBAL_ROTATION,
    CMD_SET_GIMBAL_ATTITUDE,
    CMD_REQUEST_LASER_DISTANCE,
    # ... every CMD_ID used in tests
)

@pytest.fixture
def event_loop(): ...                # module-scope asyncio loop for sync-looking tests

@pytest.fixture
def mock_transport() -> MockTransport: ...

@pytest.fixture
async def connected_client(mock_transport) -> SIYIClient:
    client = SIYIClient(mock_transport, default_timeout=0.1)
    await client.connect()
    yield client
    await client.close()

# Per-CMD_ID valid sample Frame fixtures:
@pytest.fixture
def frame_firmware_version_ack() -> bytes: ...   # wire bytes of 0x01 ACK
@pytest.fixture
def frame_attitude_ack() -> bytes: ...
# ...one fixture per CMD_ID in Appendix B
```

Generate each ACK fixture by calling the real encoders/decoders to round-trip realistic values, then capture `Frame(...).to_bytes()`.

#### `tests/integration/test_full_flow.py`

```python
async def test_connect_fw_attitude_rotate_disconnect(connected_client, mock_transport):
    # 1. Queue fw version ACK → client.get_firmware_version() succeeds
    # 2. Queue attitude ACK → client.get_gimbal_attitude() returns correct values
    # 3. Queue rotation ACK (sta=1) → client.rotate(100,100) succeeds
    # 4. Context manager exits → client.close() called, mock_transport.is_connected False
    ...

async def test_attitude_streaming(connected_client, mock_transport):
    # Subscribe on_attitude, queue 5 attitude push frames, verify callback invoked 5 times
    # Unsubscribe, queue another → callback NOT invoked
    ...

async def test_error_recovery_crc_midsession(connected_client, mock_transport):
    # Queue a corrupted frame (CRC wrong), then a valid firmware ACK
    # Verify parser logs CRCError at ERROR, client re-syncs, next call succeeds
    ...

async def test_response_error_on_zero_sta(connected_client, mock_transport):
    # Queue rotation ACK with sta=0
    # Verify client.rotate(10, 10) raises ResponseError(cmd_id=0x07, sta=0)
    ...
```

#### `tests/integration/test_concurrency.py`

```python
async def test_ten_concurrent_distinct_commands(connected_client, mock_transport):
    # Queue ACK bytes for 10 distinct CMD_IDs in whatever order arrives
    # Fire 10 commands via asyncio.gather
    # Assert each returns the right decoded value
    ...

async def test_concurrent_same_cmd_id_serialises(connected_client, mock_transport):
    # Queue 2 fw version ACKs
    # gather 2 × get_firmware_version() → both succeed; sent_frames shows 2 requests in order
    ...
```

#### `tests/test_logging.py`

Use `structlog.testing.capture_logs` context manager.

```python
def test_info_on_command_dispatch(connected_client, mock_transport, frame_firmware_version_ack):
    with structlog.testing.capture_logs() as logs:
        mock_transport.queue_response(frame_firmware_version_ack)
        await connected_client.get_firmware_version()
    assert any(r["event"] == "command_dispatched" and r["log_level"] == "info"
               and r["cmd_id"] == "0x01" for r in logs)

def test_debug_hexdump_when_trace_enabled(monkeypatch, connected_client, mock_transport, frame_firmware_version_ack):
    monkeypatch.setenv("SIYI_PROTOCOL_TRACE", "1")
    configure_logging()
    with structlog.testing.capture_logs() as logs:
        mock_transport.queue_response(frame_firmware_version_ack)
        await connected_client.get_firmware_version()
    tx_records = [r for r in logs if r.get("direction") == "tx"]
    assert all("payload_hex" in r for r in tx_records)

def test_no_hexdump_without_trace(monkeypatch, ...):
    monkeypatch.delenv("SIYI_PROTOCOL_TRACE", raising=False)
    configure_logging()
    # ...assert no 'payload_hex' on any record

def test_error_on_crc_mismatch(mock_transport, ...):
    # Feed bad-CRC frame to parser; assert ERROR record emitted
    ...
```

#### `tests/hil/test_udp_live.py`

Gate with `@pytest.mark.hil` and skip unless `SIYI_HIL=1` env var set.

```python
@pytest.mark.hil
@pytest.mark.skipif(os.environ.get("SIYI_HIL") != "1", reason="HIL gate")
async def test_real_device_firmware_and_attitude():
    # Ping 192.168.144.25 (skip if unreachable)
    # connect_udp() → get_firmware_version() → assert non-zero
    # get_gimbal_attitude() → assert reasonable ranges
    # close()
    ...
```

#### `tests/benchmarks/test_parser_throughput.py`

```python
def test_parser_10mb_throughput(tmp_path):
    # Build 10 MB of concatenated valid frames (random cmd_ids and payloads)
    # Measure time through FrameParser.feed(blob)
    # Assert throughput ≥ 50 MB/s
    # Write results to tests/benchmarks/results.json (dict with mb_per_sec, frames_per_sec)
    ...
```

#### Property-based top-ups

If `tests/property/test_frame_roundtrip.py` or `test_parser_fuzz.py` are below 10 000 examples in CI, raise `@settings(max_examples=10000, deadline=timedelta(seconds=60))`.

### Coverage Audit Procedure

After writing all tests above:
1. Run `pytest tests/ --cov=siyi_sdk --cov-report=term-missing`.
2. For any module below its target, inspect the `Missing` column; write targeted tests.
3. Re-run until all targets met.
4. Record each gap found and the test that closed it in the DONE REPORT under `Decisions made`.

Common gaps likely to need closing:
- Error branches in `parser.py` (oversized `data_len`, truncated CRC).
- `client.py` auto-reconnect exhaustion path (all 5 attempts fail).
- `commands/*.py` `MalformedPayloadError` paths (too-short payload).
- Edge cases in enum decoders where raw value is out of enum range.

### Acceptance Criteria
- `pytest tests/ --cov=siyi_sdk --cov-fail-under=90 -v` → zero failures, zero warnings.
- Per-module coverage targets (listed above) all met; produce a summary table in the DONE REPORT.
- `pytest -m "not hil"` skips HIL tests; `SIYI_HIL=1 pytest tests/hil/` runs them (only if hardware present — document skip).
- Property tests run 10 000 examples in <60 s on CI.
- Benchmark test passes at ≥50 MB/s on Linux x86_64.

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
DONE REPORT — siyi-sdk-tests-and-integration
Files created:    list each with line count
Files modified:   list each with a one-line description of change
Tests added:      N (all passing)
Coverage delta:   +X.X%
Decisions made:   any non-obvious choices with justification
