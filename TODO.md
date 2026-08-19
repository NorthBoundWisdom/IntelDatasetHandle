# Development plan and local handoff

This file is the single active project-level TODO. `TODO_TEST_INFRASTRUCTURE.md` remains a historical/detailed infrastructure record; new work should be tracked here.

## Current state

The repository has completed the generic data/infrastructure phase for the audited Intel Robotic Welding Multimodal Dataset:

- 4,040 samples / 236 sessions are indexed from the real archive.
- Raw data is immutable; derived workspace state is isolated.
- Incremental indexing, deterministic snapshots, validation, leakage audit, previews, feature caching, background tasks, benchmarks, experiment provenance, prediction artifacts, evaluation, fusion utilities, annotation overlays, compare/analytics services, alignment diagnostics, and deterministic replay contracts exist.
- The native QML workbench consumes the service layer through the loopback FastAPI boundary rather than reading SQLite/raw files directly.
- The workbench UI is componentized and now exposes pagination, reconnect state, cancellable preview/alignment tasks, synchronized alignment inspection, sample annotations, matched-Good comparison, distributions/pivots, and task state.
- A deterministic alignment-triage utility ranks real-data outliers without changing alignment semantics.
- A model-runner protocol defines the boundary future learned models must follow before predictions enter the common experiment/evaluation contract.

The project should no longer add generic infrastructure unless a concrete research or deployment requirement exposes a missing contract.

---

## P0 — local product acceptance

These items require the developer's actual Qt/runtime/data environment and cannot be accepted from repository-only changes.

- [ ] **Run the current QML workbench against the full local 4,040-sample workspace.** Verify startup, reconnect, filtering, pagination, retained selection, task polling/cancellation, annotation save/conflict handling, compare mode, analytics, and clean shutdown.
- [ ] **Perform visual layout acceptance on macOS and Windows.** Check narrow-window behavior, long IDs/paths, scrolling, high-DPI scaling, dark palette consistency, control clipping, and tab navigation.
- [ ] **Verify Qt Multimedia decoding/seek behavior on target machines.** Exercise representative AVI/FLAC files, repeated seek, pause/resume, sample switching, corrupted media, and end-of-stream behavior.
- [ ] **Validate synchronized cursor semantics on real samples.** Confirm `reference_time -> modality_time = reference_time + offset_s` matches intended alignment interpretation and does not mislead on censored/truncated intervals.
- [ ] **Review annotation workflow with real operator usage.** Decide final disposition/tag vocabulary after actual triage; do not hard-code a larger ontology before it is used.
- [ ] Add deeper Qt Quick Test/qmltestrunner interaction coverage after the component boundaries survive one local acceptance pass. The existing CI parser/package smoke and source-level contract tests remain the pre-acceptance gate.

### Acceptance output

Record only aggregate findings/screenshots that are safe to commit. Never commit Intel media bytes, generated previews derived from gated data, or local workspace databases.

---

## P1 — alignment evidence review

The alignment computation is complete enough to expose real failure classes, but the 2026-08-19 batch still marks most samples `poor`. Do not tune thresholds blindly.

- [ ] Run the full alignment batch using the current bounded 60-second / 10-FPS / 320-pixel / 200k-row limits.
- [ ] Rank review cases with:

  ```bash
  python scripts/triage_alignment.py \
    ~/Datasets/IntelWelding/workspace/reports/alignment-batch.json \
    --limit 100
  ```

- [ ] Review the highest-priority cases in the QML workbench and annotate failure classes such as `real_offset`, `double_activity`, `video_detector_failure`, `audio_detector_failure`, `sensor_time_gap`, or `unknown` only after confirming them visually.
- [ ] Inspect the known large sensor wall-clock-gap samples and the largest remaining audio/video onset outliers.
- [ ] Change alignment algorithms/thresholds only when a repeated, labeled failure class justifies a regression fixture.
- [ ] Re-run the immutable batch and compare before/after aggregate metrics. Preserve both reports for evidence; never silently overwrite the interpretation of old experiments.

---

## P2 — real unimodal model research

