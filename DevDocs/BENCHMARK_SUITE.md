# Benchmark Suite

`weld_data_workbench.benchmark_suite` is the comprehensive measurement harness for the local welding dataset workbench. It complements the lightweight `weldinfra benchmark` repository-read benchmark with scratch scan, preview, feature, and API measurements.

The suite is intentionally local-first. It does not upload dataset bytes, does not require access to the gated Hugging Face repository once the dataset is present locally, and uses transient workspace directories for derived benchmark state.

## Why this exists

The repository handles a roughly 40 GB multimodal dataset. Small implementation changes can affect several independent costs:

- complete dataset discovery and media probing;
- no-op incremental index refresh;
- SQLite list/detail query latency;
- video/audio/sensor/image preview generation;
- handcrafted feature extraction;
- feature-cache reuse;
- FastAPI request throughput;
- process memory usage.

Without a common machine-readable harness, regressions tend to be judged by subjective UI responsiveness or isolated timing snippets. The benchmark suite records the measurement contract in one JSON report so results can be compared across commits and machines.

## Running it

The module has a standalone CLI and therefore does not require changes to the main command surface:

```bash
python -m weld_data_workbench.benchmark_suite \
  --workspace ~/Datasets/IntelWelding/workspace \
  --output ~/Datasets/IntelWelding/workspace/reports/benchmark-suite.json
```

The default run measures repository queries, two preview samples, four feature samples, and 32 in-process API requests. It does **not** repeat the full 40 GB light scan unless explicitly requested.

To include the expensive scan pair:

```bash
python -m weld_data_workbench.benchmark_suite \
  --workspace ~/Datasets/IntelWelding/workspace \
  --scratch-scan \
  --workers 8
```

The scan stage creates a separate transient workspace that points to the same read-only dataset root. It performs:

1. a complete light-probe build;
2. an immediate no-op incremental rebuild.

The second pass should reuse every unchanged sample. The report includes the full/no-op timing ratio and verifies that the no-op pass performed no new probes.

## Scratch-state policy

By default, all scratch benchmark state is deleted after the report is assembled. This includes:

- scratch index databases;
- generated preview images;
- feature job caches;
- feature CSV outputs.

Use `--keep-scratch` when investigating a regression:

```bash
python -m weld_data_workbench.benchmark_suite \
  --workspace ./workspace \
  --scratch-root /tmp/weld-benchmarks \
  --keep-scratch
```

A unique run directory is created under the supplied parent. The exact path is recorded in the JSON report.

## Preview measurements

Preview timing has two layers.

The modality layer directly measures:

- video poster/contact-sheet generation;
- audio waveform/spectrogram generation;
- sensor plot generation;
- post-weld image thumbnail generation.

The bundle layer measures the normal `PreviewGenerator` path twice:

- cold generation with `force=True`;
- warm cache reuse with `force=False`.

This separates media-processing cost from the cache lookup/manifest cost.

Samples are selected deterministically across the indexed sample order rather than randomly, so repeated runs use the same positions for a fixed dataset snapshot.

## Feature measurements

Each modality is measured separately using the real resumable feature pipeline:

- video;
- audio;
- sensor;
- image.

For each modality, the suite records:

- cold forced extraction wall time;
- samples/second;
- executed jobs/second;
- feature extraction summary;
- immediate warm-cache wall time;
- reused jobs/second;
- warm/cold speedup.

The feature benchmark uses a scratch feature-job SQLite database. It does not invalidate the user's normal feature cache.

## API measurements

The API stage uses FastAPI through `httpx.ASGITransport`. It therefore measures the application/router/repository serialization path without adding TCP scheduling noise.

Requests alternate between:

- `/api/samples`;
- `/api/samples/{sample_id}`.

The report records:

- request count;
- concurrency;
- wall time;
- requests/second;
- successful requests/second;
- mean/P50/P95/max request latency;
- HTTP status counts.

This is not a substitute for a real socket/load-balancer benchmark. It is intended as a stable regression signal for the application read path.

## JSON structure

The top-level report contains:

```text
schema_version
created_at
tool_version
base
scratch_scan
previews
features
api
scratch
warnings
```

`base` is the existing repository benchmark report and therefore carries the git SHA, optional deterministic dataset `snapshot_id`, platform metadata, index size, sample/session/asset counts, query latency, feature-cache state, and peak RSS where the platform exposes it.

The remaining sections are independently skippable. A failed optional stage is represented as `enabled: false` with a reason and is also surfaced in top-level `warnings`. One optional measurement failure therefore does not discard successful measurements from unrelated stages.

## Suggested local protocol

For meaningful comparisons on the real dataset:

1. close heavy unrelated applications;
2. connect the machine to AC power;
3. use the same Python environment and worker count;
4. run one warm-up invocation;
5. run at least three measured invocations;
6. compare medians rather than a single wall time;
7. keep the dataset snapshot ID fixed;
8. record the git commit SHA;
9. do not compare a cold filesystem-cache run with a warm filesystem-cache run as if they were equivalent.

For scan performance work, use `--scratch-scan`. For UI/query work, omit it so iteration remains fast.

## Regression thresholds

Do not hard-code aggressive pass/fail thresholds until several real-machine baselines exist. CI virtual machines have noisy CPU scheduling and storage latency.

A practical progression is:

- first collect report artifacts;
- establish stable medians on the main development machine;
- add generous warning thresholds;
- only later convert mature metrics into CI gates.

Repository correctness tests remain the primary CI gate; benchmark thresholds are a secondary regression signal.

## Dataset safety

The benchmark suite never copies the Intel dataset into Git and never places generated derivative artifacts under the repository by default. Scratch directories contain only local indexes, previews, feature caches, and reports.

The dataset license remains independent from this benchmark code. Do not publish source media, derived samples, or model artifacts if doing so would violate the dataset terms.
