"""Optional PyTorch building blocks for later research experiments.

This module is intentionally not imported by the core package. Install the optional
`torch` extra before using it. The initial implementation is a generic feature-vector
autoencoder, not a reproduction of Intel's audio/video models.
"""

from __future__ import annotations

try:
    import torch
    from torch import nn
except ImportError as exc:  # pragma: no cover - optional dependency
    raise RuntimeError("Install the torch extra: pip install -e '.[torch]'") from exc


class FeatureAutoencoder(nn.Module):
    def __init__(self, input_dim: int, bottleneck_dim: int = 32, dropout: float = 0.1):
        super().__init__()
        hidden = max(64, min(512, input_dim * 2))
        middle = max(bottleneck_dim * 2, hidden // 2)
        self.encoder = nn.Sequential(
            nn.Linear(input_dim, hidden),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden, middle),
            nn.ReLU(),
            nn.Linear(middle, bottleneck_dim),
        )
        self.decoder = nn.Sequential(
            nn.Linear(bottleneck_dim, middle),
            nn.ReLU(),
            nn.Linear(middle, hidden),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden, input_dim),
        )

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        return self.decoder(self.encoder(inputs))

    def anomaly_score(self, inputs: torch.Tensor) -> torch.Tensor:
        reconstruction = self(inputs)
        return torch.mean(torch.square(inputs - reconstruction), dim=-1)
