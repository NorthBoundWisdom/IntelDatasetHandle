#!/usr/bin/env python3
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FREECM_ROOT = REPO_ROOT / "FreeCM"
if str(FREECM_ROOT) not in sys.path:
    sys.path.insert(0, str(FREECM_ROOT))

from freecm.dependency_roots import (  # noqa: E402
    DependencyRootConfig,
    ResolvedDependencyRoots,
    bind_dependency_root_workflow,
)
from freecm.dependency_workflow import DependencyRootWorkflowFacade  # noqa: E402

CONFIG = DependencyRootConfig(
    repo_root=REPO_ROOT,
    dependency_root_specs=(),
    repo_display_name="WeldDataWorkbench",
)


@dataclass(frozen=True, slots=True)
class WorkbenchSourceRoots:
    dependency_roots: ResolvedDependencyRoots

    @property
    def lock_data(self) -> dict[str, object]:
        return self.dependency_roots.lock_data


class WorkbenchSourceRootWorkflow(DependencyRootWorkflowFacade[WorkbenchSourceRoots]):
    def _wrap_dependency_roots(
        self,
        dependency_roots: ResolvedDependencyRoots,
    ) -> WorkbenchSourceRoots:
        return WorkbenchSourceRoots(dependency_roots=dependency_roots)


MANAGER = bind_dependency_root_workflow(
    globals(),
    CONFIG,
)
WORKFLOW = WorkbenchSourceRootWorkflow(CONFIG)


if __name__ == "__main__":
    raise SystemExit(MANAGER.main())
