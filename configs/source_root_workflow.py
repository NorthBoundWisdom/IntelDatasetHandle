#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FREECM_ROOT = REPO_ROOT / "FreeCM"
for path in (REPO_ROOT, FREECM_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from freecm.source_root_workflow import SourceRootWorkflowScript  # noqa: E402

from configs.source_roots import WORKFLOW  # noqa: E402
from configs.workbench_workflow import initialize_environment  # noqa: E402


class WorkbenchSourceRootWorkflowScript(SourceRootWorkflowScript):
    def build_parser(self) -> argparse.ArgumentParser:
        parser = super().build_parser()
        for action in parser._actions:
            if "--update" in action.option_strings:
                action.help = (
                    "Materialize locked source roots offline; project Config and index "
                    "refresh are separate commands."
                )
                break
        return parser

    def _cmd_init(self, *, quiet: bool = False) -> int:
        self._print_status("environment", "preparing Python environment")
        initialize_environment()
        return super()._cmd_init(quiet=quiet)


SCRIPT = WorkbenchSourceRootWorkflowScript(
    WORKFLOW,
    repo_display_name="WeldDataWorkbench",
)


def main(argv: list[str] | None = None) -> int:
    return SCRIPT.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
