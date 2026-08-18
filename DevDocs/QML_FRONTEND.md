# QML frontend

## Current scope

The QML application is an engineering browser over the local SQLite index. It is not a labeling system and it does not own dataset discovery.

Current functions:

- Open an initialized workspace.
- Rebuild the index in a worker thread.
- Filter by query, category, split, and health.
- Inspect process metadata, assets, and issues.
- Play the primary indexed video through Qt Multimedia.
- Generate and display cached video/audio/sensor/image previews.
- Reveal files and copy paths.

## Python/QML boundary

`AppController` exposes:

- State properties: workspace, busy/status, stats, selected sample, preview bundle, categories, splits, matching count.
- Slots: open workspace, set filters, refresh, select sample, generate previews, rebuild index, open path, copy text.

`SampleListModel` is a `QAbstractListModel` with stable roles. It carries only list-summary fields. Full sample detail is loaded on selection.

The QML layer must not open SQLite or scan directories directly.

## Performance model

- At most 5,000 filtered rows are loaded into the current list model. This is sufficient for the upstream dataset scale; pagination can be added later.
- Full sample detail is one repository query.
- Expensive preview generation runs via `QThreadPool`.
- Original video playback remains direct file playback.
- Audio and sensor visualization currently use cached PNG derivatives, avoiding a QML charting dependency.

## Known limitations

- Preview task cancellation is not implemented.
- The video playback cursor is not synchronized with waveform/sensor plots.
- AVI codec support depends on Qt Multimedia's platform backend.
- There is no persistent user annotation overlay.
- Rebuild progress is coarse in the QML path.
- QML code is included as a strong starter but has not been compiled in this delivery environment because PySide6 is optional.

## Recommended next UI steps

1. Add a separate `annotations.sqlite3` so human notes never mutate the discovered index.
2. Add a timeline model for synchronized video/audio/sensor selection.
3. Add matched-sample comparison using category and process-parameter filters.
4. Add category/split/process pivot charts.
5. Package with `pyside6-deploy` after macOS and Windows codec testing.
