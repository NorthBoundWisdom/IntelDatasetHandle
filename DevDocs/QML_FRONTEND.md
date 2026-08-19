# QML frontend

## Runtime model

The desktop workbench runs with the developer's installed Qt runtime through the native `Demo.app` launcher. A short-lived Python process starts the loopback-only FastAPI adapter, waits for health, and passes the selected API base URL to QML. Closing the QML process terminates the API child.

The UI never opens SQLite, scans the raw dataset, or writes raw data. Dataset facts flow through `DatasetRepository` and the API; mutable operator review state flows only through the separate annotation overlay.

## Component structure

`Main.qml` owns application/window composition and cross-feature state. Functional behavior is split under `qml/components/`:

- `ApiClient.qml` — JSON HTTP boundary, busy state, connectivity state, error normalization.
- `TaskPoller.qml` — one cancellable persistent task lifecycle.
- `FilterPanel.qml` — dataset statistics and filters.
- `SampleListPanel.qml` + `PaginationBar.qml` — bounded sample navigation.
- `DetailPanel.qml` — metadata, media playback, previews, assets/issues, review composition.
- `AlignmentTimeline.qml` — modality intervals, quality/censoring display, reference cursor seek.
- `AnnotationPanel.qml` — sample disposition/tags/notes with optimistic revision updates.
- `ComparePanel.qml` — deterministic matched-Good comparison by process parameters.
- `AnalyticsPanel.qml` — categorical/numeric distributions and bounded pivot exploration.
- `TaskPanel.qml` — recent task progress/state and cancellation.

Small visual primitives (`AssetPill`, `IssueBadge`, `StatCard`, `EmptyState`) remain reusable components.

## Current user workflows

### Browse

- Load aggregate dataset statistics.
- Filter by free text, category, split, and health.
- Navigate all matching rows with offset pagination rather than a fixed 1,000-row first page.
- Inspect full sample metadata, assets, issues, and original URLs.

### Media and derived previews

- Play selected AVI and FLAC through Qt Multimedia.
- Generate preview bundles through the persistent background task API, with visible task state rather than blocking the UI request thread.
- Display video contact sheets, image thumbnails, waveform/spectrogram, and sensor plots.

### Alignment

- Submit one alignment calculation through the persistent task API.
- Display sensor/audio/video intervals, alignment quality, offsets, and end-censoring markers.
- Seek a shared reference cursor; video/audio local seek positions are derived as `reference_time + modality_offset`.
- The UI does not silently rewrite media timestamps or claim packet-level synchronization.

### Review

- Load/save sample annotation disposition, tags, and notes from `annotations.sqlite3`.
- Send `expected_revision` when updating an existing record so concurrent edits return a conflict rather than silently overwrite.

### Compare and analytics

- Request deterministic Good candidates for a selected sample and inspect process metadata side by side.
- Query supported categorical/numeric distributions.
- Run bounded long-form pivot queries.

### Operations

- Show API connected/offline state and retry `/api/health` after disconnect.
- Inspect recent background jobs and cancel queued/running tasks.

## Performance model

- Metadata requests are asynchronous `XMLHttpRequest` calls.
- Sample pages are bounded; detail is fetched only after selection.
- Original media remains lazy and decodes only when played.
- Expensive preview/alignment work is submitted to the persistent bounded task layer.
- Derived media remains cached in the external workspace.

## Verification boundary

Public CI validates Python behavior, wheel/package contents, `qmllint`, parser/import smoke, and source-level UI contracts. Repository-only CI cannot establish:

- visual correctness on the developer's displays;
- real Intel codec/seek behavior across target machines;
- whether reference-cursor alignment is semantically useful on difficult real samples;
- operator ergonomics of disposition/tag vocabulary.

Those acceptance tasks are explicitly tracked in `TODO.md` and must be performed locally against the real workspace.
