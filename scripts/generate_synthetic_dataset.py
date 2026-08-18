#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from weld_data_workbench.synthetic import generate_synthetic_dataset


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--profile", choices=["tiny", "taxonomy"], default="tiny")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(generate_synthetic_dataset(args.output, profile=args.profile, force=args.force))


if __name__ == "__main__":
    main()
