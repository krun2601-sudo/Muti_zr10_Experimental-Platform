---
name: siyi-sdk-transport-layer
description: Implements UDP, TCP, Serial, and Mock transports behind AbstractTransport — Phase 2.
model: claude-sonnet-4-5
---

### Context
**Phase 2.** Protocol foundation (Phase 1) is complete: `constants.py`, `models.py`, `exceptions.py`, `protocol/{crc,frame,parser}.py`, `logging_config.py` all exist and pass tests. You implement the transport layer: one `AbstractTransport` ABC and four concrete transports (UDP, TCP, Serial, Mock). No client code, no command encoders.

### Protocol Reference — Frame Structure (for context)

```
Offset  Bytes  Field     Type     Endianness
0       2      STX       uint16   LE (0x6655 → wire 0x55 0x66)
2       1      CTRL      uint8    -
3       2      Data_len  uint16   LE
5       2      SEQ       uint16   LE
7       1      CMD_ID    uint8    -
8       N      DATA      bytes    -
8+N     2      CRC16     uint16   LE (CRC-16/XMODEM, poly 0x1021, seed 0x0000)
```

### Protocol Reference — Transport Endpoints and Heartbeat (Appendix E)

- **Defaults**: gimbal IP `192.168.144.25`, UDP port `37260`, TCP port `37260`, serial baud `115200` (8-N-1).
- **Heartbeat** (TCP only): `CMD_TCP_HEARTBEAT = 0x00`, empty payload. Literal wire bytes `55 66 01 01 00 00 00 00 00 59 8B` (available as `HEARTBEAT_FRAME` in `siyi_sdk.constants`). Recommended interval: **1 Hz**. No ACK expected.
- UDP and Serial do **not** require heartbeat — `supports_heartbeat = False` for those transports.
- Reconnection policy (SDK-defined, from plan §4): exponential back-off `0.5, 1, 2, 4, 8` seconds; max 5 attempts before raising `ConnectionError`. Implemented in `client.py` (Phase 4) — transports themselves do not auto-reconnect; they raise on failure.

### Ambiguity resolutions that affect transport (plan §11.G)

- Heartbeat for UDP/Serial: disabled (`supports_heartbeat=False`). TCP only.
- TCP heartbeat interval: 1 s. No ACK expected. Send raw `HEARTBEAT_FRAME` bytes.

### Tasks (verbatim from plan §9 Phase 2)

- **TASK-020**: Implement `siyi_sdk/transport/base.py` `AbstractTransport` ABC and `Unsubscribe` type alias — AC: `mypy --strict` passes; `isinstance` check works.
- **TASK-021**: Implement `siyi_sdk/transport/mock.py` `MockTransport` — AC: queued bytes stream in FIFO order; `sent_frames` captures every `send()`.
- **TASK-022**: Implement `siyi_sdk/transport/udp.py` `UDPTransport` on `asyncio.DatagramProtocol` — AC: round-trip against a loopback UDP echo server.
- **TASK-023**: Implement `siyi_sdk/transport/tcp.py` `TCPTransport` (`supports_heartbeat=True`) — AC: round-trip against `asyncio.start_server`.
- **TASK-024**: Implement `siyi_sdk/transport/serial.py` `SerialTransport` using `pyserial-asyncio` — AC: round-trip on a `socat` pty pair.
- **TASK-025**: Write `tests/transport/test_*.py` for all four transports — AC: 80% coverage on real transports, 100% on mock.

### Files to Implement

#### `siyi_sdk/transport/base.py`

```python
from __future__ import annotations
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable
from typing import TypeAlias

Unsubscribe: TypeAlias = Callable[[], None]

class AbstractTransport(ABC):
    @abstractmethod
    async def connect(self) -> None: ...
    @abstractmethod
    async def close(self) -> None: ...
    @abstractmethod
    async def send(self, data: bytes) -> None: ...
    @abstractmethod
    def stream(self) -> AsyncIterator[bytes]: ...
    @property
    @abstractmethod
    def is_connected(self) -> bool: ...
    @property
    @abstractmethod
    def supports_heartbeat(self) -> bool: ...
```

Raises: `ConnectionError` from `connect()` on failure; `NotConnectedError` from `send()` if called before `connect()`; `SendError` on OS-level failure during send.

#### `siyi_sdk/transport/mock.py`

```python
class MockTransport(AbstractTransport):
    def __init__(self) -> None: ...
    async def connect(self) -> None: ...     # sets _connected=True
    async def close(self) -> None: ...       # sets _connected=False, cancels stream iterator
    async def send(self, data: bytes) -> None: ...   # appends to _sent_frames
    def stream(self) -> AsyncIterator[bytes]: ...    # yields from _response_queue
    @property
    def is_connected(self) -> bool: ...
    @property
    def supports_heartbeat(self) -> bool: ...  # False by default; configurable via ctor arg
    def queue_response(self, data: bytes) -> None: ...
    def queue_error(self, exc: Exception) -> None: ...
    @property
    def sent_frames(self) -> list[bytes]: ...
```

