# Intel dataset notes and audit template

## Public upstream facts

As of the repository state used to create this starter package, the public dataset card describes:

- More than 4,000 annotated samples collected in an automotive production-floor setting.
- 236 welding-session directories.
- One AVI video, associated FLAC audio, one CSV time series, and five post-weld images per sample.
- A nominal 30 FPS video stream.
- A manifest containing `CATEGORY`, `WELD_TYPE`, `THICKNESS_MM`, `STEEL_TYPE`, `SAMPLES`, `CURRENT_A`, `VOLTAGE_V`, `GAS_BAR`, `ROBOT_SPEED_CPM`, `DIRECTORY`, `SUBDIRS`, and `SPLIT`.
- Twelve category labels including `Good` and eleven defect categories.
- Potential label noise because intended defects were not post-weld validated by a welding expert.
- Potential slight cross-modality misalignment due to device response differences.
- Research-only licensing and a statement that the dataset should not be used commercially.

The paper reports 4,040 samples and the following anomaly-detection split:

| Partition | Good | Defective |
|---|---:|---:|
| Train | 576 | 0 |
| Validation | 122 | 1,610 |
| Test | 121 | 1,611 |

The paper treats the task as unsupervised anomaly detection: training uses Good samples only.

## Audio-rate discrepancy resolved for the public archive

The Hugging Face dataset card currently describes one-channel audio at **16 kHz**. The paper describes the original audio experiments as retaining a **192 kHz** sampling rate.

The archive downloaded and indexed on 2026-08-18 contains 4,040 FLAC files. All
of them report one channel, a 16 kHz sampling rate, and PCM-16 encoding. The
public release therefore matches the dataset card. The paper's 192 kHz value
appears to describe the original recording or experiment pipeline rather than
the distributed FLAC files; this is an inference, because the archive itself
does not document the reason for the difference.

Re-check a local index with:

```bash
weldtool stats --workspace <workspace>
```

The `audio_sample_rates_hz` distribution is read from FLAC headers.

## Archive audit record

```text
Archive filename: intel_robotic_welding_dataset.tar.gz
Archive compressed bytes: 39,939,194,323
Archive SHA-256: 10a6bfc9973e5e23f2e10cd62c71e2ceb1d32ed9f8fa3071038d561566cee2f8
Top-level archive directory: raid/intel_robotic_welding_dataset/
Manifest relative path: raid/intel_robotic_welding_dataset/manifest.csv
Manifest encoding/delimiter: US-ASCII (UTF-8 compatible), comma-separated
Manifest row model: one sample per row (4,040 rows)
Observed sessions: 236
Observed samples: 4,040
Observed asset counts: 4,040 AVI; 4,040 FLAC; 4,040 sensor CSV; 20,185 JPEG
Observed audio sample rates/channels: 16,000 Hz, mono, FLAC PCM-16 (all 4,040)
Observed video codecs/FPS range: FMP4, 960x600, 30 or 31 FPS
Observed sensor CSV schema: Date, Time, Part No, Pressure, CO2 Weld Flow, Feed,
  Primary Weld Current, Wire Consumed, Secondary Weld Voltage, Remarks
Observed sensor row-count range: 195-666
Observed post-weld images: JPEG; five observed resolution groups, predominantly 2000x900
Index build date: 2026-08-18
Index schema version: 1
```

`DIRECTORY` identifies the session directory. Every `SUBDIRS` value is already
root-relative and begins with the corresponding `DIRECTORY`; `SAMPLES` repeats
the number of manifest rows for that session. The raw split labels are `TRAIN`,
`VAL`, and `TEST`, normalized by the workbench to `train`, `validation`, and
`test`.

The light-probe index found no unreadable AVI, FLAC, CSV, or present JPEG files.
Three samples contain no post-weld images, accounting for 15 missing JPEGs and
the index's three errors plus three warnings. The official counts match the
paper exactly: train has 576 Good and no defective samples; validation has 122
Good plus 1,610 defective; test has 121 Good plus 1,611 defective. However, 216
session IDs occur in more than one split, so session-grouped experiments must
treat the published split as a potential leakage source.

In the local workspace reviewed on 2026-08-19, the six missing-image findings are
marked `ignored` in the separate annotation overlay with a note that they are confirmed
official-source omissions. The canonical index facts remain unchanged, validation
reports them as inactive, and no replacement media was generated.

A full alignment audit also found three sensor files with large Date+Time gaps. The
parser preserves those wall-clock gaps and reports them explicitly; it does not invent
a sampling rate or silently compress time. Aggregate results and the stable machine
benchmark are recorded in `REAL_DATA_BASELINE_2026-08-19.md`.

## Required checks after first full scan

```bash
weldtool scan --workspace <workspace> --workers 8 --probe light
weldtool validate --workspace <workspace>
weldtool stats --workspace <workspace> --json > stats-console.json
```

Review at minimum:

1. `manifest_not_found` or unresolved sample paths.
2. Sample count versus approximately 4,040.
3. Session count versus 236.
4. Category distribution versus the paper.
5. `defect_in_training_split` findings.
6. Missing/corrupt AVI, FLAC, sensor CSV, or images.
7. Mixed or unexpected sample rates.
8. Session IDs crossing splits.
9. Multiple audio/video/sensor assets per sample.
10. Sensor columns and units.

## Upstream references

- Dataset: https://huggingface.co/datasets/IntelLabs/Intel_Robotic_Welding_Multimodal_Dataset
- Paper: https://arxiv.org/abs/2409.02290
