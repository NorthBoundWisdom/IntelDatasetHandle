from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Parse a QML component using the installed Qt runtime"
    )
    parser.add_argument("qml_file", type=Path)
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlComponent, QQmlEngine

    path = args.qml_file.expanduser().resolve()
    if not path.is_file():
        parser.error(f"QML file does not exist: {path}")

    app = QGuiApplication.instance() or QGuiApplication([sys.argv[0]])
    engine = QQmlEngine()
    engine.addImportPath(str(path.parent))
    component = QQmlComponent(engine)
    component.loadUrl(QUrl.fromLocalFile(str(path)))

    deadline = time.monotonic() + max(args.timeout, 0.1)
    while component.status() == QQmlComponent.Loading and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)

    if component.status() == QQmlComponent.Loading:
        print(f"QML component did not finish loading within {args.timeout}s", file=sys.stderr)
        return 2
    errors = component.errors()
    if errors:
        for error in errors:
            print(error.toString(), file=sys.stderr)
        return 1
    print(f"QML syntax/import smoke passed: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
