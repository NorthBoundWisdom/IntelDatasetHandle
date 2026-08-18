# WeldDataWorkbench

A local-first starter repository for the Intel Robotic Welding Multimodal Dataset and similar multimodal industrial datasets.

The code intentionally separates four concerns:

1. **Raw dataset preservation** — the downloaded and extracted dataset remains read-only.
2. **A reproducible workspace** — SQLite index, validation reports, previews, and feature tables are written outside the raw dataset.
3. **Lazy media access** — 40 GB of media is never loaded eagerly.
4. **Research iteration** — CLI, Python API, FastAPI service, QML desktop UI, feature extraction, and anomaly-detection baselines share one data contract.

> The code in this repository is MIT-licensed. The Intel dataset is not. Intel's dataset card states that the dataset is for research use and should not be used commercially. See `NOTICE_DATASET_LICENSE.md` before using the data.

## Included

- Safe `tar.gz` inspection and extraction.
- Manifest discovery based on expected columns rather than a hard-coded filename.
- Filesystem fallback when the manifest shape differs from expectations.
- SQLite index with `samples`, `assets`, and `issues` tables.
- Lightweight media probing for AVI, FLAC, CSV time series, and post-weld images.
- Data integrity checks, split checks, category normalization, and JSON/CSV reports.
- Cached video contact sheets, audio waveform/spectrogram images, sensor plots, and image thumbnails.
- CLI and Python API.
- FastAPI read-only service.
- Native Qt QML dataset browser backed by the loopback-only FastAPI service.
- Modality-level handcrafted feature extraction.
- Isolation Forest baseline and late-fusion utility.
- Synthetic mini-dataset generator for development before the 39.9 GB archive finishes downloading.
- Tests and GitHub Actions CI.

## Quick start

```bash
cd IntelDatasetHandle
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[all,dev]"
```

The desktop browser uses the installed Qt `qml` and Qt Multimedia runtimes, not
PySide. User-specific Qt and dataset paths are stored in both
`source_roots.lock.jsonc.in` and `source_roots.lock.jsonc`.

## FreeCM buttons

FreeCM discovers [the repository command manifest](configs/freecm.commands.jsonc)
and exposes these project buttons:

- **Init** prepares/reuses `.venv`, installs dependencies only when the
  `pyproject.toml` receipt is missing or stale, and initializes FreeCM state.
- **Config** runs the standard `source_root_workflow.py --update`, applies the
  active lock's `AppConfigs`, refreshes the real light-probe index, and writes
  the ignored `build/freecm/configured.json` readiness receipt. It does not run
  pip.
- **Build** compiles the native Qt launcher (including `setWindowIcon()`), runs
  `qmllint`, builds a wheel, and verifies that the native QML resources are
  packaged without the removed PySide bridge.
- **Run** starts a loopback API on an available port and launches the installed
  native `qml` executable with embedded Qt Multimedia audio/video playback;
  closing QML also stops the API process.
- **Test** runs Ruff, formatting, compilation, and the complete pytest suite.

Initialize the checked-in FreeCM submodule, environment, and locks with:

```bash
git submodule update --init --recursive FreeCM
python3 configs/source_root_workflow.py --init  # environment install/reuse
python3 configs/source_root_workflow.py --update
```

Edit `AppConfigs` in both lock files when changing `WELD_QML_RUNTIME`,
`WELD_DATASET_HOME`, `WELD_DATASET_ROOT`, `WELD_DATASET_ARCHIVE`,
`WELD_EXTRACTED_ROOT`, `WELD_WORKSPACE`, or `WELD_SCAN_WORKERS`. The reviewed
`.in` template is tracked; the active `.json` lock is machine-local and ignored,
and `--init` creates it from the template when absent.

Generate a small synthetic dataset and exercise the complete local workflow:

```bash
weldtool synthetic --output ./_demo/raw
weldtool init --dataset-root ./_demo/raw --workspace ./_demo/workspace
weldtool scan --workspace ./_demo/workspace
weldtool stats --workspace ./_demo/workspace
weldtool validate --workspace ./_demo/workspace
weldtool preview --workspace ./_demo/workspace --sample-id good_train_001
weldtool gui --workspace ./_demo/workspace
```