- `queue_response(bytes)` places bytes into an `asyncio.Queue`; the async iterator from `stream()` awaits and yields each entry.
- `queue_error(exc)` enqueues a sentinel; the stream iterator re-raises the exception when consumed.
- `sent_frames` returns a copy of the internal list (defensive).
- Support an optional `supports_heartbeat: bool = False` constructor kwarg so tests can simulate TCP-like behaviour.

#### `siyi_sdk/transport/udp.py`

```python
class UDPTransport(AbstractTransport):
    def __init__(
        self,
        ip: str = DEFAULT_IP,
        port: int = DEFAULT_UDP_PORT,
        *,
        bind_port: int | None = None,
    ) -> None: ...
```

- Use `asyncio.DatagramProtocol`. On `connect`:
  - Create an `asyncio.DatagramEndpoint` via `loop.create_datagram_endpoint(lambda: _DatagramProtocol(self._queue), remote_addr=(ip,port), local_addr=("0.0.0.0", bind_port) if bind_port else None)`.
  - Store the `transport` object.
- `send`: `self._transport.sendto(data)`. Wrap OS errors in `SendError`.
- `stream()`: async generator yielding each datagram from `self._queue`.
- `close`: `self._transport.close()`; drain queue.
- `supports_heartbeat = False`.
- Log INFO on connect (`connected transport=udp peer=ip:port`) and disconnect (`disconnected transport=udp`).

#### `siyi_sdk/transport/tcp.py`

```python
class TCPTransport(AbstractTransport):
    def __init__(
        self,
        ip: str = DEFAULT_IP,
        port: int = DEFAULT_TCP_PORT,
    ) -> None: ...
```

- Use `asyncio.open_connection(ip, port)` → `(reader, writer)`.
- `stream()`: loops on `await reader.read(4096)` and yields bytes until EOF.
- `send`: `writer.write(data); await writer.drain()`. Wrap in `SendError` on `ConnectionResetError`/`BrokenPipeError`.
- `close`: `writer.close(); await writer.wait_closed()`.
- `supports_heartbeat = True`.

#### `siyi_sdk/transport/serial.py`

```python
class SerialTransport(AbstractTransport):
    def __init__(
        self,
        device: str,
        baud: int = DEFAULT_BAUD,
    ) -> None: ...
```

- Use `serial_asyncio.open_serial_connection(url=device, baudrate=baud, bytesize=8, parity="N", stopbits=1)`.
- `send`/`stream`/`close` mirror TCP.
- `supports_heartbeat = False`.

### Tests to Write

#### `tests/transport/test_base.py`
- Assert `AbstractTransport` is an ABC (cannot instantiate directly — `pytest.raises(TypeError)`).
- Assert all abstract methods are declared.
- Assert `Unsubscribe` type alias is callable-zero-arg-returning-None.

#### `tests/transport/test_mock.py`
- `queue_response(b"\x01\x02"); async for chunk in t.stream(): ...` yields `b"\x01\x02"`.
- `queue_error(RuntimeError("boom"))`; iterating the stream raises.
- `send(b"hi")` appends to `sent_frames`.
- `is_connected` toggles on `connect`/`close`.
- FIFO ordering for multiple queued responses.
- Coverage target: 100%.

#### `tests/transport/test_udp.py`
- Spin up a loopback UDP echo server in the test (`loop.create_datagram_endpoint(EchoProto, local_addr=("127.0.0.1",0))`).
- Transport connects to that server, sends a heartbeat frame, receives the echo via `stream()`.
- Target: 80% coverage.

#### `tests/transport/test_tcp.py`
- Use `asyncio.start_server` on 127.0.0.1:0 that echoes bytes.
- Connect `TCPTransport` to that server; round-trip bytes.
- Test graceful `close`.
- Test `supports_heartbeat == True`.
- Target: 80%.

#### `tests/transport/test_serial.py`
- Skip if `socat` unavailable (`pytest.importorskip` on `serial_asyncio` and a runtime check for `socat`). Use a `socat` pty pair (`socat pty,raw,echo=0 pty,raw,echo=0`) spawned via `asyncio.create_subprocess_exec`.
- Round-trip bytes on pty pair.
- Target: 80% (OS-dependent branches allowed to skip).

### Acceptance Criteria
- `pytest tests/transport/ -v` → all green.
- `pytest tests/transport/ --cov=siyi_sdk/transport --cov-fail-under=90` (mock=100%, others ≥80% averaged).
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
DONE REPORT — siyi-sdk-transport-layer
Files created:    list each with line count
Files modified:   list each with a one-line description of change
Tests added:      N (all passing)
Coverage delta:   +X.X%
Decisions made:   any non-obvious choices with justification
