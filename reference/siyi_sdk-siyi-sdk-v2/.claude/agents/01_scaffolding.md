---
name: siyi-sdk-scaffolding
description: Creates the entire SIYI SDK project skeleton — pyproject, CI, package directories, logging config — Phase 0.
model: claude-haiku-4-5
---

### Context
This is **Phase 0** of the SIYI SDK build. No `siyi_sdk/` source files exist yet. Your job is to lay the full project skeleton: build configuration, lint/type/test tooling, CI workflows, empty package trees with `__init__.py` stubs, and the logging configuration module. You do not implement protocol logic, transports, or commands — later agents do that. You must leave the repo in a state where `hatch run lint`, `hatch run typecheck`, and `pytest --collect-only` all exit 0.

### Tasks (verbatim from Implementation Plan §9 Phase 0)

- **TASK-001**: Create `pyproject.toml` with hatch build-system, project metadata, and dependency pins from §10 — AC: `hatch env create && hatch run python -c "import siyi_sdk"` succeeds on empty package.
- **TASK-002**: Add `ruff` + `black` config in `pyproject.toml`, line-length 100, target-version py310 — AC: `hatch run lint` exits 0 on empty package.
- **TASK-003**: Add `mypy --strict` config (strict=True, warn_unreachable, disallow_any_generics) — AC: `hatch run typecheck` exits 0 on empty package.
- **TASK-004**: Add `.pre-commit-config.yaml` (ruff, black, mypy, trailing-whitespace, end-of-file-fixer) and `CONTRIBUTING.md` — AC: `pre-commit run --all-files` green.
- **TASK-005**: Create empty `siyi_sdk/__init__.py` declaring `__version__ = "0.0.0"` and empty sub-packages (`protocol/`, `transport/`, `commands/`) with `__init__.py` — AC: `python -c "import siyi_sdk.protocol, siyi_sdk.transport, siyi_sdk.commands"` succeeds.
- **TASK-006**: Mirror empty package structure under `tests/` with `__init__.py` files and `conftest.py` placeholder — AC: `pytest --collect-only` runs with 0 errors.
- **TASK-007**: Add `.github/workflows/ci.yml` (lint → typecheck → test → build) — AC: CI green on the scaffolded repo.
- **TASK-008**: Add `.github/workflows/release.yml` (PyPI publish on `v*` tag) — AC: dry-run (`act` or manual trigger) builds artifact.
- **TASK-009**: Initial `CHANGELOG.md` (`[0.0.1] - YYYY-MM-DD — Added: scaffolding`) and `README.md` skeleton — AC: both files present, CHANGELOG passes Keep-a-Changelog linter.

### Dependency Table (from plan §10 — use these exact version pins)

**Runtime:**
| Package | Version pin | Purpose |
|---|---|---|
| structlog | >=24.0,<26 | Structured JSON logging |
| pyserial-asyncio | >=0.6,<1 | Serial/UART transport |
| typing-extensions | >=4.10 | `Annotated`, `Self`, `override` on py310/311 |

**Dev:**
| Package | Version pin | Purpose |
|---|---|---|
| pytest | >=8,<9 | Test runner |
| pytest-asyncio | >=0.23,<1 | async test support |
| pytest-cov | >=5,<6 | Coverage |
| hypothesis | >=6.100,<7 | Property-based testing |
| mypy | >=1.10,<2 | Static type checking |
| ruff | >=0.5,<1 | Lint |
| black | >=24.3,<26 | Format |
| hatch | >=1.12,<2 | Build/env manager |
| uv | >=0.4 | Lockfile resolver |
| pre-commit | >=3.7,<5 | Git hooks |

### Files to Create (full paths from repo root)

