from __future__ import annotations

import argparse
from pathlib import Path

from weld_data_workbench.config import load_config
from weld_data_workbench.index.repository import DatasetRepository
from weld_data_workbench.previews.generator import PreviewGenerator


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace", type=Path)
    args = parser.parse_args()

    config = load_config(args.workspace)
    repository = DatasetRepository(config.index_path, config.dataset_root)

    print(repository.stats())
    samples = repository.list_samples(split="test", limit=5)
    for sample in samples:
        print(sample["sample_id"], sample["category"], sample["relpath"])

    if samples:
        sample_id = samples[0]["sample_id"]
        detail = repository.get_sample(sample_id)
        print(detail)
        print(PreviewGenerator(config, repository).generate(sample_id))


if __name__ == "__main__":
    main()
