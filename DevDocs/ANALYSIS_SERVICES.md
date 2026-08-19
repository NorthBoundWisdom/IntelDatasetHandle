# Analysis Services, Annotation Overlay, and Replay Contracts

This document describes the service-side infrastructure that can be validated without
making visual UI or learned-model quality decisions.

## Annotation overlay

Operator state is stored in:

```text
workspace/overlays/annotations.sqlite3
```

The overlay is intentionally separate from `index.sqlite3`. Dataset indexing remains
read-only after a scan, while human review state is mutable and survives index rebuilds.

Two target types are supported:

- `sample`: the target key is normally the stable `sample_id`.
- `issue`: callers may provide a stable target key or derive one with
  `issue_target_key(sample_id, code, relpath, message)`.

Each annotation stores a disposition, note, normalized tag list, revision number,
timestamps, and optional operator identifier. Every upsert appends an immutable JSON
snapshot to `annotation_history`.

Supported dispositions are:

```text
open
accepted
rejected
resolved
needs_review
ignored
```

Updates may supply `expected_revision` for optimistic concurrency. A stale revision is
reported as a conflict instead of silently overwriting another reviewer.

Dataset validation also reads existing issue annotations without modifying them.
`ignored` and `resolved` scanner issues remain present in validation exports with their
original severity, but are marked inactive and do not make validation fail. This is
used for confirmed upstream source omissions where synthesizing replacement media
would corrupt the raw-data contract.

## Good-versus-defect matching

`AnalysisService.good_matches()` provides deterministic Good-sample candidates for any
indexed sample. It does not train a model and it does not use validation/test labels to
fit a predictor.

Matching uses:

- exact/mismatch penalties for weld type and steel type;
- normalized absolute differences for thickness, current, voltage, gas, and robot speed;
- robust scales estimated from the available Good candidate population;
- deterministic `sample_id` tie breaking.

This is intended for compare-mode data selection, not as an anomaly score.

## Distribution and pivot analytics

`AnalysisService.distribution()` supports categorical counts and numeric histograms over
the indexed sample table. `AnalysisService.pivot()` returns a long-form grouped result
rather than constructing an unbounded dense matrix.

Supported dimensions include category, split, weld type, steel type, thickness, session,
and health status. Numeric measures include process parameters, total bytes, and image
count. Pivot output has an explicit cardinality cap and asks callers to refine filters
rather than allocating an arbitrarily large result.

## API surface

The local FastAPI adapter exposes:

```text
GET  /api/samples/{sample_id}/matches/good

GET  /api/annotations
PUT  /api/annotations
GET  /api/annotations/{target_type}/{target_key}
GET  /api/annotations/{target_type}/{target_key}/history

GET  /api/analytics/distribution
POST /api/analytics/pivot

POST /api/replay/plan
GET  /api/events/schema
```

The annotation endpoints write only to the overlay database. Analytics, matching, and
replay planning read the canonical dataset index.

## Stable anomaly and feedback contracts

`weld_data_workbench.replay` defines versioned Pydantic schemas for:

- `AnomalyEvent`
- `OperatorFeedbackEvent`
- `ReplayPlan`
- `ReplayEvent`

`AnomalyEvent` carries the final anomaly score, optional threshold/decision, per-modality
scores, availability, reliability, and provenance identifiers. Reliability values are
validated to `[0, 1]`.

`OperatorFeedbackEvent` links feedback to the originating anomaly event and supports
true-positive, false-positive, true-negative, false-negative, and uncertain verdicts.

`event_schema_bundle()` exports JSON Schema for transport adapters and external tools.

## Transport-agnostic replay

`DatasetReplayService.plan()` converts a `ReplayPlan` into deterministic replay
envelopes. It emits three logical events per sample:

```text
sample_started
sample_payload
sample_finished
```

The payload contains process metadata and, when requested, relative asset references.
It intentionally does **not** pretend that unknown audio/video/sensor packet timestamps
are synchronized. `relative_time_s` describes the replay schedule only.

The replay layer does not sleep, open sockets, publish MQTT, or create RTSP streams.
Those are deployment adapters and remain deferred until a concrete deployment contract
exists.

## Boundaries that still require acceptance

This infrastructure does not decide:

- QML layout or interaction design;
- synchronized media-cursor presentation;
- learned audio/video/image/sensor model architecture;
- anomaly threshold policy for deployment;
- RTSP/MQTT topic and transport semantics;
- ONNX/OpenVINO export correctness for a future accepted model.

Those remain explicit downstream tasks.
