# Roadmap

The project has moved from infrastructure construction to product acceptance and real model research.

## M0 — dataset truth — DONE

- Real archive/layout audited.
- 4,040 samples / 236 sessions indexed.
- Media/schema/split properties recorded.
- Missing source images and cross-split sessions documented.
- Generated real-shape regression fixtures exist without Intel bytes.

## M1 — reproducible research infrastructure — DONE

- Atomic incremental index and deterministic dataset snapshots.
- Leakage audit, session-disjoint split artifacts, near-duplicate triage.
- Persistent preview/feature/alignment jobs with cancellation/backpressure.
- Benchmark suite and real-machine baseline.
- Prediction contract, telemetry, experiment registry, evaluation, policy comparison.
- Score standardization, fixed/reliability-aware late fusion, missing-modality evaluation.
- Annotation overlay, matched-Good service, distribution/pivot analytics.
- Deterministic replay/event contracts without speculative transports.

## M2 — workbench product loop — CODE COMPLETE / LOCAL ACCEPTANCE ACTIVE

Repository-side code now includes:

- componentized native QML workbench;
- offset pagination;
- API disconnect/reconnect state;
- task polling/cancellation for expensive preview/alignment work;
- synchronized alignment timeline/cursor controls;
- sample review annotations with optimistic revision handling;
- deterministic Good-vs-defect comparison;
- distribution and pivot exploration;
- background task inspection/cancellation.

Remaining work is real Qt/data visual and interaction acceptance, tracked in `TODO.md`.

## M3 — alignment evidence review — NEXT

- Use deterministic triage ranking on the full batch.
- Human-review the highest-priority outliers in the workbench.
- Label repeated failure classes before modifying algorithms.
- Re-run and compare immutable before/after reports.

## M4 — unimodal research — NEXT

- Audio log-STFT anomaly baseline.
- Sensor inspectable + temporal baseline.
- Maintained frozen video embedding anomaly baseline.
- Maintained frozen post-weld image embedding anomaly baseline.
- Every model emits the common prediction contract through the model-runner boundary.
- Session-disjoint metrics are primary; official split is compatibility-only.

## M5 — multimodal research — PLANNED

- Real unimodal/fusion ablation matrix.
- Fixed, validation-tuned, and reliability-aware late fusion.
- Learned fusion only after unimodal acceptance and a demonstrated need.

## M6 — deployment — DEFERRED

- RTSP/MQTT only from a concrete deployment contract.
- ONNX/OpenVINO only for an accepted model with parity tests.
- Commercial work remains blocked until licensing is resolved in writing.
