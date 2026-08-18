# Development plan

## P0 — establish truth from the downloaded archive

- [x] Record the real archive root and manifest filename in `DevDocs/DATASET_NOTES.md` without hard-coding them into the scanner.
- [x] Index the complete extracted dataset and inspect every issue code.
- [x] Compare indexed counts against the upstream expectations: 236 sessions and 4,040 samples observed.
- [x] Confirm the public FLAC files are mono 16 kHz PCM-16 and document the paper's 192 kHz discrepancy.
- [x] Record the real sensor CSV columns and row-count range; exact units/synchronization semantics still require upstream confirmation.
- [x] Confirm how `DIRECTORY`, `SUBDIRS`, `SAMPLES`, and `SPLIT` are encoded in the manifest.
- [x] Add a regression fixture containing the anonymized real manifest path shape only.
- [x] Audit the official split: training contains only Good samples, but 216 session IDs cross splits.

## P1 — robust local data engineering

- [ ] Add incremental re-indexing keyed by asset size, mtime, and optional checksum.
- [ ] Add resumable feature extraction with per-sample state and failure isolation.
- [ ] Add ffprobe fallback for AVI files OpenCV cannot decode.
- [ ] Add audio/video alignment diagnostics based on onset and illumination changes.
- [ ] Add a time-axis normalization layer for all sensor CSV variants.
- [ ] Add duplicate/near-duplicate sample detection.
- [ ] Add deterministic dataset snapshots containing manifest/index hashes.
- [ ] Add session-grouped cross-validation utilities.

## P1 — user interface

- [ ] Move preview generation to a cancellable background job queue.
- [ ] Add synchronized playback cursor across video, audio waveform, and sensor plot.
- [ ] Add issue triage and user annotations in a separate overlay database.
- [ ] Add compare mode for Good versus defective samples with matched process parameters.
- [ ] Add histogram and pivot views by category, weld type, material, thickness, and split.
- [ ] Add QML packaging for macOS and Windows.

## P2 — research baselines

- [ ] Reproduce a bounded audio STFT autoencoder baseline.
- [ ] Add video clip embeddings using a maintained pretrained video model.
- [ ] Add post-weld-image anomaly and supervised baselines.
- [ ] Add sensor-only time-series baselines.
- [ ] Add calibrated late fusion with confidence intervals.
- [ ] Evaluate category-wise AUC, equal-error rate, precision-recall, and threshold stability.
- [ ] Add explicit leakage audits and bootstrap confidence intervals grouped by session.

## P2 — production-oriented extensions

- [ ] Introduce a stream simulator emitting RTSP/MQTT-compatible data without coupling it to the indexer.
- [ ] Define an online event schema for anomaly scores and operator feedback.
- [ ] Add model export adapters for ONNX/OpenVINO only after research baselines are stable.
- [ ] Keep all commercial-use work blocked until dataset/model licensing is resolved in writing.
