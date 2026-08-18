# QML frontend

## Runtime model

The desktop browser runs with the developer's installed Qt `qml` executable.
It does not import or install PySide. A short-lived Python launcher starts the
read-only FastAPI adapter on `127.0.0.1` using an available port, waits for
`/api/health`, then passes the API base URL to QML through
`Qt.application.arguments`. Closing QML terminates the API child process.

FreeCM Config discovers `qml` from `PATH` or `~/Qt/*/macos/bin/qml`. An explicit
`WELD_QML_RUNTIME` overrides discovery without putting an absolute path in Git.

## Current functions

- Load statistics and up to 1,000 filtered sample summaries from the real
  SQLite-backed API.
- Filter by query, category, split, and health.
- Inspect process metadata, indexed assets, and structured issues.
- Generate and display cached video contact sheets, image thumbnails, audio
  plots, spectrograms, and sensor plots.
- Open original video, audio, sensor, image, and generated preview URLs with the
  operating system.

The QML layer never opens SQLite, scans raw directories, or writes into the raw
dataset. All filesystem validation stays in `DatasetRepository` and the API.

## FreeCM lifecycle

`configs/freecm.commands.jsonc` declares one `local-qml-workbench` Config:

1. **Config** prepares `.venv`, locates/extracts data, scans the dataset, and
   records a local readiness receipt.
2. **Build** runs the installed `qmllint`, builds the wheel, and checks that
   `Main.qml` is packaged without stale PySide controller/model files.
3. **Run** starts the loopback API and terminal-owned QML process.
4. **Test** runs the repository's precommit checks.

Config is explicit; Build, Run, and Test fail with a clear message when its
receipt, workspace configuration, index, or QML runtime is missing.

## Performance model

- QML uses asynchronous `XMLHttpRequest`; the UI does not block on metadata
  requests.
- The list endpoint is bounded to 1,000 records per request.
- Full sample detail is fetched only after selection.
- Preview generation is bounded to one sample and cached in the external
  workspace.
- Original media remains lazy and is opened only on explicit user action.

## Known limitations

- The installed Qt 6.11.1 runtime does not include Qt Multimedia, so original
  video/audio is opened externally instead of decoded inside the QML window.
- The current QML list has a 1,000-item page limit and no next/previous page UI.
- Preview requests are not cancellable once submitted.
- There is no persistent user annotation overlay.

## Recommended next UI steps

1. Add offset pagination and retained selection across pages.
2. Add a separate `annotations.sqlite3` so human notes never mutate the index.
3. Add matched-sample comparison using process-parameter filters.
4. Add synchronized playback only after Qt Multimedia is installed and codec
   behavior is validated on target machines.
