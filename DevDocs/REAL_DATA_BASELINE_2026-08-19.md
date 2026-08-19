# Real-data baseline — 2026-08-19

This record contains aggregate metadata and measurements only. It does not contain
Intel media bytes, previews, or trained checkpoints. The detailed machine-readable
reports remain in the ignored local workspace under `workspace/reports/`.

## Dataset identity and validation

- Snapshot ID: `29aeb715c5685749ce6d2630eb27b74388f1f72411c423dc2361a9b878c8c191`
- Samples/sessions/assets: 4,040 / 236 / 32,305
- Indexed source bytes: 44,699,658,216
- Validation: passed with 0 active errors, 1 active warning, and 1 active info finding.
- Six canonical findings for three samples without post-weld images remain recorded
  but are marked `ignored` in the local annotation overlay as confirmed official-source
  omissions. No replacement images were synthesized.
- Leakage audit: 216 sessions and 4,009 samples cross official split boundaries;
  no exact hashed asset was observed across splits.

The snapshot was created and immediately verified against the live index and assets.
The optional 39.9 GB archive re-hash was omitted because the archive digest was already
recorded in `DATASET_NOTES.md` and would add unrelated sequential I/O to this run.

## Stable local benchmark

Machine: Darwin 25.6 arm64, Python 3.13.12, 18 logical CPUs. One warm-up was followed
by three identical measured runs. Every run enabled scratch full/no-op light scanning,
two preview samples, four feature samples per modality, and 32 in-process API requests
at concurrency four. All stages succeeded without warnings and used the snapshot above.

| Metric | Run 1 | Run 2 | Run 3 | Median | CV |
|---|---:|---:|---:|---:|---:|
| Full light scan (s) | 17.318 | 18.170 | 18.267 | 18.170 | 2.38% |
| Full scan (samples/s) | 233.29 | 222.35 | 221.16 | 222.35 | 2.42% |
| No-op incremental scan (s) | 5.652 | 5.863 | 5.815 | 5.815 | 1.57% |
| No-op scan (samples/s) | 714.81 | 689.02 | 694.76 | 694.76 | 1.58% |
| Full/no-op speedup | 3.064x | 3.099x | 3.141x | 3.099x | 1.02% |
| Repository list P95 (ms) | 0.708 | 0.814 | 0.708 | 0.708 | 6.68% |
| Repository detail P95 (ms) | 1.015 | 1.085 | 0.954 | 1.015 | 5.26% |
| Cold preview mean (ms) | 372.99 | 384.39 | 389.01 | 384.39 | 1.76% |
| Warm preview mean (ms) | 1.284 | 1.400 | 1.351 | 1.351 | 3.52% |
| API requests/s | 452.55 | 458.89 | 440.74 | 452.55 | 1.67% |
| API P95 (ms) | 10.943 | 10.510 | 10.976 | 10.943 | 1.96% |
| Base benchmark peak RSS (MiB) | 267.78 | 270.47 | 270.22 | 270.22 | 0.45% |

Median cold feature throughput was 84.86 audio, 28.00 video, 98.60 sensor, and
56.12 image samples/s. Every immediate warm pass reused all requested jobs.

These results establish an initial reference, not a CI failure threshold. Additional
cross-commit measurements should precede any hard gate.

## Alignment baseline and evidence-driven revision

The initial full batch analyzed only the first 15 seconds of audio/video. Real indexed
durations are 25–38 seconds for audio and 21–43 seconds for video. Consequently, the
baseline confused analysis-window truncation and short signal dropouts with physical
weld endings.

| Metric | Initial full baseline | Revised full result |
|---|---:|---:|
| Samples | 4,040 | 4,040 |
| Sensor/audio/video onset successes | 4,040 / 4,037 / 4,040 | 4,040 / 4,040 / 4,040 |
| Start-spread median / P95 (s) | 1.227 / 4.638 | 1.190 / 2.285 |
| Duration-spread median / P95 (s) | 24.191 / 30.525 | 0.557 / 5.951 |
| Sensor/audio/video end-censored | 0 / 1,223 / 2,364 | 0 / 27 / 0 |
| Sensor/audio/video analysis-window truncated | not distinguished | 0 / 0 / 0 |
| Quality good / warning / poor / partial | 1 / 185 / 3,851 / 3 | 2 / 190 / 3,848 / 0 |

The revised detector:

- uses explicit 60-second audio/video and 200,000-row sensor bounds;
- analyzes video at most 10 FPS and 320-pixel width while preserving source time;
- bridges short modality-specific dropouts and selects the earlier of near-dominant
  activity runs instead of ending at the first brief release;
- distinguishes source-end censoring from analysis-window truncation;
- reports large sensor timestamp gaps without compressing or inventing time.

Three sensor files contain a detected large wall-clock gap (14.368, 16.288, and
117.906 seconds). Two still align through their earlier near-dominant activity segment;
one retains a 17.378-second onset spread and remains an explicit triage case. The
remaining large video/audio onset outliers are kept visible rather than hidden by
relaxing quality thresholds.
