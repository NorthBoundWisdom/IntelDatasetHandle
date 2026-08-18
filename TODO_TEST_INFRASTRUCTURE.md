# Test and Infrastructure Roadmap

This roadmap tracks the infrastructure phase after the first successful integration with the real Intel Robotic Welding Multimodal Dataset. The goal is to keep the data and experiment pipeline reproducible, failure-tolerant, leakage-aware, measurable, and suitable for sustained research work.

## Current baseline

- Real public archive audited: 4,040 samples across 236 sessions.
- Real light-probe scan succeeds for all present AVI, FLAC, CSV, and JPEG assets.
- Three source samples have no post-weld images; these are source-data findings rather than scanner failures.
- Public FLAC assets are mono 16 kHz PCM-16.
- The upstream train/validation/test counts match the paper, but 216 session IDs cross official split boundaries.
- CLI, SQLite repository, validation, preview generation, resumable handcrafted features, Isolation Forest baseline, FastAPI, native QML, FreeCM workflow, experiment/evaluation utilities, and synthetic/real-schema fixtures are present.
- Public CI currently runs Linux Python 3.11/3.12/3.13, Ruff, formatting, compileall, scoped mypy, pytest with an 80% core coverage gate, synthetic smoke, wheel build, and clean-wheel CLI smoke.

The high-level rule remains: **do not optimize research metrics until dataset identity, split semantics, provenance, and evaluation contracts are reproducible.**

---

## P0-A — CI and quality gates

- [x] Add GitHub Actions CI for Linux on Python 3.11, 3.12, and 3.13.
- [x] Run Ruff, formatting checks, scoped infrastructure mypy, compileall, pytest, and the synthetic smoke workflow in CI.
- [x] Build a wheel and install it into a clean environment as a packaging smoke test.
- [ ] Add a macOS job for native Qt/QML launcher and `qmllint` smoke when Qt is available.
- [x] Produce pytest coverage reports and enforce an 80% core-package coverage gate; command adapters/QML and optional torch-only modules are excluded from the initial denominator.
- [x] Cache pip artifacts without caching generated dataset/workspace state.

### Exit criteria

Linux/headless core code has a public CI gate without access to the gated Intel dataset. Remaining P0-A work is native Qt/QML CI coverage on macOS.

---

## P0-B — deterministic dataset snapshots and provenance

- [x] Add `weldinfra snapshot-create` and `weldinfra snapshot-verify`.
- [x] Define a deterministic snapshot document containing:
  - schema version;
  - manifest relative path and SHA-256;
  - archive SHA-256 when explicitly supplied;
  - canonical semantic index hash;
  - sample/session/asset counts;
  - category × split distribution;
  - modality counts and missingness;
  - audio sample-rate/channel distribution;
  - video codec/FPS/resolution distribution;
  - sensor schema distribution;
  - live indexed-asset stat integrity;
  - creation tool version.
- [x] Derive a stable `snapshot_id` from canonical snapshot content rather than timestamps or raw SQLite page bytes.
- [x] Make experiment provenance reference `snapshot_id` rather than only a filesystem path.
- [x] Detect changed manifest/index semantics and live missing/stat-drifted assets during snapshot verification.

### Exit criteria

Delivered for the indexed/local dataset boundary. Snapshot verification intentionally does not hash all 40 GB of media by default; full asset SHA-256 remains an explicit expensive scan option.

---

## P0-C — crash safety, restartability, and incremental indexing

- [x] Add incremental re-indexing keyed by indexed metadata plus live asset `relpath`, size, mtime, and optional trusted SHA-256.
- [x] Preserve the atomic `index.sqlite3.building -> index.sqlite3` replacement contract.
- [x] Add failure/restart tests covering SQLite write failure, stale `.building`, `KeyboardInterrupt`, and reading the old active index while a replacement is built.
- [x] Keep probe/codec failure isolated to the affected candidate rather than aborting unrelated samples.
- [x] Verify that failed/interrupted rebuilds leave the previous index queryable and remove temporary WAL/SHM/building files.
- [x] Make a no-op incremental scan avoid reopening unchanged media codecs.
- [x] Record scan statistics for reused, reprobed, removed, and failed samples.
- [ ] Add an explicit `added_sample_count` field to the build summary rather than inferring it from discovery/reuse statistics.

### Exit criteria

The core restart/atomicity contract is implemented. Remaining work is mostly reporting refinement and real-dataset performance measurement.

---

## P0-D — real-schema regression fixture

- [x] Add a generated mini fixture whose manifest/path/schema shape mirrors the audited public archive and contains no Intel media bytes.
- [x] Preserve audited sensor column names and representative 30/31 FPS behavior.
- [x] Include malformed/edge variants:
  - missing five-image bundle;
  - corrupt AVI/FLAC/CSV/JPEG;
  - duplicate sample basename across sessions;
  - extra/unknown sensor columns;
  - missing sensor columns;
  - unexpected audio rate;
  - session crossing splits.
- [x] Add regression assertions for normalized counts, path semantics, duplicate basename handling, and stable issue codes.
- [x] Keep real Intel samples, screenshots, derived previews, and trained checkpoints out of Git.

### Exit criteria

Delivered for current audited schema. Extend the fixture whenever a new real-archive edge case is discovered.

---

## P0-E — leakage-resistant split infrastructure

The published `split` remains immutable upstream annotation; experimental assignments are standalone artifacts.

