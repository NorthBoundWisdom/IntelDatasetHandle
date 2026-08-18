"""Optional path-oriented PyTorch dataset.

Decoding and transforms are supplied by the caller so that research code can select its
own temporal windows, sample rates, and augmentation policy without coupling them to the
indexer.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

try:
    from torch.utils.data import Dataset
except ImportError as exc:  # pragma: no cover - optional dependency
    raise RuntimeError("Install the torch extra: pip install -e '.[torch]'") from exc

from ..index.repository import DatasetRepository


class IndexedWeldDataset(Dataset):
    def __init__(
        self,
        repository: DatasetRepository,
        *,
        split: str | None = None,
        category: str | None = None,
        transform: Callable[[dict[str, Any]], Any] | None = None,
    ):
        self.repository = repository
        self.transform = transform
        self.sample_ids = [
            row["sample_id"]
            for row in repository.iter_samples(split=split, category=category, batch_size=1000)
        ]

    def __len__(self) -> int:
        return len(self.sample_ids)

    def __getitem__(self, index: int) -> Any:
        sample = self.repository.get_sample(self.sample_ids[index])
        if sample is None:
            raise IndexError(index)
        if self.transform is not None:
            return self.transform(sample)
        return sample
