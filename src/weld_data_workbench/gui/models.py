from __future__ import annotations

from typing import Any

try:
    from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, Slot
except ImportError as exc:  # pragma: no cover - optional dependency
    raise RuntimeError("Install the GUI extra: pip install -e '.[gui]'") from exc


class SampleListModel(QAbstractListModel):
    ROLE_NAMES = (
        "sampleId",
        "sessionId",
        "relpath",
        "category",
        "split",
        "healthStatus",
        "totalBytes",
        "imageCount",
        "weldType",
        "steelType",
    )

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[dict[str, Any]] = []
        self._roles = {
            Qt.UserRole + index + 1: name.encode("utf-8")
            for index, name in enumerate(self.ROLE_NAMES)
        }
        self._field_by_role = {
            Qt.UserRole + index + 1: field
            for index, field in enumerate(
                (
                    "sample_id",
                    "session_id",
                    "relpath",
                    "category",
                    "split",
                    "health_status",
                    "total_bytes",
                    "image_count",
                    "weld_type",
                    "steel_type",
                )
            )
        }

    def roleNames(self) -> dict[int, bytes]:
        return self._roles

    def rowCount(self, parent: QModelIndex | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or index.row() < 0 or index.row() >= len(self._rows):
            return None
        if role == Qt.DisplayRole:
            return self._rows[index.row()].get("sample_id")
        field = self._field_by_role.get(role)
        return self._rows[index.row()].get(field) if field else None

    def replace(self, rows: list[dict[str, Any]]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    @Slot(int, result="QVariantMap")
    def get(self, row: int) -> dict[str, Any]:
        if 0 <= row < len(self._rows):
            return dict(self._rows[row])
        return {}