- [x] Keep upstream split annotations separate from generated experimental split artifacts.
- [x] Add leakage audit for sessions crossing partitions and exact asset hashes when SHA-256 is available.
- [ ] Add scalable near-duplicate detection across partitions; exact hashes alone are insufficient for acquisition leakage.
- [x] Add deterministic session-disjoint holdout generation with explicit random seed.
- [x] Add session-grouped K-fold utilities.
- [x] Add a deterministic balanced holdout heuristic that keeps whole sessions while approximating sample/category targets; retain hash assignment as a simpler fallback.
- [x] Export split assignments as versioned standalone artifacts rather than rewriting raw annotations.
- [ ] Add a top-level comparison report that evaluates one prediction set under official-split and session-disjoint policies side by side.

### Exit criteria

The split generator prevents direct session overlap. Near-duplicate detection and paired official-vs-grouped result reporting remain open.

---

## P1-A — resumable derivative/feature job system

- [x] Replace monolithic feature extraction with persistent per-sample/per-modality job state in a separate workspace SQLite database.
- [x] Cache key = live modality fingerprint + extractor name + extractor version + canonical extractor config hash.
- [x] Track `pending`, `running`, `success`, `failed`, and `stale` states.
- [x] Recover interrupted `running` jobs and reuse already successful jobs.
- [x] Isolate failures so one corrupt modality/sample does not abort unrelated extraction.
- [x] Support per-modality invalidation; touching one audio asset invalidates only that audio job.
- [ ] Use bounded process/device queues for CPU/GPU-heavy learned extractors instead of extending the current thread pool.

### Exit criteria

Delivered for current handcrafted feature extractors. Learned CPU/GPU extractors need a separate process/device scheduler.

---

## P1-B — benchmark and regression harness

- [x] Add `weldinfra benchmark` with machine-readable JSON output.
- [ ] Measure full light-scan wall time in an explicit scratch benchmark workspace.
- [ ] Measure no-op incremental-scan wall time.
- [x] Measure process peak RSS where the platform exposes it.
- [x] Measure SQLite size.
- [x] Measure sample-list and sample-detail P50/P95 latency.
- [ ] Measure preview-generation latency by modality.
- [ ] Measure handcrafted/learned feature throughput.
- [ ] Measure concurrent API read throughput.
- [ ] Add a generated large synthetic benchmark fixture in CI; keep the real 40 GB dataset local/nightly only.
- [x] Store benchmark metadata with platform, Python version, git SHA, and snapshot ID.
- [ ] Add regression thresholds only after stable baselines are collected.

---

## P1-C — multimodal alignment diagnostics

- [x] Resolve explicit sensor time axes from numeric elapsed-time fields or known Date+Time/time-only encodings without inventing an unknown sample rate.
- [x] Estimate welding onset from sensor current/voltage transitions, audio framed RMS, and video illumination/arc change.
- [ ] Estimate welding end/active interval in addition to onset.
- [x] Report per-modality offsets, confidence, method, and diagnostic details.
- [x] Build a generated alignment fixture with known sensor/audio/video onset offsets and bounded-error tests.
- [x] Parse the audited `%m-%d-%y %H:%M:%S.%f` sensor timestamp shape explicitly before mixed-format fallback.
- [ ] Add alignment quality plots and batch/session distribution reports.
- [x] Keep alignment as an explicit derived report; never silently shift raw media.

---

## P1-D — QML workbench testability and analysis UX

- [ ] Move preview/feature jobs to cancellable background tasks.
- [ ] Add synchronized video/audio/sensor timeline playback using explicit alignment metadata.
- [ ] Add Good-versus-defect compare mode matched by process parameters.
- [ ] Add histogram/pivot exploration by category, weld type, steel, thickness, split, and session.
- [ ] Add issue triage and user annotations in a separate overlay database.
- [ ] Add API disconnect/reconnect behavior and visible task/error state.
- [ ] Add QML/offscreen tests for filtering, pagination, selection, seek, media errors, and shutdown.
- [ ] Add macOS and Windows packaging smoke tests.

---

## P2-A — experiment registry and evaluation contract

- [x] Add a lightweight repository-native experiment registry rather than requiring an external MLflow service.
- [x] Persist experiment config/provenance/environment/predictions/metrics with snapshot ID, split artifact ID, git SHA, dependency environment, and random seeds.
- [x] Add unified ROC AUC, PR AUC, equal-error rate, FNR-at-fixed-FPR, category-wise metrics, and session-grouped bootstrap ROC-AUC confidence intervals.
- [x] Add externally calibrated fixed-threshold operating-point analysis by session, weld type, steel type, and thickness, including FPR/FNR range summaries.
- [ ] Add missing-modality robustness evaluation.
- [ ] Add inference latency/memory fields to the common prediction/evaluation contract.
- [ ] Add paired official-split versus session-disjoint comparison reports.

Thresholds must be calibrated outside the evaluation frame (normally train/validation). The evaluator never tunes an operating threshold on the test frame.

---

## P2-B — stronger unimodal baselines

Only after the remaining leakage/reporting work is stable:

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

## Next recommended implementation order

1. Near-duplicate leakage detection and official-vs-session-disjoint comparison report.
2. Expand benchmark harness: scratch full/no-op scan, preview/features/API throughput, large synthetic benchmark fixture.
3. Complete alignment with active-interval/end detection and batch quality reporting.
4. Build QML synchronized timeline and compare/annotation workflows on top of alignment/job APIs.
5. Add stronger unimodal audio/sensor/video/image baselines only after the above reporting boundary is stable.
6. Move to calibrated fusion and online replay after unimodal results are reproducible.
