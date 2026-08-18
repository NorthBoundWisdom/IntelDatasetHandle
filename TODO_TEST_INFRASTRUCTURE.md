# Test and Infrastructure Roadmap

This roadmap captures the next phase after the first successful integration with the real Intel Robotic Welding Multimodal Dataset. The repository already has a working local-first indexer, validation pipeline, preview/feature generation, FastAPI adapter, native QML browser, synthetic fixtures, and a lightweight anomaly baseline. The next goal is to make the data and experiment pipeline reproducible, failure-tolerant, leakage-aware, measurable, and suitable for sustained research work.

## Current baseline

- Real public archive audited: 4,040 samples across 236 sessions.
- Real light-probe scan succeeds for all present AVI, FLAC, CSV, and JPEG assets.
- Three source samples have no post-weld images; these are source-data findings rather than scanner failures.
- Public FLAC assets are mono 16 kHz PCM-16.
- The upstream train/validation/test counts match the paper, but 216 session IDs cross official split boundaries.
- CLI, SQLite repository, validation, preview generation, handcrafted features, Isolation Forest baseline, FastAPI, native QML, FreeCM workflow, and synthetic smoke tests are already present.

The high-level rule for the next phase is: **do not optimize research metrics until the dataset snapshot, split semantics, provenance, and evaluation contracts are reproducible.**

---

## P0-A — CI and quality gates

- [ ] Add GitHub Actions CI for Linux on Python 3.11, 3.12, and 3.13.
- [ ] Run Ruff, formatting checks, mypy, compileall, pytest, and the synthetic smoke workflow in CI.
- [ ] Build a wheel and install it into a clean environment as a packaging smoke test.
- [ ] Add a macOS job for native Qt/QML launcher and `qmllint` smoke when Qt is available.
- [ ] Produce a pytest coverage report and introduce a pragmatic core-package coverage gate; GUI/QML code may remain excluded initially.
- [ ] Cache pip artifacts without caching generated dataset/workspace state.

### Exit criteria

Every change to `main` is automatically checked without access to the gated Intel dataset, and a clean wheel can execute the synthetic end-to-end workflow.

---

## P0-B — deterministic dataset snapshots and provenance

- [ ] Add `weldtool snapshot create` and `weldtool snapshot verify`.
- [ ] Define a deterministic snapshot document containing:
  - schema version;
  - manifest relative path and SHA-256;
  - archive SHA-256 when known/provided;
  - index database hash or canonical content hash;
  - sample/session/asset counts;
  - category × split distribution;
  - modality counts and missingness;
  - audio sample-rate/channel distribution;
  - video codec/FPS/resolution distribution;
  - sensor column/schema distribution;
  - creation tool version.
- [ ] Derive a stable `snapshot_id` from canonical snapshot content rather than timestamps.
- [ ] Make experiment outputs reference `snapshot_id` instead of only a filesystem path.
- [ ] Add verification failures for changed manifest, changed index semantics, missing files, and incompatible schema versions.

### Exit criteria

A researcher can prove exactly which indexed dataset state an experiment used, and rerunning snapshot generation without data changes produces the same identity.

---

## P0-C — crash safety, restartability, and incremental indexing

- [ ] Add incremental re-indexing keyed by stable asset fingerprints (`relpath`, size, mtime, optional SHA-256).
- [ ] Preserve the existing atomic `index.sqlite3.building -> index.sqlite3` replacement contract.
- [ ] Add failure-injection tests for:
  - exception after the Nth sample;
  - codec/probe failure;
  - SQLite write failure;
  - stale `.building` database;
  - interrupted scan;
  - old index being read while a replacement is built.
- [ ] Verify that any failed rebuild leaves the previous index queryable.
- [ ] Make a no-op incremental scan avoid reopening unchanged media codecs.
- [ ] Record scan statistics: reused, reprobed, added, removed, failed.

### Exit criteria

A 40 GB workspace can be refreshed repeatedly without throwing away valid work, and changing one asset does not force a complete re-probe.

---

## P0-D — real-schema regression fixture

- [ ] Add an anonymized/generated mini fixture whose manifest/path/schema shape mirrors the audited public archive.
- [ ] Preserve the real sensor column names and representative 30/31 FPS behavior without committing Intel media.
- [ ] Add intentionally malformed variants:
  - missing five-image bundle;
  - corrupt AVI/FLAC/CSV/JPEG;
  - duplicate sample basename;
  - extra/unknown sensor columns;
  - missing sensor columns;
  - unexpected audio rate;
  - session crossing splits.
- [ ] Add golden assertions for normalized stats and validation issue codes.
- [ ] Never commit real Intel samples, screenshots, derived previews, or trained checkpoints.

### Exit criteria

Scanner/data-contract regressions that would break the real archive are caught in public CI using generated test data only.

---

## P0-E — leakage-resistant split infrastructure

The published split remains an immutable upstream annotation. Experimental splits are separate data.

- [ ] Add explicit `upstream_split` versus `experiment_split` semantics.
- [ ] Add a leakage audit reporting sessions, exact duplicates, and near-duplicates that cross partitions.
- [ ] Add deterministic session-disjoint holdout generation with an explicit random seed.
- [ ] Add session-grouped K-fold utilities.
- [ ] Preserve category balance as far as possible while keeping whole sessions together.
- [ ] Export split assignments as standalone versioned artifacts rather than rewriting raw annotations.
- [ ] Report both official-split and session-disjoint metrics when comparing research baselines.

### Exit criteria

No experiment can accidentally claim session-independent generalization while training and evaluation contain samples from the same acquisition session.

---