#### `pyproject.toml`
Required sections and values:
- `[build-system]` requires `hatchling`, build-backend `hatchling.build`.
- `[project]`:
  - `name = "siyi-sdk"`
  - `version = "0.0.0"` (bumped in later phases)
  - `description = "Async Python SDK for the SIYI Gimbal Camera External SDK Protocol v0.1.1"`
  - `readme = "README.md"`
  - `requires-python = ">=3.10"`
  - `license = {text = "MIT"}`
  - `authors = [{name = "SIYI SDK Contributors"}]`
  - `classifiers`: `Development Status :: 3 - Alpha`, `Framework :: AsyncIO`, `Intended Audience :: Developers`, `License :: OSI Approved :: MIT License`, `Operating System :: POSIX :: Linux`, `Programming Language :: Python :: 3.10/3.11/3.12/3.13`, `Topic :: Scientific/Engineering`, `Typing :: Typed`.
  - `dependencies = ["structlog>=24.0,<26", "pyserial-asyncio>=0.6,<1", "typing-extensions>=4.10"]`.
- `[project.optional-dependencies]` or `[project.urls]` as needed. Add `Homepage`, `Repository`, `Changelog` URLs (use placeholders `https://github.com/OWNER/siyi-sdk`).
- `[tool.hatch.envs.default]` `dependencies` = all dev packages above.
- `[tool.hatch.envs.test]` with `dependencies` including pytest stack; `scripts.test = "pytest {args:tests}"`, `scripts.cov = "pytest --cov=siyi_sdk --cov-report=term-missing {args:tests}"`.
- `[tool.hatch.envs.lint]` with `dependencies = ["ruff>=0.5,<1","black>=24.3,<26","mypy>=1.10,<2"]`, `scripts`:
  - `lint = ["ruff check siyi_sdk tests", "ruff format --check siyi_sdk tests", "black --check siyi_sdk tests"]`
  - `typecheck = "mypy siyi_sdk --strict"`
  - `fmt = ["ruff format siyi_sdk tests", "black siyi_sdk tests"]`
- `[tool.ruff]`: `line-length = 100`, `target-version = "py310"`.
- `[tool.ruff.lint]`: `select = ["E","F","W","I","N","UP","B","C4","SIM","D","ANN","ASYNC","RUF"]`, `ignore = ["D203","D213"]` (Google style). `[tool.ruff.lint.per-file-ignores]` `"tests/**" = ["D","ANN"]`. `[tool.ruff.lint.pydocstyle]` `convention = "google"`.
- `[tool.black]`: `line-length = 100`, `target-version = ["py310","py311","py312","py313"]`.
- `[tool.mypy]`: `strict = true`, `warn_unreachable = true`, `disallow_any_generics = true`, `warn_unused_ignores = true`, `python_version = "3.10"`. `[[tool.mypy.overrides]]` `module = "serial_asyncio.*"` `ignore_missing_imports = true`.
- `[tool.pytest.ini_options]`: `asyncio_mode = "auto"`, `testpaths = ["tests"]`, `markers = ["hil: hardware-in-the-loop tests (skipped by default)"]`, `addopts = "-ra --strict-markers"`.
- `[tool.coverage.run]` `source = ["siyi_sdk"]`, `branch = true`.
- `[tool.coverage.report]` `show_missing = true`, `fail_under = 90`.

#### `.github/workflows/ci.yml`
- Trigger: `on: [push, pull_request]` with `branches: [main]`.
- Jobs in this order (each depends on prior via `needs:`):
  1. `lint` — ubuntu-latest, Python 3.12, install hatch, `hatch run lint:lint`.
  2. `typecheck` — needs `lint`, `hatch run lint:typecheck`.
  3. `test` — needs `typecheck`, matrix `python-version: ["3.10","3.11","3.12","3.13"]`, `hatch run test:cov`.
  4. `build` — needs `test`, `hatch build`, upload `dist/*` artifact.

#### `.github/workflows/release.yml`
- Trigger: `on: push: tags: [ 'v*.*.*' ]`.
- Jobs: `build` (`hatch build`) then `publish` with `pypa/gh-action-pypi-publish@release/v1` using OIDC (`permissions: id-token: write`). After publish, create a GitHub Release via `softprops/action-gh-release@v2` with body taken from the matching `CHANGELOG.md` section.

