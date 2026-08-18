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
- Multimodal timing analysis now estimates start/end/active duration, explicitly marks right-censored recording ends, and supports batch/session quality reports plus diagnostic plots.
- The comprehensive benchmark suite measures repository queries, scratch full/no-op scans, preview generation/cache reuse, per-modality feature throughput/cache reuse, and in-process API throughput.
- CLI, SQLite repository, validation, preview generation, resumable handcrafted features, Isolation Forest baseline, FastAPI, native QML, FreeCM workflow, experiment/evaluation utilities, and synthetic/real-schema fixtures are present.
- Public CI runs Linux Python 3.11/3.12/3.13, Ruff, formatting, compileall, scoped mypy, pytest with an 80% core coverage gate, synthetic smoke, wheel build, and clean-wheel CLI smoke.

The high-level rule remains: **do not optimize research metrics until dataset identity, split semantics, provenance, timing semantics, and evaluation contracts are reproducible.**

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
- [x] Add ffprobe metadata fallback for AVI assets that OpenCV cannot open or validate, without treating metadata fallback as decode verification.
- [x] Verify that failed/interrupted rebuilds leave the previous index queryable and remove temporary WAL/SHM/building files.
- [x] Make a no-op incremental scan avoid reopening unchanged media codecs.
- [x] Record scan statistics for added, reused, reprobed, removed, and failed samples.
- [x] Add an explicit `added_sample_count` field to the build summary and persisted incremental summary.

### Exit criteria

The core restart/atomicity and incremental reporting contract is implemented. Remaining work here is real-dataset performance measurement rather than correctness plumbing.

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
- [x] Add cached, bounded perceptual image/video near-duplicate candidate detection across partitions; exact hashes alone are insufficient for acquisition leakage.
- [x] Add deterministic session-disjoint holdout generation with explicit random seed.
- [x] Add session-grouped K-fold utilities.
- [x] Add a deterministic balanced holdout heuristic that keeps whole sessions while approximating sample/category targets; retain hash assignment as a simpler fallback.
- [x] Export split assignments as versioned standalone artifacts rather than rewriting raw annotations.
- [x] Add a top-level comparison report that evaluates one immutable prediction set under official-split and session-disjoint policies side by side.

### Exit criteria

Delivered for the current split/evaluation boundary: direct session overlap is prevented in generated policies, perceptual duplicate candidates are triageable, and upstream-vs-grouped evaluation is reportable without refitting or silently tuning thresholds on test data.

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

- [x] Add lightweight `weldinfra benchmark` repository/read-path JSON reports.
- [x] Add comprehensive `weldbench` / `benchmark_suite` report for expensive and modality-level measurements.
- [x] Measure full light-scan wall time in an explicit scratch benchmark workspace when requested.
- [x] Measure immediate no-op incremental-scan wall time and verify all unchanged samples are reused.
- [x] Measure process peak RSS where the platform exposes it.
- [x] Measure SQLite size.
- [x] Measure sample-list and sample-detail P50/P95 latency.
- [x] Measure preview-generation latency by modality plus cold/warm bundle-cache behavior.
- [x] Measure handcrafted per-modality feature throughput and warm cache reuse.
- [x] Measure concurrent in-process FastAPI read throughput and request latency.
- [ ] Add a generated large synthetic benchmark fixture in CI; keep the real 40 GB dataset local/nightly only.
- [x] Store benchmark metadata with platform, Python version, git SHA, and snapshot ID.
- [ ] Add regression thresholds only after stable baselines are collected on the main development machine.

### Exit criteria

The measurement surface is implemented. Remaining work is baseline collection, a larger deterministic CI fixture, and conservative regression threshold policy rather than additional timing plumbing.

---

## P1-C — multimodal alignment diagnostics

- [x] Resolve explicit sensor time axes from numeric elapsed-time fields or known Date+Time/time-only encodings without inventing an unknown sample rate.
- [x] Estimate welding onset from sensor current/voltage transitions, audio framed RMS, and video illumination/arc change.
- [x] Estimate welding end/active interval in each modality using sustained-release logic and short-gap bridging.
- [x] Explicitly report `end_censored` when activity continues to the end of the observed recording instead of pretending a physical weld end was observed.
- [x] Report per-modality start offsets, end offsets, duration, confidence, method, and diagnostic details.
- [x] Report per-sample start/end/duration spread and a coarse quality classification for triage.
- [x] Build generated tests with known sensor/audio/video onset and release times plus bounded-error assertions.
- [x] Parse the audited `%m-%d-%y %H:%M:%S.%f` sensor timestamp shape explicitly before mixed-format fallback.
- [x] Add `weldinfra alignment-batch` with category/split/health/query filtering, bounded parallelism, deterministic sample order, JSON and CSV output.
- [x] Add category/split/session aggregate summaries, modality success/error/censoring statistics, and worst-session triage.
- [x] Add aggregate start-offset, start-spread, and active-duration PNG diagnostics.
- [x] Expose per-sample alignment through `/api/samples/{sample_id}/alignment` for UI integration.
- [x] Keep alignment as an explicit derived report; never silently shift raw media.

### Exit criteria

The data-side alignment contract is complete enough for UI synchronization and research diagnostics. Future algorithm changes should be driven by observed real-data failure modes rather than speculative timestamp formats or hidden automatic shifts.

---

## P1-D — QML workbench testability and analysis UX

- [ ] Move preview/feature/alignment jobs to cancellable background tasks.
- [ ] Add synchronized video/audio/sensor timeline playback using the explicit schema-v2 alignment interval/offset metadata.
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
- [x] Add paired official-split versus session-disjoint comparison reports for one immutable prediction set.

Thresholds must be calibrated outside the evaluation frame (normally train/validation). The evaluator never tunes an operating threshold on the test frame.

---

## P2-B — stronger unimodal baselines

Only after the measurement and UI-analysis boundaries are stable:

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

1. Build the cancellable background task layer shared by preview, feature, and alignment work.
2. Add QML synchronized timeline playback using schema-v2 alignment offsets and active intervals.
3. Add QML compare/annotation/histogram workflows on top of the read-only dataset core and separate overlay state.
4. Add a larger deterministic benchmark fixture and begin collecting stable real-machine benchmark baselines.
5. Add stronger unimodal audio/sensor/video/image baselines after the analysis UI and timing contract are stable.
6. Move to calibrated fusion and online replay only after unimodal results are reproducible under both split policies.
