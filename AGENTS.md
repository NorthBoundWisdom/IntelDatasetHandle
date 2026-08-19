# AGENTS.md

## Repository purpose

This repository is a local-first dataset workbench. Preserve the separation between raw data, generated workspace artifacts, user interfaces, and research experiments.

## Non-negotiable rules

- Never add raw Intel dataset files, previews derived from real samples, or model checkpoints trained on the real dataset to Git.
- Do not write generated files into the raw dataset tree by default.
- Do not hard-code the archive's internal root directory, manifest filename, audio sample rate, or exact sensor column names.
- A corrupt sample must produce a structured issue; it must not abort indexing of unrelated samples.
- Media decoding must remain lazy and bounded. Do not load the complete dataset or a complete long recording into memory without an explicit option.
- Keep the SQLite schema backward-compatible or add an explicit migration and schema-version bump.
- Validate paths before serving files through the API.
- Keep optional frontends and ML dependencies out of core imports.

## Branch and commit policy

- Agent-authored development happens directly on the latest `main` branch. Do not create feature branches, fix branches, CI-validation branches, temporary branches, or pull requests unless the user explicitly asks for one.
- Before writing, refresh/re-read `main` and base changes on its current HEAD. If `main` advanced during the task, reconcile with the latest `main` before pushing further changes.
- Push coherent implementation batches directly to `main`; do not create marker-only or no-op commits merely to trigger CI.
- When GitHub Actions fails, diagnose and repair the failure directly on `main` rather than creating a validation branch.
- Prefer substantial coherent commits over frequent micro-commits. When the scope naturally supports it, accumulate roughly 500 or more lines of meaningful implementation/test/documentation changes before committing; correctness fixes required to restore a broken `main` are exempt.
- Do not force-push or rewrite `main` history unless the user explicitly requests history rewriting for that operation.

## Architecture boundaries

- `domain/`: pure data definitions and normalization.
- `io/`: discovery, manifest parsing, archive handling, media probing.
- `index/`: SQLite persistence and queries.
- `validation/`: dataset-level invariants and reports.
- `previews/`: bounded derivative generation.
- `features/`: deterministic feature extraction.
- `ml/`: optional research baselines, not the core data contract.
- `api/` and `gui/`: adapters over the repository; they must not rescan the raw tree themselves.

## Change workflow

1. Refresh/re-read the latest `main`; all agent-authored changes stay on `main` unless explicitly instructed otherwise.
2. Update or add a focused test.
3. Make the smallest coherent implementation change that belongs in the current batch.
4. Run `pytest -q` and `python -m compileall -q src scripts tests`.
5. For scanner/schema changes, run `make synthetic-smoke`.
6. Update `DevDocs/DATA_CONTRACT.md` if persisted fields or semantics change.
7. Update `TODO.md` only after the implementation and tests are complete.
8. Push the coherent batch directly to `main` and verify GitHub Actions; repair CI failures on `main`.
