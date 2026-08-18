# Test Report

Date: 2026-08-18

## Delivered scope

The repository covers archive handling, dataset discovery, manifest parsing,
media probing, SQLite indexing, validation, preview generation, feature
extraction, a lightweight anomaly-detection baseline, a FastAPI service, a
native Qt QML browser, synthetic fixtures, tests, and developer documentation.

## Automated checks executed

### Lint and Python compilation

```text
.venv/bin/ruff check src tests scripts configs
.venv/bin/python -m compileall -q src scripts tests configs
Result: both passed
```

### Unit and integration tests

```text
.venv/bin/python -m pytest -q
Result: 21 passed, 1 dependency deprecation warning (3.02s final run)
```

The warning originates in FastAPI/Starlette's test-client compatibility layer;
the API test itself passes.

Covered behavior includes:

- safe archive extraction and path-traversal rejection;
- manifest detection and category normalization;
- synthetic dataset scanning and SQLite repository queries;
- media/integrity validation;
- preview generation;
- modality feature extraction;
- tabular anomaly baseline execution;
- FastAPI health, statistics, sample-list, and sample-detail endpoints.

### Packaging verification

```text
python3 configs/workbench_workflow.py build
Result: passed
```

The FreeCM Build action first compiled the native `demo_qml_launcher` with Qt
6.11.2 and `QGuiApplication::setWindowIcon()`, then passed Qt 6.11.2 `qmllint`
and produced a wheel
containing `Main.qml` and its components. It also verified that removed PySide
controller/model modules were absent from the clean build.

### End-to-end synthetic smoke run

The following workflow was executed against a generated 14-sample, 9-session mini dataset:

```text
weldtool synthetic
weldtool init
weldtool scan
weldtool validate
weldtool stats
```

Observed result:

- 14 samples indexed;
- 112 media assets indexed;
- no scanner failures;
- validation completed successfully, with only expected informational/warning findings caused by the intentionally small synthetic category set;
- feature extraction, Isolation Forest, preview, repository, and API paths also
  passed against the synthetic fixture in the automated test suite.

## Real dataset integration

The 39,939,194,323-byte archive was safely extracted outside the repository and
indexed with `--probe light`. The result was 4,040 samples, 236 sessions, and
32,305 readable present assets. A complete preview bundle was generated from a
real Good/train sample, covering video, audio, sensor, and image paths.

The only asset-level findings are three samples that contain no post-weld
images: three `missing_image` errors and three `unexpected_image_count`
warnings. Validation also reports that 216 session IDs cross official splits.
These are source-data/split properties, not scanner failures. Full counts and
media metadata are recorded in `DevDocs/DATASET_NOTES.md`.

The standard FreeCM `--init` and `--update` workflows completed successfully.
`--update` applied all user settings from `source_roots.lock.jsonc`, reused the
real workspace, and refreshed all 4,040 samples. The native QML smoke loaded Qt
Multimedia with its FFmpeg 7.1.5 backend, received HTTP 200 from health, stats,
and the 1,000-sample page, exited on schedule, and shut down the API child
cleanly.

## Known verification limits

- Qt Multimedia is connected for embedded audio/video playback, but codec
  behavior still depends on the target machine's FFmpeg backend.
- Exact sensor units and synchronization-marker semantics are not encoded unambiguously in the CSV headers and still require upstream confirmation.
- The included ML baseline is an engineering smoke baseline, not a reproduction of Intel's paper results.
