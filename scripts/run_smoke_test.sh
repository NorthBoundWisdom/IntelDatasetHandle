#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-./_demo}"
rm -rf "$ROOT"
weldtool synthetic --output "$ROOT/raw"
weldtool init --dataset-root "$ROOT/raw" --workspace "$ROOT/workspace"
weldtool scan --workspace "$ROOT/workspace" --workers 2 --probe light
weldtool stats --workspace "$ROOT/workspace"
weldtool validate --workspace "$ROOT/workspace" || true
weldtool features --workspace "$ROOT/workspace" --output "$ROOT/workspace/features/features.csv" --workers 2
