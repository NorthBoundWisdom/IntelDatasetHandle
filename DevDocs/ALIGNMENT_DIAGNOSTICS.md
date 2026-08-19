# Multimodal Alignment Diagnostics

The welding workbench treats timing alignment as an explicit derived-data problem rather than silently shifting raw audio, video, or sensor streams. The source dataset states that devices were triggered from the same acquisition script but may respond at slightly different times. Consequently, equal file start timestamps do not prove physical synchronization.

This document describes alignment schema v2, active-interval estimation, batch quality reporting, and the contract intended for the QML synchronized timeline.

## Design rules

1. Raw media is immutable.
2. Every estimated time shift is inspectable and reproducible.
3. The sensor stream is preferred as the reference when it exposes a real time axis and a detectable welding-current/voltage transition.
4. If the sensor onset is unavailable, audio is preferred, then video.
5. An observed recording end is not automatically a physical weld end.
6. When activity remains above threshold through the last observed frame/sample, the estimate is marked `end_censored: true`.
7. Unknown sensor sampling rates are never invented.
8. Alignment quality is a triage signal, not expert welding ground truth.

## Per-modality activity traces

### Audio

Audio is decoded as floating-point samples and reduced to mono. The estimator uses framed RMS energy with a default frame length near 20 ms. Reads are explicitly bounded by `audio_max_seconds`, which defaults to 60 seconds and covers every audited public FLAC file.

The activity threshold is based on the beginning of the recording. This works for the expected acquisition pattern where the recording starts before arc ignition. The estimator does not assume that the recording ends after the weld has ended.

Output details include:

- sample rate;
- actual frame duration;
- analyzed duration;
- baseline median;
- baseline MAD;
- threshold;
- peak activity;
- active point count;
- end-censoring state;
- source/analyzed duration and whether the analysis window was truncated.

### Video

Video is decoded through OpenCV for timing diagnostics because onset/end detection needs actual pixels rather than only container metadata. Sampled frames are converted to grayscale and summarized by a simple illumination score combining high-end luminance and the fraction of near-saturated pixels. The default resource contract scans at most 60 seconds, evaluates at most 10 frames per second, and resizes analysis frames to at most 320 pixels wide while retaining source-timeline timestamps.

This is intentionally an inspectable engineering baseline. It is not an arc-segmentation neural network. The score is sufficient to detect the large illumination transition present in the generated regression fixture and provides a useful starting point for real-data analysis.

A video that can only be inspected through the general ffprobe metadata fallback but cannot be decoded by OpenCV will therefore have an alignment error. That distinction is deliberate: metadata readability and pixel-level timing analysis are different capabilities.

### Sensor

The estimator first resolves an explicit time axis. Supported sources currently include:

- numeric `timestamp_s`;
- numeric `time_s`;
- numeric `elapsed_s`;
- numeric seconds fields;
- audited `Date` + `Time` timestamps;
- bare clock-time fields that can be normalized within one recording.

The audited date/time layout `%m-%d-%y %H:%M:%S.%f` is parsed explicitly before falling back to pandas mixed-format parsing.

If no explicit time information exists, alignment fails with `No explicit sensor time axis could be resolved`. Row index is never converted into seconds using an assumed frequency.

The activity trace prefers numeric columns whose names contain `current`, then `voltage`. Absolute magnitude is used so signed representations do not change onset semantics.

Sensor parsing is bounded to 200,000 rows by default. Positive timestamp steps are inspected for gaps greater than both one second and ten times the median step. Such gaps are reported as `time_gap_detected` and `max_time_gap_s`; they are never silently removed or compressed.

## Robust interval detection

The shared detector operates on a scalar activity trace and a real time axis.

The threshold is derived from the leading baseline:

- baseline = median of the leading baseline points;
- noise scale = median absolute deviation;
- dynamic scale = difference between the global 95th percentile and baseline;
- threshold increment = maximum of a MAD term, a fraction of dynamic range, and a small numerical floor.

A start is accepted only after sustained above-threshold activity. Modality-specific short gaps are bridged in physical time. The detector selects the earlier of activity runs whose length is within 90% of the dominant run, instead of ending at the first brief release or allowing a one-point length difference to select a later duplicate segment. Confidence uses the unbridged active fraction inside the selected interval.

If no release is observed before the recording ends, the estimator extends the interval by one median positive time step where such a step can be resolved and records `end_censored: true`.

This distinction matters when comparing durations. A censored duration is a lower-bound observation of the active interval within the observed window, not proof that the physical welding process ended at the file boundary. `analysis_window_truncated` separately records whether a configured resource limit ended observation before the source file ended.

## Per-sample schema v2

`weldinfra alignment` emits a JSON object with the following main fields:

```text
schema_version = 2
sample_id
reference_modality
estimates
  sensor/audio/video
    onset_s
    end_s
    duration_s
    confidence
    method
    details
    error
offsets_s
end_offsets_s
durations_s
start_spread_s
end_spread_s
duration_spread_s
quality
```

`offsets_s` is measured relative to the chosen reference onset. `end_offsets_s` is separately measured relative to the reference end. No implicit time shift is applied to media files.

`start_spread_s` is the max-minus-min onset across available modalities. Equivalent fields exist for end and duration.

## Quality labels

The current labels are deliberately coarse:

