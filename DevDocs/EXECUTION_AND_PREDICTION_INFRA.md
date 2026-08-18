# Execution, Prediction, and Evaluation Infrastructure

This document describes the repository infrastructure that sits between raw multimodal welding data and future learned models/UI workflows. The goal is to make expensive derived work cancellable and bounded, make prediction artifacts comparable across models, and make missing-modality/fusion behavior explicit before any specific neural architecture is selected.

## Scope

This layer deliberately does **not** choose a research model architecture. It provides reusable contracts for:

- background preview, feature, and alignment jobs;
- bounded thread/process/device execution;
- persistent task progress and cancellation state;
- common sample-oriented prediction artifacts;
- inference latency and process-memory telemetry;
- missing-modality evaluation;
- Good-training-only score standardization;
- fixed late fusion;
- validation-only convex-weight tuning;
- reliability-aware fusion;
- generated large benchmark fixtures;
- Linux plus native macOS/Windows CI coverage.

Raw Intel dataset bytes remain read-only and are never copied into the job-state databases.

---

## Background task boundary

`weld_data_workbench.runtime_tasks` provides a workspace-local task manager backed by:

```text
workspace/jobs/tasks.sqlite3
```

The task store records only derived execution metadata:

```text
task_id
kind
state
payload_json
result_json
error
progress_current
progress_total
progress_message
cancel_requested
created_at
started_at
finished_at
updated_at
```

Supported states are:

```text
queued
running
succeeded
failed
cancelled
```

The database is intentionally separate from `index.sqlite3`. The dataset index remains an immutable/read-only query surface after a scan, while task state is operational mutable state.

### Restart semantics

A process that terminates while tasks are in `running` state cannot prove those workers are still alive. On the next task-manager initialization, stale running tasks are converted to explicit failures with an interruption diagnostic. They are not silently resumed at an arbitrary instruction boundary.

Long-running algorithms that already have their own resumable cache, such as handcrafted feature extraction, can then be submitted again and reuse successful lower-level jobs.

### Backpressure

The task manager uses a bounded semaphore around a `ThreadPoolExecutor` rather than accepting an unlimited queue. When capacity is exhausted, submission fails immediately with `TaskQueueFullError` instead of accumulating unbounded decoded media, Python futures, or QML requests in memory.

The API maps this condition to HTTP 429.

### Cooperative cancellation

Running tasks cannot be safely killed at arbitrary Python/native-library instructions. Cancellation is therefore cooperative:

1. the task row receives `cancel_requested = 1`;
2. handlers check the flag at defined safe points;
3. feature extraction checks between bounded groups of work;
4. the task ends in `cancelled` state instead of `failed`.

Queued cancellations never enter the running state.

---

## API task surface

The FastAPI adapter retains synchronous preview/alignment endpoints for compatibility, but exposes the preferred task surface:

```text
POST /api/tasks/previews/{sample_id}
POST /api/tasks/alignment/{sample_id}
POST /api/tasks/features
GET  /api/tasks
GET  /api/tasks/{task_id}
POST /api/tasks/{task_id}/cancel
```

Feature tasks do not accept an arbitrary output path from API clients. Their output is constrained to:

```text
workspace/features/tasks/<task_id>.parquet
```

This prevents the local API from becoming a general filesystem-write primitive.

The QML client can poll one task ID and display progress/error/cancellation without embedding Python feature-generation logic in the UI process.

---

## Bounded learned-job scheduling

`weld_data_workbench.execution` provides the execution primitive intended for future learned extractors.

The existing handcrafted feature pipeline is light enough to use threads, but learned video/image/audio models may hold large tensors and non-thread-safe native runtime state. The scheduler therefore separates:

- bounded thread execution;
- spawn-based CPU process execution;
- explicit named device queues.

A device queue is configured with `DeviceSpec`:

```python
DeviceSpec(
    name="mps",
    slots=1,
    mode="thread",
    max_queue=2,
)
```

Other valid names can be repository/model conventions such as:

```text
cuda:0
cuda:1
mps
xpu:0
cpu
```

The scheduler does not auto-detect or auto-select a device. Device selection is explicit so provenance can record the actual execution policy.

### Why spawn-based CPU workers

`ProcessPoolExecutor` uses a spawn multiprocessing context. This avoids inheriting arbitrary initialized native-library state from the parent process and is safer for future Torch/OpenVINO/native inference libraries than relying on fork semantics.

### Queue limits

Every executor has:

```text
max_workers
max_queue
```

Submission beyond `max_workers + max_queue` fails immediately. The snapshot API reports submitted/completed/in-flight/rejected counts and can be included in diagnostics.

---

## Feature extraction scheduling

The handcrafted feature pipeline now bounds the number of futures in flight instead of submitting the complete dataset at once.

The default maximum in-flight count is proportional to worker count. This matters for the 4,040-sample real dataset because a future may indirectly retain sample metadata, decoded frames, exception state, and native resources.

Cancellation occurs between bounded scheduling windows. Existing per-modality cache keys remain unchanged:

```text
sample fingerprint
extractor name
extractor version
canonical config hash
```

Consequently a cancelled run can be started again without discarding already successful feature jobs.

---

## Prediction artifact contract

`weld_data_workbench.prediction_contract` defines a model-independent, sample-oriented table.

Required identity:

```text
sample_id
```

The conventional fused/final anomaly score is:

```text
anomaly_score
```

where larger means more anomalous.

For each modality, implementations may emit:

```text
score_audio
score_video
score_sensor
score_image

available_audio
available_video
available_sensor
available_image

reliability_audio
reliability_video
reliability_sensor
reliability_image
```

