from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
except ImportError as exc:  # pragma: no cover - optional dependency
    raise RuntimeError("Install the GUI extra: pip install -e '.[gui]'") from exc

from .controller import AppController
from .models import SampleListModel


def run_gui(workspace: Path | None = None) -> int:
    application = QGuiApplication.instance() or QGuiApplication([sys.argv[0]])
    application.setApplicationName("WeldDataWorkbench")
    application.setOrganizationName("WeldDataWorkbench")

    sample_model = SampleListModel()
    controller = AppController(sample_model, workspace)

    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("controller", controller)
    engine.rootContext().setContextProperty("sampleModel", sample_model)

    qml_path = Path(__file__).parent / "qml" / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_path)))
    if not engine.rootObjects():
        return 2
    return application.exec()


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch the WeldDataWorkbench QML browser")
    parser.add_argument("--workspace", type=Path, default=None)
    args = parser.parse_args()
    raise SystemExit(run_gui(args.workspace))


if __name__ == "__main__":
    main()