For the real dataset after extraction, point the workspace at the directory that
contains the discovered manifest. In the archive audited on 2026-08-18, that is:

```bash
DATASET_HOME="$HOME/Datasets/IntelWelding"

weldtool init \
  --dataset-root "$DATASET_HOME/extracted/raid/intel_robotic_welding_dataset" \
  --workspace "$DATASET_HOME/workspace"

weldtool scan \
  --workspace "$DATASET_HOME/workspace" \
  --workers 8 \
  --probe light

weldtool validate --workspace "$DATASET_HOME/workspace"
weldtool stats --workspace "$DATASET_HOME/workspace"
weldtool gui --workspace "$DATASET_HOME/workspace"
```

The manifest resolver also supports pointing `--dataset-root` at a wrapper
extraction directory. It resolves paths relative to the discovered manifest and
accepts both `SUBDIRS=sample` and already-prefixed `SUBDIRS=session/sample`
layouts without duplicating `DIRECTORY`.

The scanner is deliberately tolerant. It records incomplete or corrupt samples as issues instead of aborting the whole run, which is useful while an archive is still being extracted.

## Archive utilities

List archive contents without extracting:

```bash
weldtool archive-list ~/Datasets/IntelWelding/intel_robotic_welding_dataset.tar.gz \
  --limit 200
```

Safely extract while rejecting path traversal entries:

```bash
weldtool extract \
  ~/Datasets/IntelWelding/intel_robotic_welding_dataset.tar.gz \
  ~/Datasets/IntelWelding/extracted
```

## Workspace layout

```text
workspace/
├── workbench.yaml
├── index.sqlite3
├── reports/
│   ├── validation.json
│   ├── validation.csv
│   └── stats.json
├── previews/
│   └── <sample-id>/...
├── features/
│   └── features.csv or features.parquet
└── models/
```

No generated file is written inside the raw dataset directory unless you explicitly use the same path for both locations.

## Main commands

```text
weldtool init           Create workspace configuration
weldtool scan           Discover, probe, and index samples
weldtool stats          Show dataset/category/split/health statistics
weldtool validate       Run integrity and split checks
weldtool preview        Generate cached previews for one sample
weldtool export-index   Export indexed metadata to JSONL/CSV/Parquet
weldtool features       Extract lightweight modality features
weldtool baseline       Train/evaluate a tabular anomaly baseline
weldtool serve          Start the read-only FastAPI service
weldtool gui            Start the native Qt QML browser and loopback API
weldtool synthetic      Generate a development dataset
weldtool archive-list   Inspect a tar archive
weldtool extract        Safely extract a tar archive
```

Run `weldtool <command> --help` for detailed options.

## Python API

```python
from pathlib import Path

from weld_data_workbench.config import load_config
from weld_data_workbench.index.repository import DatasetRepository

config = load_config(Path("~/Datasets/IntelWelding/workspace").expanduser())
repo = DatasetRepository(config.index_path, config.dataset_root)

print(repo.stats())
for sample in repo.list_samples(category="Porosity", split="test", limit=10):
    print(sample["sample_id"], sample["relpath"])
```

See `examples/python_api.py` and `notebooks/01_dataset_overview.ipynb`.

## Design notes

The public dataset card and paper are not completely consistent about audio sampling rate: the card currently says 16 kHz, while the paper describes the original recordings as 192 kHz. This project reads the actual FLAC metadata and does not hard-code either value.

The paper's anomaly-detection protocol trains only on `Good` samples in the training partition and evaluates defects in validation/test. The baseline command follows that protocol when the manifest provides compatible labels and splits.

The audited public archive contains 4,040 samples in 236 session directories.
All 4,040 FLAC files report mono 16 kHz PCM-16 audio. See
`DevDocs/DATASET_NOTES.md` for the complete local audit, including three source
samples with missing post-weld images and the official split's session-overlap
warning.

## Development

```bash
make test
make lint
make synthetic-smoke
```

Start with:

- `DevDocs/ARCHITECTURE.md`
- `DevDocs/DATA_CONTRACT.md`
- `DevDocs/DATASET_NOTES.md`
- `DevDocs/RESEARCH_BASELINES.md`
- `TODO.md`
