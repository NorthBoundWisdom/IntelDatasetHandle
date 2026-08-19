# Test and Infrastructure Roadmap

This roadmap tracks the infrastructure phase after the first successful integration with the real Intel Robotic Welding Multimodal Dataset. The goal is to keep the data and experiment pipeline reproducible, failure-tolerant, leakage-aware, measurable, and suitable for sustained research work.

## Current baseline

- Real public archive audited: 4,040 samples across 236 sessions.
- Real light-probe scan succeeds for all present AVI, FLAC, CSV, and JPEG assets.
- Video probing uses OpenCV first and an explicit ffprobe metadata fallback when OpenCV cannot open or validate an AVI; decode verification remains separately reported.
- Three source samples have no post-weld images; these are source-data findings rather than scanner failures.
- Public FLAC assets are mono 16 kHz PCM-16.
- The upstream train/validation/test counts match the paper, but 216 session IDs cross official split boundaries.
- Cached image/video perceptual hashes support bounded near-duplicate leakage triage, and one immutable prediction set can be compared under upstream and session-disjoint policies.
- Multimodal timing analysis estimates start/end/active duration, explicitly marks right-censored recording ends, and supports batch/session quality reports plus diagnostic plots.
- Preview, feature, and alignment work can run through a persistent bounded/cancellable background-task layer instead of blocking UI/API callers.
- Learned CPU/device execution has explicit bounded process/device queues and backpressure rather than an unbounded thread submission model.
- A common sample-oriented prediction contract now carries per-modality availability/reliability and inference latency/memory metadata.
- Fixed late fusion, Good-training-only standardization, validation-only convex-weight tuning, and reliability-aware missing-modality fusion are implemented as model-independent utilities.
- Missing-modality robustness and inference telemetry are part of the unified evaluator.
- The comprehensive benchmark suite measures repository queries, scratch full/no-op scans, preview generation/cache reuse, per-modality feature throughput/cache reuse, and in-process API throughput.
- A warm-up plus three stable real-machine benchmark runs are recorded in `DevDocs/REAL_DATA_BASELINE_2026-08-19.md`; thresholds remain deferred pending cross-commit evidence.
- Full real-data alignment now distinguishes source-end censoring from bounded analysis-window truncation, reports large sensor timestamp gaps, and produces all three modality intervals for 4,040/4,040 samples.
- Public CI includes Linux Python 3.11/3.12/3.13, generated large-fixture benchmark smoke, clean-wheel smoke, and native macOS/Windows QML lint/parser/package smoke.
- Human review state lives in a separate revisioned annotation overlay instead of mutating the canonical dataset index.
- Deterministic Good-sample matching, histogram/distribution analytics, and bounded long-form pivot analytics are available behind service/API contracts.
- Versioned anomaly/feedback event schemas and transport-agnostic deterministic dataset replay envelopes are defined without committing to RTSP/MQTT semantics.

The high-level rule remains: **do not optimize research metrics until dataset identity, split semantics, provenance, timing semantics, and evaluation contracts are reproducible.**

---

## P0-A — CI and quality gates

- [x] Add GitHub Actions CI for Linux on Python 3.11, 3.12, and 3.13.
- [x] Run Ruff, formatting checks, scoped infrastructure mypy, compileall, pytest, and the synthetic smoke workflow in CI.
- [x] Build a wheel and install it into a clean environment as a packaging smoke test.
- [x] Add native macOS and Windows Qt/QML lint/parser/package smoke with PySide6.
- [x] Produce pytest coverage reports and enforce an 80% core-package coverage gate; command adapters/QML and optional torch-only modules are excluded from the initial denominator.
- [x] Cache pip artifacts without caching generated dataset/workspace state.

### Exit criteria

Delivered for public CI. Visual QML correctness remains a product/UI acceptance concern rather than a parser/package CI concern.

---

## P0-B — deterministic dataset snapshots and provenance

- [x] Add `weldinfra snapshot-create` and `weldinfra snapshot-verify`.
- [x] Define a deterministic snapshot document containing schema version, manifest hash, optional archive hash, canonical semantic index hash, distributions, media/schema distributions, live asset integrity, and tool version.
- [x] Derive a stable `snapshot_id` from canonical snapshot content rather than timestamps or raw SQLite page bytes.
- [x] Make experiment provenance reference `snapshot_id` rather than only a filesystem path.
- [x] Detect changed manifest/index semantics and live missing/stat-drifted assets during snapshot verification.

### Exit criteria

Delivered for the indexed/local dataset boundary. Full-media SHA-256 remains an explicit expensive option rather than a default 40 GB scan cost.

