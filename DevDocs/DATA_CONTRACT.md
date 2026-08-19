# Persisted data contract

## 1. Versioning

The current configuration and SQLite schema version is `1`.

Any incompatible change to table fields, identity semantics, or path interpretation requires:

1. A schema-version bump.
2. A migration or an explicit requirement to rebuild the index.
3. Updated tests and this document.

## 2. Identity

### Sample ID

A sample ID is derived from the sample-directory basename when unique. When the same basename exists more than once, each colliding sample receives a deterministic suffix derived from its dataset-relative path.

Consequences:

- IDs are human-readable in the common case.
- IDs remain stable while the relative path is stable.
- Code must not infer category, split, or session from the sample ID.

### Asset ID

Asset IDs are SHA-1 identifiers derived from sample ID, kind, ordinal, and relative path. They are internal identity keys, not security hashes.

## 3. Path semantics

All paths persisted in `samples` and `assets` are POSIX-form dataset-relative paths, even on Windows.

At runtime, `DatasetRepository` resolves them under the configured `dataset_root` and rejects path escape.

Absolute paths and `file://` URLs are generated at query time and are not persisted.

## 4. `samples`

| Field | Meaning |
|---|---|
| `sample_id` | Stable workbench identity. |
| `session_id` | Parent session-directory basename. |
| `relpath` | Sample directory relative to dataset root. |
| `category_raw` | Original manifest value. |
| `category` | Normalized taxonomy value when recognized. |
| `is_good` | `1` for normalized `Good`, `0` for a known non-Good category, `NULL` if unannotated. |
| `split` | Normalized `train`, `validation`, or `test` when recognized. |
| `weld_type` | Manifest weld type. |
| `thickness_mm` | Parsed numeric thickness. |
| `steel_type` | Manifest material/steel designation. |
| `current_a` | Manifest current set point. |
| `voltage_v` | Manifest voltage set point. |
| `gas_bar` | Manifest gas pressure. |
| `robot_speed_cpm` | Manifest robot/process speed field, preserved using upstream naming. |
| `manifest_relpath` | Manifest path relative to dataset root. |
| `manifest_row` | Zero-based dataframe row index. |
| `manifest_raw_json` | Full normalized-row payload for forward compatibility. |
| `discovered_by_json` | Discovery sources such as `manifest` and `filesystem`. |
| `health_status` | `ok`, `warning`, `error`, or `unprobed`. |
| `total_bytes` | Sum of indexed asset sizes. |
| `image_count` | Number of indexed image assets. |
| `primary_*_relpath` | First deterministic asset of that kind for convenience. Multiple assets remain in `assets`. |
| `scanned_at` | UTC timestamp for the probe result. |

## 5. `assets`

| Field | Meaning |
|---|---|
| `asset_id` | Internal stable identity. |
| `sample_id` | Owning sample. |
| `kind` | `video`, `audio`, `sensor`, `image`, or future `other`. |
| `relpath` | File path relative to dataset root. |
| `ordinal` | Deterministic zero-based ordering within sample and kind. |
| `size_bytes` | File size at indexing time. |
| `mtime_ns` | Modification time at indexing time. |
| `status` | Probe status. |
| `metadata_json` | Kind-specific metadata. |
| `sha256` | Optional content hash when expensive hashing is enabled. |

### Current kind-specific metadata

Video:

```json
{
  "fps": 29.97,
  "frame_count": 300,
  "width": 640,
  "height": 480,
  "duration_s": 10.01,
  "fourcc": "MJPG"
}
```

Audio:

```json
{
  "sample_rate_hz": 192000,
  "channels": 1,
  "frames": 1920000,
  "duration_s": 10.0,
  "format": "FLAC",
  "subtype": "PCM_16"
}
```

Sensor:

```json
{
  "delimiter": ",",
  "row_count": 1000,
  "column_count": 8,
  "columns": ["..."],
  "numeric_columns": ["..."]
}
```

Image:

```json
{
  "width": 1920,
  "height": 1080,
  "mode": "RGB",
  "format": "JPEG"
}
```

These JSON objects may gain fields without a schema-version bump. Existing field meaning must not change silently.

## 6. `issues`

Issues are facts or warnings from discovery/probing, not user annotations.

| Field | Meaning |
|---|---|
| `severity` | `info`, `warning`, or `error`. |
| `code` | Stable machine-readable code. |
| `sample_id` | Nullable for dataset-level issues. |
| `relpath` | Relevant dataset-relative path when known. |
| `message` | Human-readable explanation. |
| `details_json` | Structured context. |

Code consuming issues should branch on `code`, not parse `message`.

## 7. Category normalization

Canonical values:

```text
Good
Excessive_Convexity
Undercut
Lack_of_Fusion
Porosity
Spatter
Burnthrough
Porosity_w_Excessive_Penetration
Excessive_Penetration
Crater_Cracks
Warping
Overlap
```

Unknown non-empty values are preserved rather than discarded. Validation reports them.

## 8. Split semantics

Aliases are normalized:

- `training` → `train`
- `val` / `valid` → `validation`
- `testing` → `test`

The workbench does not re-split samples automatically. Any new experimental split must be stored separately from the upstream annotation.

## 9. Validation findings and issue dispositions

Scanner issues in `index.sqlite3` remain immutable facts even when an operator has
confirmed that a problem belongs to the upstream source dataset. Validation joins
sample-level scanner issues to the separate annotation overlay by the stable
`issue_target_key(sample_id, code, relpath, message)` identity.

Validation JSON/CSV findings include these additive fields:

| Field | Meaning |
|---|---|
| `target_key` | Stable annotation-overlay key for a sample issue. |
| `disposition` | Current overlay disposition when one exists. |
| `disposition_note` | Operator explanation copied from the current overlay record. |
| `active` | `false` only for `ignored` or `resolved` issue dispositions. |

The original `severity`, `code`, message, and details are retained when a finding is
inactive. `validation_findings_by_severity` continues to count every recorded fact;
`active_validation_findings_by_severity` counts only actionable findings, and
`ValidationReport.passed` is determined by active errors. This allows confirmed
upstream omissions to remain auditable without repeatedly failing local validation.

The overlay lives at `workspace/overlays/annotations.sqlite3`, so an atomic index
rebuild does not erase a reviewed disposition. If a scanner issue changes identity
(for example, its path or stable message changes), it intentionally requires review
under a new target key.
