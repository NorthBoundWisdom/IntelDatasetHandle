#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from huggingface_hub import hf_hub_download


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    args.destination.mkdir(parents=True, exist_ok=True)
    path = hf_hub_download(
        repo_id="IntelLabs/Intel_Robotic_Welding_Multimodal_Dataset",
        filename="intel_robotic_welding_dataset.tar.gz",
        repo_type="dataset",
        local_dir=args.destination,
    )
    print(path)


if __name__ == "__main__":
    main()