Reliability values are constrained to `[0, 1]` and represent model/pipeline confidence or quality, not defect probability unless a specific model explicitly defines that semantic.

Duplicate `sample_id` rows are rejected. Availability values are normalized from boolean/0/1 representations. Prediction artifacts can be written as Parquet, CSV, or JSONL with a JSON metadata sidecar.

### Metadata sidecar

The sidecar records at least:

```text
prediction_schema_version
model_name
modalities
score_semantics
telemetry_fields
```

Additional model-specific metadata may be nested under `extra` without changing the stable common columns.

---

## Inference telemetry

The common artifact supports:

```text
inference_latency_ms
process_cpu_ms
peak_rss_mb
device
batch_size
```

`measure_inference` records wall-clock latency and process CPU time around an operation. Peak RSS is included where the operating system exposes a compatible process-usage API; Windows may report it as unavailable rather than inventing a value.

These fields are diagnostic measurements, not strict CI thresholds. Runtime comparisons should keep hardware, environment, dataset snapshot, batch size, and model version fixed.

---

## Missing-modality evaluation

The evaluator reports performance by actual modality-availability pattern. Example patterns are:

```text
available=audio+video+sensor+image;missing=none
available=audio+video+sensor;missing=image
available=audio+sensor;missing=video+image
```

For each sufficiently populated pattern it reports the same anomaly metrics used by the main evaluator and the ROC-AUC delta relative to the overall prediction set.

This evaluator does not manufacture new fused scores after deleting modalities. Synthetic modality removal belongs in the model/fusion layer because only that layer knows how a model should behave when an input disappears.

---

## Score standardization

Multimodal fusion begins with an explicit standardization policy. `fit_good_standardizer` fits center/scale values using **Good training rows only**.

This prevents defective validation/test examples from changing the score coordinate system. It also makes the calibration boundary auditable in experiment provenance.

A zero/near-zero standard deviation falls back to a scale of one rather than dividing by zero.

---

## Fixed late fusion

`fuse_scores` combines selected modality scores using non-negative weights.

For a complete row:

```text
fused = sum(weight_i * standardized_score_i)
```

For a row with missing modalities, unavailable terms are removed and remaining effective weights are normalized. The function also reports:

```text
fusion_available_modalities
fusion_effective_weight
```

If no usable modality remains, the fused score is NaN rather than a fabricated normal/anomalous score.

### Reliability-aware fusion

When enabled, each base weight is additionally multiplied by the corresponding reliability value before row-wise normalization.

This provides a bounded, inspectable mechanism for low-quality or partially missing modalities without introducing a learned fusion network prematurely.

---

## Validation-only convex tuning

`tune_convex_weights` searches a bounded simplex grid. It accepts an explicit validation frame and never reads test data internally.

Supported objectives are:

```text
roc_auc
pr_auc
```

The grid is deliberately bounded to at most five modalities. This is an engineering baseline, not a replacement for later model-selection methodology.

The chosen weights, objective value, number of candidates, and validation row count are serializable into experiment provenance.

---

## Fusion ablation

`fusion_ablation_report` emits unimodal and fused ROC-AUC/PR-AUC summaries from the same immutable prediction frame. This establishes the reporting shape needed for later official-split versus session-disjoint comparison without refitting predictions.

Learned fusion remains intentionally out of scope until strong unimodal models are independently validated.

---

## Large generated benchmark fixture

`weld_data_workbench.benchmark_fixture` creates a deterministic many-sample directory tree without Intel media bytes.

Media templates are generated once, then hard-linked where supported. A copy fallback is used on filesystems without hard links. This gives CI realistic directory/index cardinality without generating hundreds of independent video/audio files.

The CI benchmark fixture currently exercises:

- discovery and indexing;
- scratch full/no-op scan benchmarking;
- preview timing;
- feature extraction/cache reuse;
- in-process API throughput.

Real 40 GB benchmark runs remain local/nightly because public CI must not receive gated dataset bytes.

---

## Native QML CI

The workflow now includes macOS and Windows native jobs with PySide6.

Each job performs:

1. `pyside6-qmllint` on `Main.qml`;
2. an offscreen `QQmlComponent` load to catch QML import/parser failures;
3. wheel build;
4. clean wheel installation and package import.

This is a structural/native packaging gate. It does not claim visual correctness or interaction-design acceptance.

---

## Safety and provenance rules

The following rules apply to this layer:

- raw dataset files are never modified;
- task/annotation/experiment databases live under the workspace, not the raw dataset;
- API clients cannot choose arbitrary feature output paths;
- model thresholds are calibrated outside test evaluation;
- fusion standardization uses Good training data only;
- validation-only weight tuning is explicit;
- missing modalities produce explicit availability state;
- unavailable memory telemetry remains null rather than guessed;
- generated CI fixtures contain no Intel media bytes.

---

## What still requires acceptance or real-data evidence

The following work should not be auto-completed merely because infrastructure exists:

- choice of audio autoencoder architecture and STFT representation;
- choice of maintained video/image embedding model;
- sensor temporal architecture;
- learned fusion architecture;
- QML timeline visual/interaction design;
- UI compare-mode presentation and annotation workflow details;
- aggressive benchmark regression thresholds;
- RTSP/MQTT transport details;
- ONNX/OpenVINO export for models that do not yet exist;
- any commercial-use interpretation of the Intel research dataset license.

Those decisions should be driven by real 40 GB diagnostics, benchmark measurements, model results, or explicit product acceptance rather than hidden infrastructure assumptions.
