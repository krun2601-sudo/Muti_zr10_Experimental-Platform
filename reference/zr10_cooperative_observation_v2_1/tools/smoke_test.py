from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import asyncio
from pathlib import Path

from zr10_coop.config import load_config
from zr10_coop.manager import CooperativeObservationSystem
from zr10_coop.policies import build_policy


async def main() -> None:
    root = Path(__file__).resolve().parents[1]
    config = load_config(root / "config" / "three_zr10.yaml")
    config.system.duration_s = 1.5
    config.system.control_rate_hz = 5.0
    policy = build_policy(config.policy)
    system = CooperativeObservationSystem(config, policy, dry_run=True)
    log_dir = await system.run()
    telemetry = log_dir / "telemetry.csv"
    events = log_dir / "events.csv"
    assert telemetry.exists() and telemetry.stat().st_size > 0
    assert events.exists() and events.stat().st_size > 0
    print(f"Smoke test passed: {log_dir}")


if __name__ == "__main__":
    asyncio.run(main())