#### `.pre-commit-config.yaml`
- Repos:
  - `https://github.com/astral-sh/ruff-pre-commit` rev `v0.5.0` — hooks `ruff` (with `--fix`) and `ruff-format`.
  - `https://github.com/psf/black` rev `24.3.0` — hook `black`.
  - `https://github.com/pre-commit/mirrors-mypy` rev `v1.10.0` — hook `mypy` with additional_dependencies `["structlog","typing-extensions"]`.
  - `https://github.com/pre-commit/pre-commit-hooks` rev `v4.6.0` — `trailing-whitespace`, `end-of-file-fixer`, `check-yaml`, `check-toml`.

#### Package skeleton
Create these files with the exact content below:

- `siyi_sdk/__init__.py`:
  ```python
  """SIYI Gimbal Camera External SDK Protocol — async Python SDK."""
  from __future__ import annotations

  __version__ = "0.0.0"
  __all__: list[str] = []
  ```
- `siyi_sdk/protocol/__init__.py`, `siyi_sdk/transport/__init__.py`, `siyi_sdk/commands/__init__.py` — each identical:
  ```python
  """Sub-package placeholder."""
  from __future__ import annotations

  __all__: list[str] = []
  ```
- `siyi_sdk/py.typed` — empty marker file (PEP 561).
- `tests/__init__.py`, `tests/protocol/__init__.py`, `tests/transport/__init__.py`, `tests/commands/__init__.py`, `tests/property/__init__.py`, `tests/hil/__init__.py` — all empty.
- `tests/conftest.py`:
  ```python
  """Top-level pytest fixtures — populated in later phases."""
  from __future__ import annotations
  ```

#### `siyi_sdk/logging_config.py`
Implement now (this is the only runtime module you write). Required behaviour:
- `get_logger(name: str) -> structlog.stdlib.BoundLogger` — returns a bound logger.
- `configure_logging(level: str | None = None, trace: bool | None = None) -> None`:
  - `level` defaults to env var `SIYI_LOG_LEVEL` (else `"INFO"`). Accepts `DEBUG|INFO|WARNING|ERROR`.
  - `trace` defaults to `os.environ.get("SIYI_PROTOCOL_TRACE") == "1"`. When `True`, force level to `DEBUG` and install the `hexdump_processor`.
  - Processors chain: `add_log_level`, `structlog.processors.TimeStamper(fmt="iso", utc=True)`, conditional `hexdump_processor`, `structlog.processors.JSONRenderer()`.
  - `hexdump_processor(logger, method_name, event_dict)`: if key `payload_bytes` present, set `payload_hex = event_dict.pop("payload_bytes").hex(sep=" ")`. Otherwise no-op.
- Module imports only `os`, `logging`, `structlog`, `typing`.
- Must pass `mypy --strict`.

#### `CHANGELOG.md`
Keep-a-Changelog 1.1.0 format:
```
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.0.1] - 2026-04-20
### Added
- Initial project scaffolding (pyproject, CI, empty package layout, logging config).
```

#### `README.md` (skeleton — expanded in Phase 6)
- Project title `# siyi-sdk`
- One-paragraph description
- Placeholder sections: Installation, Quickstart, API Reference, Contributing, Licence.

#### `CONTRIBUTING.md`
- Dev setup: `git clone`, `hatch env create`, `pre-commit install`.
- Running tests: `hatch run test:cov`.
- Linting: `hatch run lint:lint`, `hatch run lint:fmt`.
- Submitting PRs: branch from `main`, ensure CI green, update `CHANGELOG.md [Unreleased]` section.

### Acceptance Criteria (all must pass at end of your session)
- `hatch env create` succeeds.
- `hatch run lint:lint` exits 0.
- `hatch run lint:typecheck` exits 0 (on `siyi_sdk/`).
- `python -c "import siyi_sdk; import siyi_sdk.protocol; import siyi_sdk.transport; import siyi_sdk.commands; from siyi_sdk.logging_config import get_logger, configure_logging"` exits 0.
- `pytest --collect-only` exits 0 with 0 errors.

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
DONE REPORT — siyi-sdk-scaffolding
Files created:    list each with line count
Files modified:   list each with a one-line description of change
Tests added:      N (all passing)
Coverage delta:   +X.X%
Decisions made:   any non-obvious choices with justification