## P1-A — resumable derivative/feature job system

- [ ] Replace monolithic feature extraction with per-sample job state.
- [ ] Cache key = sample fingerprint + extractor name + extractor version + canonical extractor config hash.
- [ ] Track `pending`, `running`, `success`, `failed`, and `stale` states.
- [ ] Resume after process interruption without recomputing completed samples.
- [ ] Isolate failures so a corrupt sample does not abort unrelated extraction.
- [ ] Allow per-modality invalidation; changing the audio extractor must not invalidate image/video features.
- [ ] Use bounded process/device queues for CPU/GPU-heavy learned extractors instead of extending the current thread pool indiscriminately.

### Exit criteria

Repeated feature runs are near no-op when nothing changes, and a single changed/corrupt asset causes only the affected derivative work to rerun/fail.

---

## P1-B — benchmark and regression harness

- [ ] Add `weldtool benchmark` with machine-readable JSON output.
- [ ] Measure:
  - full light-scan wall time;
  - no-op incremental-scan wall time;
  - peak RSS;
  - SQLite size;
  - sample-list and sample-detail P50/P95 latency;
  - preview-generation latency by modality;
  - handcrafted/learned feature throughput;
  - API concurrent read throughput.
- [ ] Use a generated large synthetic fixture in CI and the real 40 GB dataset only in local/nightly runs.
- [ ] Store benchmark metadata with platform, Python version, git SHA, and snapshot ID.
- [ ] Add regression thresholds only after stable baselines are collected.

---

## P1-C — multimodal alignment diagnostics

- [ ] Add a normalized time-axis abstraction for video, audio, and sensor streams.
- [ ] Estimate welding onset/end from:
  - sensor current/voltage transitions;
  - audio energy onset;
  - video illumination/arc onset.
- [ ] Estimate and report per-modality offsets and confidence.
- [ ] Build a synthetic alignment fixture with known offsets and bounded expected error.
- [ ] Add alignment quality plots/reports.
- [ ] Do not silently shift raw data; alignment is an explicit derived transform.

---

## P1-D — QML workbench testability and analysis UX

- [ ] Move preview/feature jobs to cancellable background tasks.
- [ ] Add synchronized video/audio/sensor timeline playback.
- [ ] Add Good-versus-defect compare mode matched by process parameters.
- [ ] Add histogram/pivot exploration by category, weld type, steel, thickness, split, and session.
- [ ] Add issue triage and user annotations in a separate overlay database.
- [ ] Add API disconnect/reconnect behavior and visible task/error state.
- [ ] Add QML/offscreen tests for filtering, pagination, selection, seek, media errors, and shutdown.
- [ ] Add macOS and Windows packaging smoke tests.

---

## P2-A — experiment registry and evaluation contract

Use a lightweight repository-native experiment format before introducing a heavier service such as MLflow.

Each experiment should persist:

```text
experiments/<experiment-id>/
├── config.yaml
├── provenance.json
├── predictions.parquet
├── metrics.json
├── environment.json
└── artifacts/          # lightweight generated plots only
```

`provenance.json` should include at least:

- dataset `snapshot_id`;
- split artifact ID/hash;
- git commit SHA;
- Python/package environment;
- model/extractor versions;
- random seeds;
- training/tuning/evaluation partition policy.

The unified evaluator should report:

- ROC AUC overall and by defect category;
- PR AUC;
- equal-error rate;
- false-negative rate at fixed false-positive rates;
- threshold drift by session/weld/material/thickness;
- bootstrap confidence intervals grouped by session;
- missing-modality robustness;
- inference latency and memory where applicable.

---

## P2-B — stronger unimodal baselines

Only after P0/P1 provenance and leakage controls are stable:

- [ ] Audio log-STFT + bounded convolutional/shallow autoencoder baseline.
- [ ] Sensor-only statistical and temporal baselines.
- [ ] Frozen maintained video embedding + reconstruction/density baseline.
- [ ] Frozen post-weld-image embedding + nearest-neighbor/anomaly baseline.
- [ ] Common prediction schema for every modality.
- [ ] Calibration strictly on train/validation, never test.

---

## P2-C — multimodal fusion

- [ ] Standardize unimodal scores using Good training data only.
- [ ] Reproduce simple fixed late fusion first.
- [ ] Tune convex fusion weights on validation only.
- [ ] Add reliability-aware/missing-modality fusion.
- [ ] Add learned fusion only after unimodal baselines are independently validated.
- [ ] Report unimodal and fused results side by side for both official and session-disjoint split policies.

---

## P3 — online/edge simulation

- [ ] Add a dataset replay service without coupling it to the indexer.
- [ ] Add RTSP-compatible video replay and MQTT-compatible sensor/audio metadata transport where useful.
- [ ] Define a stable online anomaly event schema and operator-feedback schema.
- [ ] Add end-to-end latency/throughput/failure-injection tests.
- [ ] Add ONNX/OpenVINO export adapters only after research correctness is stable.
- [ ] Keep any commercial-use work blocked until dataset/model licensing is resolved in writing.

---

## Recommended implementation order

1. CI + type/coverage/package gates.
2. Dataset snapshot/provenance.
3. Real-schema generated fixture and golden validation tests.
4. Session leakage audit and deterministic group splits.
5. Incremental/restartable scan and feature cache.
6. Benchmark harness.
7. Multimodal alignment and synchronized QML timeline.
8. Experiment registry/evaluator.
9. Stronger unimodal baselines.
10. Multimodal fusion and online replay.

The immediate development target is **P0-A through P0-E**. Those items create the safety and reproducibility boundary required for all later model work.