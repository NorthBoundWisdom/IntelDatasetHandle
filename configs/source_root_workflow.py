#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FREECM_ROOT = REPO_ROOT / "FreeCM"
for path in (REPO_ROOT, FREECM_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from freecm.source_root_workflow import SourceRootWorkflowScript  # noqa: E402

from configs.source_roots import WORKFLOW  # noqa: E402

APP_CONFIG_KEYS = (
    "WELD_QML_RUNTIME",
    "WELD_DATASET_HOME",
    "WELD_DATASET_ROOT",
    "WELD_DATASET_ARCHIVE",
    "WELD_EXTRACTED_ROOT",
    "WELD_WORKSPACE",
    "WELD_SCAN_WORKERS",
)


def update_workbench() -> int:
    lock_data = WORKFLOW.load_lock_file(REPO_ROOT)
    raw_configs = lock_data.get("AppConfigs")
    if not isinstance(raw_configs, dict):
        raise ValueError("source_roots.lock.jsonc must contain an AppConfigs object")

    environment = os.environ.copy()
    for key in APP_CONFIG_KEYS:
        value = raw_configs.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"AppConfigs.{key} must be a non-empty string")
        environment[key] = value

    result = subprocess.run(
        [sys.executable, "configs/workbench_workflow.py", "config"],
        cwd=REPO_ROOT,
        env=environment,
        check=False,
    )
    return result.returncode


SCRIPT = SourceRootWorkflowScript(
    WORKFLOW,
    repo_display_name="WeldDataWorkbench",
    update_callback=update_workbench,
)


def main(argv: list[str] | None = None) -> int:
    return SCRIPT.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
