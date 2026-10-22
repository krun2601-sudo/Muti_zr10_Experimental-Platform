from __future__ import annotations

import argparse
import json
from pathlib import Path

from .mappo_protocol import select_checkpoint


def main(argv=None):
    parser = argparse.ArgumentParser(description="Select MAPPO checkpoint from a training_index.json on validation only")
    parser.add_argument("training_index")
    parser.add_argument("--configs", nargs="+", required=True)
    parser.add_argument("--seeds", nargs="+", type=int, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args(argv)
    index_path = Path(args.training_index).resolve()
    data = json.loads(index_path.read_text(encoding="utf-8"))
    checkpoints = data.get("checkpoints", [])
    if not checkpoints:
        raise ValueError("training index contains no checkpoints")
    result = select_checkpoint(
        checkpoints, args.configs, args.seeds, args.output,
        safe=bool(data.get("safe", False)), device=args.device,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
