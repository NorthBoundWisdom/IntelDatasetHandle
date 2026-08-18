# Architecture

## 1. Goals

WeldDataWorkbench is not a monolithic training application. It is a local data-engineering boundary around a large, gated, multimodal dataset.

The core architectural constraints are:

- Raw data remains immutable and outside Git.
- Indexing is restartable and failure-isolated at sample granularity.
- Media is accessed lazily.
- Persisted metadata has a stable schema.
- CLI, API, QML, notebooks, and ML experiments query the same repository layer.
- Dataset-specific assumptions are explicit and validated rather than embedded in UI or model code.

## 2. Data flow

```text
Hugging Face archive
        │
        ├── archive-list / safe extraction
        ▼
Read-only extracted dataset root
        │
        ├── manifest discovery and parsing
        ├── filesystem sample discovery
        ├── bounded media probes
        └── structured issues
        ▼
Atomic SQLite index
        │
        ├── DatasetRepository
        │      ├── CLI
        │      ├── FastAPI
        │      ├── QML controller/model
        │      ├── preview generator
        │      └── feature extractor
        ▼
Workspace derivatives
        ├── validation reports
        ├── cached previews
        ├── feature tables
        └── research model outputs
```

## 3. Raw-data boundary

`dataset_root` is treated as read-only. The only supported writer acting on the raw-data side is the explicit archive extractor, whose destination is chosen by the user.

All derived content belongs under `workspace_root`:

- `index.sqlite3`
- `reports/`
- `previews/`
- `features/`
- `models/`

This prevents feature code, notebooks, or UI actions from silently contaminating or partially rewriting the original dataset.

## 4. Discovery strategy

### 4.1 Manifest detection

The manifest filename is intentionally not hard-coded. Candidate delimited files near the dataset root are scored using the public expected columns:

```text
CATEGORY, WELD_TYPE, THICKNESS_MM, STEEL_TYPE, SAMPLES,
CURRENT_A, VOLTAGE_V, GAS_BAR, ROBOT_SPEED_CPM,
DIRECTORY, SUBDIRS, SPLIT
```

A candidate must include `CATEGORY` and enough additional path/split/process fields to avoid accidentally selecting a sensor CSV.

Sample paths are resolved relative to the discovered manifest directory first,
with the configured dataset root as a compatibility fallback. The resolver
accepts both a directory-relative `SUBDIRS=sample` value and an already-prefixed
`SUBDIRS=session/sample` value; it never blindly concatenates both fields.

### 4.2 Filesystem fallback

A directory is considered a sample candidate when it contains at least two expected modalities and is not an `images` directory. Filesystem discovery is merged with manifest-derived paths. Exact path matches are preferred; a unique basename match is a fallback for manifest prefix differences.

This tolerant strategy is retained after the real-archive audit because it
supports wrapper extraction directories and related datasets without coupling
the scanner to Intel's current archive root or manifest filename.

## 5. Probe levels

- `none`: classify and stat assets without opening codecs.
- `light`: read headers/metadata and verify that codecs can open assets.
- `full`: additionally decode bounded media fragments and inspect more sensor/image detail.

`full` still does not decode entire videos or load the complete dataset.

## 6. Persistence

The index is built into `index.sqlite3.building`. Only after all futures complete and SQLite is checkpointed is the temporary database atomically renamed over the active index.

A failed build therefore leaves the previous valid index intact.

The database has three primary tables:

- `samples`: annotation/process metadata and primary-asset shortcuts.
- `assets`: one row per video, audio, sensor, or image file.
- `issues`: structured discovery/probe problems.

See `DATA_CONTRACT.md` for field semantics.

## 7. Repository layer

`DatasetRepository` owns all read queries. Adapters must not issue ad hoc filesystem scans:

- QML requests a filtered page from the repository.
- FastAPI resolves only assets present in the index.
- Preview generation receives full sample details from the repository.
- Feature extraction iterates indexed sample IDs.

This makes UI and experiment behavior reproducible against a specific index snapshot.

## 8. Preview generation

Previews are generated on demand per sample and cached by an asset fingerprint made from relative path, size, and mtime.

Current derivatives:

- Video middle-frame poster and contact sheet.
- Audio waveform and bounded spectrogram.
- Sensor line plot for a bounded row/column subset.
- Resized post-weld image thumbnails.

The QML UI never needs to decode all modalities itself.

## 9. Feature pipeline

The initial feature extractor is deliberately lightweight. It produces deterministic, inspectable features from bounded media samples:

- Audio amplitude/spectral statistics.
- Video appearance/motion statistics from uniformly sampled frames.
- Sensor per-column distribution and derivative statistics.
- Post-weld image appearance/sharpness/edge statistics.

This is enough to verify the data contract and construct a tabular anomaly baseline. It is not intended to replace learned audio/video representations.

## 10. Optional adapters

Core package imports do not require PySide6, FastAPI, scikit-learn, PyTorch, or Hugging Face Hub. Optional imports are restricted to their adapter modules and commands.

This keeps indexing usable in headless environments and reduces installation risk.

## 11. Concurrency

- Dataset probing uses a `ThreadPoolExecutor`; codecs and filesystem reads are I/O-heavy.
- Feature extraction uses a separate bounded thread pool.
- SQLite writes remain on the builder thread.
- QML preview/index operations execute through `QThreadPool` to avoid blocking the UI.

Future CPU/GPU-heavy learned feature extraction should use process workers or explicit device queues rather than extending the current thread pool indiscriminately.