---

## P0-C — crash safety, restartability, and incremental indexing

- [x] Add incremental re-indexing keyed by indexed metadata plus live asset `relpath`, size, mtime, and optional trusted SHA-256.
- [x] Preserve atomic `index.sqlite3.building -> index.sqlite3` replacement.
- [x] Add failure/restart tests for SQLite write failure, stale `.building`, interruption, and concurrent reads of the old active index.
- [x] Keep probe/codec failure isolated to the affected candidate.
- [x] Add ffprobe metadata fallback for AVI assets OpenCV cannot open/validate without treating metadata readability as decode verification.
- [x] Verify failed rebuilds leave the previous index queryable and clean WAL/SHM/building state.
- [x] Make no-op incremental scans avoid reopening unchanged codecs.
- [x] Record added/reused/reprobed/removed/failed counts.

### Exit criteria

Correctness plumbing is complete; remaining scan work is real-dataset measurement/optimization when evidence warrants it.

---

## P0-D — real-schema regression fixture

- [x] Add a generated mini fixture mirroring audited manifest/path/schema shape without Intel media bytes.
- [x] Preserve audited sensor columns and representative 30/31 FPS behavior.
- [x] Include missing/corrupt media, duplicate basename, sensor-schema variation, audio-rate variation, and cross-split-session cases.
- [x] Add regression assertions for normalized counts, path semantics, duplicate handling, and stable issue codes.
- [x] Keep real Intel samples, screenshots, derived previews, and trained checkpoints out of Git.

---

## P0-E — leakage-resistant split infrastructure

- [x] Keep upstream split annotations separate from generated experimental split artifacts.
- [x] Audit sessions and exact hashes across partitions.
- [x] Add cached bounded perceptual image/video near-duplicate triage.
- [x] Add deterministic session-disjoint holdout generation and grouped K-fold utilities.
- [x] Add balanced session-level holdout heuristic while retaining deterministic hash assignment as a simpler fallback.
- [x] Export versioned split artifacts rather than rewriting raw annotations.
- [x] Compare one immutable prediction set under official and session-disjoint policies side by side.

---

## P1-A — derivative jobs, task scheduling, and backpressure

- [x] Persist per-sample/per-modality handcrafted feature job state in a separate workspace SQLite database.
- [x] Cache by live modality fingerprint + extractor name + extractor version + canonical config hash.
- [x] Track pending/running/success/failed/stale and recover interrupted feature jobs.
- [x] Isolate corrupt modality/sample failures.
- [x] Support per-modality invalidation.
- [x] Bound handcrafted feature futures in flight rather than scheduling all samples at once.
- [x] Add a separate persistent background-task database for preview/feature/alignment operations.
- [x] Add task progress, result/error state, restart recovery, queue backpressure, and cooperative cancellation.
- [x] Add bounded spawn-process CPU queues and named device queues for future learned extractors/models.

### Exit criteria

Execution infrastructure is complete enough for future learned extractors. Specific Torch/OpenVINO model worker implementations remain model work, not generic scheduler work.

---

## P1-B — benchmark and regression harness

- [x] Add lightweight `weldinfra benchmark` repository/read-path JSON reports.
- [x] Add comprehensive `weldbench` report.
- [x] Measure scratch full light scan and immediate no-op incremental scan.
- [x] Measure peak RSS where available, SQLite size, sample-list/detail P50/P95 latency, preview latency/cache reuse, feature throughput/cache reuse, and concurrent in-process API throughput.
- [x] Add a deterministic generated large benchmark fixture in CI without Intel bytes.
- [x] Store benchmark platform/Python/git/snapshot metadata.
- [ ] Add performance regression thresholds only after stable baselines are collected on the main development machine.

### Exit criteria

Measurement plumbing and a nontrivial public CI fixture are complete. Real-machine threshold selection intentionally remains evidence-driven.

---

## P1-C — multimodal alignment diagnostics

- [x] Resolve explicit sensor time axes without inventing unknown sample rates.
- [x] Estimate welding onset and active interval/end from sensor, audio, and video.
- [x] Mark right-censored ends explicitly.
- [x] Report start/end offsets, duration, confidence, methods, spread, and quality.
- [x] Add generated bounded-error alignment tests and audited Date+Time parsing.
- [x] Add dataset-wide alignment batch reports, filters, JSON/CSV output, category/split/session aggregation, and diagnostic plots.
- [x] Expose per-sample alignment through the API.
- [x] Keep alignment as explicit derived state; never silently shift raw media.

---

## P1-D — workbench analysis services and QML UX

### Infrastructure-safe work