Repository infrastructure is ready; model family acceptance requires local training and real metrics.

### P2-A Audio

- [ ] Select and document the exact log-STFT/window/normalization policy for the actual mono 16 kHz FLAC files.
- [ ] Implement/train a bounded convolutional or shallow autoencoder using **Good training data only**.
- [ ] Calibrate preprocessing and thresholds on validation only.
- [ ] Emit predictions through `ModelRunner` / the common prediction contract, including inference telemetry.

### P2-B Sensor

- [ ] Establish a simple statistical/one-class baseline first.
- [ ] Select a temporal representation that uses the explicit sensor time axis and does not invent an unknown sampling rate.
- [ ] Train/evaluate a small temporal model only if it improves on the inspectable baseline.

### P2-C Video

- [ ] Choose a maintained frozen video/frame embedding model after checking license, runtime, memory, and target-device support.
- [ ] Define exact clip/frame sampling on the real AVI durations.
- [ ] Prefer frozen embeddings + simple anomaly modeling before training a large video network.

### P2-D Post-weld image

- [ ] Choose a maintained frozen image embedding model with compatible license.
- [ ] Evaluate kNN/Mahalanobis/one-class anomaly scoring before adding trainable image heads.
- [ ] Treat the three source samples without post-weld images as missing modality, not synthetic replacements.

### Required reporting for every accepted model

- [ ] Primary result: deterministic **session-disjoint** split.
- [ ] Compatibility result: official Intel split, clearly labeled as leakage-prone.
- [ ] ROC AUC, PR AUC, EER, FNR@fixed-FPR, category breakdown, session-grouped bootstrap CI, threshold stability, latency, CPU/RSS/device/batch metadata, and missing-modality behavior.
- [ ] Snapshot ID, split artifact ID, Git SHA, dependency environment, seeds, model/preprocessing config, and prediction sidecar are present in the experiment registry.

---

## P3 — multimodal research

Start only after independently accepted unimodal predictions exist.

- [ ] Compare audio, sensor, video, and image unimodal results from one immutable evaluation frame.
- [ ] Run fixed late fusion, missing-modality renormalization, validation-only convex-weight tuning, and reliability-aware fusion using the existing utilities.
- [ ] Report all ablations and both split policies; do not publish only the best fused aggregate metric.
- [ ] Consider learned fusion only if fixed/reliability-aware fusion exposes a clear limitation and the added complexity is justified by validation evidence.

---

## P4 — second-dataset/generalization boundary

Do this when a second industrial multimodal dataset is actually selected.

- [ ] Add a dataset adapter boundary only for assumptions that truly differ from the Intel archive (manifest mapping, modality names, process metadata, time semantics).
- [ ] Keep the canonical repository/prediction/evaluation interfaces dataset-agnostic where possible.
- [ ] Add a generated regression fixture for the second adapter; do not make the Intel parser increasingly speculative to absorb unrelated formats.
- [ ] Compare whether the same unimodal/fusion experiment contracts can run without workbench-specific forks.

---

## P5 — deployment, intentionally deferred

Blocked until there is an accepted model and a concrete deployment contract.

- [ ] RTSP adapter only when stream/container/timestamp semantics are specified.
- [ ] MQTT adapter only when topics, payload schema, QoS, ordering, and clock semantics are specified.
- [ ] End-to-end replay/transport latency and failure-injection tests after those adapters exist.
- [ ] ONNX/OpenVINO export only for an accepted model, with numerical parity tests against the source implementation.
- [ ] Resolve dataset/model commercial-use licensing in writing before any production/commercial use.

---

## Standing engineering rules

- Raw Intel data is read-only and stays outside Git.
- Scanner/index facts are immutable; human review belongs in the overlay database.
- Test is never used for preprocessing, threshold, fusion-weight, or model selection.
- Session-disjoint results are the primary generalization signal; official-split results are compatibility-only.
- Do not add timestamp formats, synchronization assumptions, transport semantics, or model complexity without observed evidence.
- Prefer one reproducible experiment path over model-specific scripts with bespoke output formats.
