#!/usr/bin/env python3
from __future__ import annotations

import argparse
import random
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Create deterministic SFT train/validation splits.")
    parser.add_argument("path", type=Path)
    parser.add_argument("--val-ratio", type=float, default=0.05)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rows = [line for line in args.path.read_text(encoding="utf-8").splitlines() if line.strip()]
    indexed = list(enumerate(rows))
    random.Random(args.seed).shuffle(indexed)
    if len(indexed) <= 1:
        val_count = 0
    else:
        val_count = max(1, min(len(indexed) - 1, round(len(indexed) * args.val_ratio)))
    val_indexes = {index for index, _row in indexed[:val_count]}
    train_rows = [row for index, row in enumerate(rows) if index not in val_indexes]
    val_rows = [row for index, row in enumerate(rows) if index in val_indexes]

    train_path = args.path.with_name(args.path.stem + ".train" + args.path.suffix)
    val_path = args.path.with_name(args.path.stem + ".val" + args.path.suffix)
    train_path.write_text("\n".join(train_rows) + ("\n" if train_rows else ""), encoding="utf-8")
    val_path.write_text("\n".join(val_rows) + ("\n" if val_rows else ""), encoding="utf-8")
    print(f"source={len(rows)} train={len(train_rows)} val={len(val_rows)} seed={args.seed} val_ratio={args.val_ratio}")
    print(f"train={train_path}")
    print(f"val={val_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
