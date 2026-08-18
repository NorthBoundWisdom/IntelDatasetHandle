# Development plan

`TODO_TEST_INFRASTRUCTURE.md` is the detailed infrastructure/test roadmap. This file remains the compact project-level plan.

## P0 — establish truth from the downloaded archive

- [x] Record the real archive root and manifest filename in `DevDocs/DATASET_NOTES.md` without hard-coding them into the scanner.
- [x] Index the complete extracted dataset and inspect every issue code.
- [x] Compare indexed counts against the upstream expectations: 236 sessions and 4,040 samples observed.
- [x] Confirm the public FLAC files are mono 16 kHz PCM-16 and document the paper's 192 kHz discrepancy.
- [x] Record the real sensor CSV columns and row-count range; exact units/synchronization semantics still require upstream confirmation.
- [x] Confirm how `DIRECTORY`, `SUBDIRS`, `SAMPLES`, and `SPLIT` are encoded in the manifest.
- [x] Add a generated regression fixture matching the audited manifest/path/sensor/media shape without committing Intel data.
- [x] Audit the official split: training contains only Good samples, but 216 session IDs cross splits.

## P1 — robust local data engineering

- [x] Add crash-safe incremental re-indexing, no-op reuse, ffprobe fallback, and explicit scan statistics.
- [x] Add resumable per-sample/per-modality handcrafted feature extraction with persistent cache state and bounded in-flight work.
- [x] Add a persistent bounded/cancellable background-task layer for preview, feature, and alignment work.
- [x] Add bounded spawn-process CPU queues and named device queues for future learned extractors.
- [x] Add deterministic dataset snapshots and live-asset integrity checks.
- [x] Add leakage audits, near-duplicate triage, deterministic session-disjoint holdout, grouped K-fold, and official-vs-session-disjoint comparison.
- [x] Add explicit sensor time normalization plus multimodal onset/active-interval/end diagnostics with batch/session reports and plots.
- [x] Add comprehensive machine-readable benchmarking for repository reads, scratch scans, previews, features/cache reuse, and API throughput.
- [x] Add a generated many-sample benchmark fixture to public CI.
- [ ] Collect stable real-machine benchmark baselines before introducing performance regression thresholds.
- [ ] Extend sensor timestamp parsing only when additional real encodings are observed and regression-tested.

## P1 — user interface and analysis services

### Infrastructure complete without visual acceptance

- [x] Expose background task progress/error/cancellation through FastAPI.
- [x] Add native macOS/Windows QML lint/parser/package smoke.

### Remaining service-side work that can be implemented without visual acceptance

- [ ] Add a separate annotation/issue-disposition overlay database.
- [ ] Add deterministic Good-vs-defect sample matching by process parameters.
- [ ] Add histogram/pivot analytics service/API.

### Product/UI acceptance work

- [ ] Add synchronized playback cursor and active-interval overlays across video/audio/sensor.
- [ ] Add compare-mode, analytics, annotation, reconnect, and task-state presentation in QML.
- [ ] Add deeper offscreen interaction tests after QML component boundaries stabilize.

## P2 — prediction, evaluation, and model research

### Infrastructure complete without model acceptance

- [x] Add a common sample-oriented prediction schema with per-modality availability/reliability.
- [x] Add per-row inference latency/process CPU/peak RSS/device/batch-size telemetry.
- [x] Add missing-modality robustness evaluation.
- [x] Add Good-training-only score standardization.
- [x] Add fixed late fusion, row-wise missing-modality renormalization, and reliability-aware fusion.
- [x] Add validation-only convex-weight tuning and unimodal/fusion ablation reporting.
- [x] Retain category-wise ROC AUC, PR AUC, EER, FNR@FPR, threshold stability, session bootstrap, experiment registry, and provenance.

### Research/model acceptance work

- [ ] Choose and implement bounded audio STFT/autoencoder baseline.
- [ ] Choose and implement sensor temporal baseline.
- [ ] Choose maintained video embedding/anomaly baseline.
- [ ] Choose maintained post-weld-image embedding/anomaly baseline.
- [ ] Add learned fusion only after unimodal baselines are independently validated.

## P3 — production-oriented extensions

### Infrastructure-safe core

- [ ] Add a transport-agnostic dataset replay plan/service.
- [ ] Define stable anomaly-event and operator-feedback schemas.

### Deployment/model-dependent work

- [ ] Add RTSP/MQTT adapters only when a concrete deployment contract requires them.
- [ ] Add ONNX/OpenVINO export adapters only after model correctness is stable.
- [ ] Keep all commercial-use work blocked until dataset/model licensing is resolved in writing.
