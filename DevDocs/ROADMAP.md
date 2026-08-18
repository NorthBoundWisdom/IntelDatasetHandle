# Roadmap

## Milestone 0 — starter package

Delivered in this package:

- Workspace/config model.
- Archive inspection and safe extraction.
- Tolerant manifest/filesystem discovery.
- Media probes and SQLite index.
- Validation reports.
- Cached previews.
- CLI, REST API, and QML starter UI.
- Handcrafted feature extraction.
- Tabular anomaly baseline and late-fusion utility.
- Synthetic dataset, tests, CI, and development docs.

## Milestone 1 — adapt to the real archive

Exit criteria:

- Exact archive layout documented.
- Manifest path semantics confirmed.
- All expected samples resolve.
- Audio/video/sensor schemas and rates recorded.
- Full light scan has no unexplained errors.
- Split and session-leakage audit completed.
- Real-schema regression tests added without real data.

## Milestone 2 — reproducible dataset snapshots

- Incremental scan with fingerprints.
- Snapshot ID from manifest/index hashes.
- Resumable preview/feature job state.
- Deterministic environment lock.
- Experiment configuration and result registry.

## Milestone 3 — stronger unimodal baselines

- Audio STFT autoencoder.
- Frozen video embeddings and reconstruction/density models.
- Sensor temporal baseline.
- Post-weld image anomaly baseline.
- Unified score/evaluation schema.

## Milestone 4 — multimodal alignment and fusion

- Estimate modality onset/end alignment.
- Synchronized timeline viewer.
- Late-fusion reproduction.
- Learned fusion with missing-modality handling.
- Session-grouped uncertainty estimates.

## Milestone 5 — online/edge simulation

- Dataset replay service.
- RTSP video and MQTT sensor adapters.
- Online anomaly event schema.
- Latency/throughput benchmark harness.
- ONNX/OpenVINO export only after research correctness is stable.
