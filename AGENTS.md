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

1. Update or add a focused test.
2. Make the smallest coherent implementation change.
3. Run `pytest -q` and `python -m compileall -q src scripts tests`.
4. For scanner/schema changes, run `make synthetic-smoke`.
5. Update `DevDocs/DATA_CONTRACT.md` if persisted fields or semantics change.
6. Update `TODO.md` only after the implementation and tests are complete.