- `good`: all three onsets exist, onset spread is small, and modality confidence is adequate;
- `warning`: all three exist but disagreement is larger;
- `poor`: all three exist but onset disagreement is large;
- `partial`: two useful modalities are available;
- `insufficient`: fewer than two modalities have detectable onsets.

These labels are intended for dataset triage and UI highlighting. They should not be used as defect labels or as a model training target without a separate study.

## Single-sample usage

```bash
weldinfra alignment \
  --workspace ~/Datasets/IntelWelding/workspace \
  --sample-id <sample-id>
```

The default output is stored under:

```text
workspace/reports/alignment/<safe-sample-id>.json
```

The read-only API exposes the same computation:

```text
GET /api/samples/{sample_id}/alignment
```

This endpoint is retained for synchronous compatibility. UI clients should use the persistent bounded/cancellable alignment task endpoint when issuing concurrent work.

## Batch usage

Dataset-wide analysis is available through:

```bash
weldinfra alignment-batch \
  --workspace ~/Datasets/IntelWelding/workspace \
  --workers 8
```

Useful filters include:

```bash
weldinfra alignment-batch \
  --workspace ~/Datasets/IntelWelding/workspace \
  --split test \
  --category Porosity \
  --limit 500 \
  --workers 8 \
  --audio-max-seconds 60 \
  --video-max-seconds 60 \
  --video-analysis-fps 10 \
  --video-max-width 320 \
  --sensor-max-rows 200000
```

The command writes:

```text
alignment-batch.json
alignment-batch.csv
alignment-plots/
  start-offsets.png
  start-spread-histogram.png
  active-durations.png
```

The JSON report contains per-sample rows plus aggregate statistics. The CSV is intentionally flattened for ad-hoc analysis in pandas, spreadsheets, or external plotting tools.

## Batch summary

The summary reports:

- total samples;
- quality label counts;
- start/end/duration spread distributions;
- start/end offset distributions by modality;
- modality onset/interval success rates;
- modality duration/confidence distributions;
- end-censoring counts;
- bounded analysis-window truncation counts;
- detected sensor time-gap counts and distributions;
- most frequent modality errors;
- summaries grouped by upstream split;
- summaries grouped by defect category;
- session-level triage and the worst sessions by poor/insufficient count and onset-spread tail.

The intent is to make timing assumptions visible before model fusion is attempted. If one session consistently shows a large video offset, for example, the researcher can investigate acquisition behavior rather than allowing a model to absorb that session-specific artifact silently.

## Plot semantics

`start-offsets.png` shows audio and video onset offsets relative to the selected reference. Sensor is normally zero because it is usually the reference.

`start-spread-histogram.png` shows the max onset disagreement across available modalities for each sample.

`active-durations.png` compares estimated active durations across sensor, audio, and video. End-censored samples remain present; consumers should use the per-row censoring flags when interpreting duration tails.

## QML integration contract

The future synchronized timeline should consume schema v2 without modifying source media timestamps.

A useful UI mapping is:

```text
master timeline time t
sensor local time = t - sensor_offset_s
audio  local time = t - audio_offset_s
video  local time = t - video_offset_s
```

The exact sign convention should be implemented once in the UI/controller and covered by tests. The API currently defines each modality offset as:

```text
modality onset - reference onset
```

Therefore a positive audio offset means the detected audio event occurred later in its local recording than the reference event.

The UI should also visualize the detected active interval, source-end censoring, analysis-window truncation, and sensor time-gap diagnostics. These states should use distinct visual treatments rather than drawing a definitive weld-stop marker.

## Failure handling

Alignment failure is modality-local. A corrupt audio file does not prevent sensor/video estimates from being returned. Batch analysis keeps problematic samples as rows rather than dropping them, preserving the ability to measure failure rates by session/category/split.

Expected failure modes include:

- media cannot be decoded;
- video has no usable FPS;
- sensor CSV is empty or corrupt;
- sensor time axis is unresolved;
- current/voltage column is absent;
- trace is too short;
- no sustained activity is detected.

All of these should remain visible in `error` or diagnostic fields.

## Validation strategy

Public CI uses generated data only. Tests cover:

- a scalar active interval with a one-point dropout;
- an interval that runs through recording end and must be marked censored;
- internal dropouts and near-equal dominant runs;
- synthetic FLAC with a known quiet-active-quiet interval;
- bounded audio windows that end before a later event;
- synthetic sensor CSV with a known current interval;
- sensor row limits and explicit large timestamp-gap diagnostics;
- generated MJPG AVI with a known bright interval;
- audited Date+Time parsing;
- refusal to invent sensor frequency;
- real-schema generated fixture onset compatibility;
- batch summaries, filters, deterministic ordering, JSON/CSV output, and plots;
- corrupt-media rows remaining visible;
- the FastAPI alignment endpoint;
- `weldinfra alignment-batch` command behavior.

## Next work

The data-side contract and background task layer are now sufficient for product work:

1. QML master timeline and aligned media cursors;
2. active-interval, censoring, truncation, and time-gap visualization;
3. compare mode and session-level timing diagnostics in the workbench;
4. explicit review of the remaining large audio/video onset outliers.

The 2026-08-19 full real-data report is summarized in `REAL_DATA_BASELINE_2026-08-19.md`. Do not add speculative timestamp formats or silently compress the three observed wall-clock gaps; future parser changes still require a new real encoding and a regression fixture.
