from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

try:
    from PySide6.QtCore import (
        Property,
        QObject,
        QRunnable,
        QThreadPool,
        QUrl,
        Signal,
        Slot,
    )
    from PySide6.QtGui import QDesktopServices, QGuiApplication
except ImportError as exc:  # pragma: no cover - optional dependency
    raise RuntimeError("Install the GUI extra: pip install -e '.[gui]'") from exc

from ..config import AppConfig, load_config
from ..index.builder import IndexBuilder
from ..index.repository import DatasetRepository
from ..previews.generator import PreviewGenerator
from .models import SampleListModel


class TaskSignals(QObject):
    finished = Signal(object)
    error = Signal(str)
    progress = Signal(int, int, str)


class FunctionTask(QRunnable):
    def __init__(self, function: Callable[..., Any], *args: Any, **kwargs: Any):
        super().__init__()
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.signals = TaskSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.function(*self.args, **self.kwargs)
        except Exception as exc:
            self.signals.error.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.signals.finished.emit(result)


class AppController(QObject):
    busyChanged = Signal()
    statusTextChanged = Signal()
    workspacePathChanged = Signal()
    statsChanged = Signal()
    selectedSampleChanged = Signal()
    previewBundleChanged = Signal()
    filterOptionsChanged = Signal()
    errorOccurred = Signal(str)
    sampleCountChanged = Signal()

    def __init__(self, sample_model: SampleListModel, workspace: Path | None = None):
        super().__init__()
        self.sample_model = sample_model
        self.thread_pool = QThreadPool.globalInstance()
        self._config: AppConfig | None = None
        self._repository: DatasetRepository | None = None
        self._busy_count = 0
        self._status_text = "Open a workbench workspace"
        self._workspace_path = ""
        self._stats: dict[str, Any] = {}
        self._selected_sample: dict[str, Any] = {}
        self._preview_bundle: dict[str, Any] = {}
        self._categories: list[str] = []
        self._splits: list[str] = []
        self._sample_count = 0
        self._query = ""
        self._category = ""
        self._split = ""
        self._health = ""
        if workspace is not None:
            self.open_workspace(str(workspace))

    def _set_busy(self, value: bool) -> None:
        previous = self._busy_count > 0
        self._busy_count = max(0, self._busy_count + (1 if value else -1))
        if previous != (self._busy_count > 0):
            self.busyChanged.emit()

    def _set_status(self, value: str) -> None:
        if value != self._status_text:
            self._status_text = value
            self.statusTextChanged.emit()

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy_count > 0

    @Property(str, notify=statusTextChanged)
    def statusText(self) -> str:
        return self._status_text

    @Property(str, notify=workspacePathChanged)
    def workspacePath(self) -> str:
        return self._workspace_path

    @Property("QVariantMap", notify=statsChanged)
    def stats(self) -> dict[str, Any]:
        return self._stats

    @Property("QVariantMap", notify=selectedSampleChanged)
    def selectedSample(self) -> dict[str, Any]:
        return self._selected_sample

    @Property("QVariantMap", notify=previewBundleChanged)
    def previewBundle(self) -> dict[str, Any]:
        return self._preview_bundle

    @Property("QStringList", notify=filterOptionsChanged)
    def categories(self) -> list[str]:
        return self._categories

    @Property("QStringList", notify=filterOptionsChanged)
    def splits(self) -> list[str]:
        return self._splits

    @Property(int, notify=sampleCountChanged)
    def sampleCount(self) -> int:
        return self._sample_count

    @staticmethod
    def _local_path(value: str) -> Path:
        url = QUrl(value)
        return Path(url.toLocalFile() if url.isLocalFile() else value).expanduser().resolve()

    @Slot(str)
    def open_workspace(self, value: str) -> None:
        try:
            config = load_config(self._local_path(value))
            repository = DatasetRepository(config.index_path, config.dataset_root)
        except Exception as exc:
            self.errorOccurred.emit(str(exc))
            self._set_status(f"Failed to open workspace: {exc}")
            return

        self._config = config
        self._repository = repository
        self._workspace_path = str(config.workspace_root)
        self.workspacePathChanged.emit()
        self._categories = repository.categories()
        self._splits = repository.splits()
        self.filterOptionsChanged.emit()
        self.refresh()
        self._set_status(f"Opened {config.workspace_root}")

    @Slot(str, str, str, str)
    def set_filters(self, query: str, category: str, split: str, health: str) -> None:
        self._query = query.strip()
        self._category = "" if category in {"", "All"} else category
        self._split = "" if split in {"", "All"} else split
        self._health = "" if health in {"", "All"} else health
        self.refresh()

    @Slot()
    def refresh(self) -> None:
        if self._repository is None:
            return
        try:
            rows = self._repository.list_samples(
                query=self._query or None,
                category=self._category or None,
                split=self._split or None,
                health=self._health or None,
                limit=5000,
            )
            self.sample_model.replace(rows)
            self._sample_count = self._repository.count_samples(
                query=self._query or None,
                category=self._category or None,
                split=self._split or None,
                health=self._health or None,
            )
            self.sampleCountChanged.emit()
            self._stats = self._repository.stats()
            self.statsChanged.emit()
        except Exception as exc:
            self.errorOccurred.emit(str(exc))

    @Slot(str)
    def select_sample(self, sample_id: str) -> None:
        if self._repository is None:
            return
        sample = self._repository.get_sample(sample_id)
        self._selected_sample = sample or {}
        self._preview_bundle = {}
        self.selectedSampleChanged.emit()
        self.previewBundleChanged.emit()

    @Slot(str, bool)
    def generate_previews(self, sample_id: str, force: bool = False) -> None:
        if self._config is None or self._repository is None or not sample_id:
            return
        self._set_busy(True)
        self._set_status(f"Generating previews for {sample_id}…")
        generator = PreviewGenerator(self._config, self._repository)
        task = FunctionTask(generator.generate, sample_id, force=force)

        def finished(bundle: Any) -> None:
            self._preview_bundle = bundle.model_dump(mode="json")
            self.previewBundleChanged.emit()
            self._set_busy(False)
            self._set_status(f"Previews ready for {sample_id}")

        task.signals.finished.connect(finished)
        task.signals.error.connect(self._task_error)
        self.thread_pool.start(task)

    @Slot()
    def rebuild_index(self) -> None:
        if self._config is None:
            return
        self._set_busy(True)
        self._set_status("Rebuilding index…")
        builder = IndexBuilder(self._config)
        task = FunctionTask(builder.build)

        def finished(_summary: Any) -> None:
            assert self._config is not None
            self._repository = DatasetRepository(self._config.index_path, self._config.dataset_root)
            self._categories = self._repository.categories()
            self._splits = self._repository.splits()
            self.filterOptionsChanged.emit()
            self.refresh()
            self._set_busy(False)
            self._set_status("Index rebuilt")

        task.signals.finished.connect(finished)
        task.signals.error.connect(self._task_error)
        self.thread_pool.start(task)

    @Slot(str)
    def open_path(self, value: str) -> None:
        if not value:
            return
        url = QUrl(value)
        if not url.isValid() or not url.scheme():
            url = QUrl.fromLocalFile(str(Path(value).expanduser().resolve()))
        QDesktopServices.openUrl(url)

    @Slot(str)
    def copy_text(self, value: str) -> None:
        QGuiApplication.clipboard().setText(value)
        self._set_status("Copied to clipboard")

    @Slot(str)
    def _task_error(self, message: str) -> None:
        self._set_busy(False)
        self._set_status(message)
        self.errorOccurred.emit(message)