- [x] Move preview/feature/alignment work behind a cancellable persistent background-task API while retaining synchronous compatibility endpoints.
- [x] Add native macOS/Windows QML lint/parser/package smoke.
- [x] Add a separate revisioned sample/issue annotation overlay database that survives index rebuilds.
- [x] Add deterministic Good-versus-defect matching by weld/material/process parameters.
- [x] Add categorical/numeric distribution and bounded long-form pivot analysis services.
- [x] Expose annotation, matching, distribution, and pivot contracts through FastAPI.

### Product/UI acceptance work

- [ ] Add synchronized video/audio/sensor timeline playback using schema-v2 alignment intervals and offsets.
- [ ] Add Good-versus-defect compare presentation matched by process parameters.
- [ ] Add histogram/pivot exploration UI.
- [ ] Add issue-triage/annotation UI.
- [ ] Add API disconnect/reconnect and visible task/error presentation.
- [ ] Add deeper QML interaction tests for filtering, pagination, selection, seek, media errors, and shutdown once component boundaries are stabilized.

The data/service implementations for compare, analytics, and annotations are complete independently of visual acceptance; only the final QML presentation remains acceptance-sensitive.

---

## P2-A — experiment registry and evaluation contract

- [x] Add repository-native experiment registry.
- [x] Persist config/provenance/environment/predictions/metrics with snapshot ID, split artifact ID, git SHA, dependency environment, and seeds.
- [x] Add ROC AUC, PR AUC, EER, FNR-at-fixed-FPR, category metrics, and session-grouped bootstrap ROC-AUC confidence intervals.
- [x] Add externally calibrated fixed-threshold group stability analysis.
- [x] Add common per-row inference latency/process CPU/peak RSS/device/batch-size fields.
- [x] Add missing-modality robustness evaluation by actual availability pattern.
- [x] Add paired official-split versus session-disjoint reports for one immutable prediction set.

Thresholds are calibrated outside the evaluation frame. The evaluator never tunes an operating threshold on test rows.

---

## P2-B — unimodal prediction contract and future baselines

### Infrastructure-safe work

- [x] Add a common sample-oriented prediction schema for unimodal/fused models.
- [x] Normalize modality availability and bounded reliability values.
- [x] Add prediction artifact metadata sidecars and inference telemetry helpers.

### Research/model acceptance work

- [ ] Audio log-STFT + bounded convolutional/shallow autoencoder baseline.
- [ ] Sensor-only statistical/temporal learned baseline.
- [ ] Maintained frozen video embedding + anomaly baseline.
- [ ] Maintained frozen post-weld-image embedding + anomaly baseline.
- [ ] Calibrate each model strictly on train/validation, never test.

Architecture/model-family choices should be driven by real-data measurements and explicit research intent.

---

## P2-C — multimodal fusion

- [x] Standardize selected unimodal scores using Good training data only.
- [x] Implement fixed weighted late fusion.
- [x] Renormalize remaining effective weights when modalities are missing.
- [x] Add optional reliability-aware fusion.
- [x] Tune convex weights on an explicit validation frame only.
- [x] Add unimodal-versus-fusion ablation reporting from one immutable prediction frame.
- [ ] Add learned fusion only after unimodal baselines are independently validated.
- [ ] Report real-model fused results under official and session-disjoint policies once real unimodal predictions exist.

---

## P3 — online/edge simulation

### Infrastructure-safe core

- [x] Add a transport-agnostic deterministic dataset replay plan/service without coupling it to the indexer.
- [x] Define stable versioned anomaly-event and operator-feedback schemas with JSON Schema export.

### Acceptance/model-dependent work

- [ ] Add concrete RTSP/MQTT adapters where deployment requires them.
- [ ] Add end-to-end transport latency/failure-injection tests after the transport contract exists.
- [ ] Add ONNX/OpenVINO export adapters only after model correctness is stable.
- [ ] Keep any commercial-use work blocked until dataset/model licensing is resolved in writing.

---

## Remaining implementation boundaries

1. Accumulate cross-commit real-machine benchmark history before deciding whether any performance threshold belongs in CI; the initial three-run baseline is now recorded.
2. Extend sensor timestamp parsing only when a new real encoding is observed and can be regression-tested.
3. Keep QML interaction/layout work as explicit product acceptance work; service contracts underneath compare, analytics, annotations, background tasks, and replay are now available.
4. Keep audio/video/image/sensor model-family selection and learned fusion as explicit research decisions backed by the real dataset.
5. Defer RTSP/MQTT transport adapters and ONNX/OpenVINO export until a concrete deployment/model contract exists.
