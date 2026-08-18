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

- [x] Add incremental re-indexing keyed by live asset path/size/mtime and optional trusted checksum, while preserving atomic index replacement.
- [x] Add resumable per-sample/per-modality feature extraction with persistent job state and failure isolation.
- [x] Add ffprobe metadata fallback for AVI files OpenCV cannot open or validate, while keeping decode verification explicit.
- [x] Add audio/video/sensor alignment diagnostics based on sensor transitions, audio onset, and illumination changes.
- [x] Add explicit sensor time-axis normalization for numeric elapsed-time fields and the audited Date+Time/time-only forms; do not invent an unknown sampling rate.
- [ ] Extend the time-axis parser only when additional real sensor encodings are observed and can be regression-tested.
- [x] Add cached perceptual image/video near-duplicate candidate detection for cross-split leakage triage.
- [x] Add deterministic dataset snapshots containing manifest and canonical semantic index hashes plus live-asset integrity checks.
- [x] Add deterministic session-disjoint holdout and session-grouped K-fold utilities.
- [x] Add official-versus-session-disjoint evaluation comparison for one immutable prediction set.
- [x] Add crash/interruption tests proving failed rebuilds preserve the previous valid index.
- [x] Add machine-readable repository benchmark reports; continue expanding scan/preview/feature/API throughput measurements in the detailed roadmap.

## P1 — user interface

- [ ] Move preview/feature generation to cancellable background job queues.
- [ ] Add synchronized playback cursor across video, audio waveform, and sensor plot using explicit alignment reports.
- [ ] Add issue triage and user annotations in a separate overlay database.
- [ ] Add compare mode for Good versus defective samples with matched process parameters.
- [ ] Add histogram and pivot views by category, weld type, material, thickness, split, and session.
- [ ] Add QML packaging and native smoke coverage for macOS and Windows.

## P2 — research baselines and evaluation

- [ ] Reproduce a bounded audio STFT autoencoder baseline.
- [ ] Add video clip embeddings using a maintained pretrained video model.
- [ ] Add post-weld-image anomaly and supervised baselines.
- [ ] Add sensor-only time-series baselines.
- [ ] Add calibrated late fusion with confidence intervals and missing-modality handling.
- [x] Evaluate category-wise ROC AUC, PR AUC, equal-error rate, FNR at fixed FPR, and externally calibrated threshold stability.
- [x] Add explicit session leakage audits and session-grouped bootstrap confidence intervals.
- [x] Add a repository-native experiment/provenance registry tied to dataset snapshot and split artifact IDs.
- [ ] Add inference latency/memory and missing-modality robustness to the common evaluation contract.

## P2 — production-oriented extensions

- [ ] Introduce a stream simulator emitting RTSP/MQTT-compatible data without coupling it to the indexer.
- [ ] Define an online event schema for anomaly scores and operator feedback.
- [ ] Add model export adapters for ONNX/OpenVINO only after research baselines are stable.
- [ ] Keep all commercial-use work blocked until dataset/model licensing is resolved in writing.
