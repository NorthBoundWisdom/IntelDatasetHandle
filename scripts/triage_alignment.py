from __future__ import annotations

import argparse
from pathlib import Path

from weld_data_workbench.alignment_triage import (
    triage_alignment_batch,
    write_alignment_triage_csv,
    write_alignment_triage_json,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rank real-data alignment outliers for deterministic human review."
    )
    parser.add_argument("input", type=Path, help="alignment-batch JSON report")
    parser.add_argument("--output", "-o", type=Path, default=None, help="triage JSON output")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--include-good", action="store_true")
    args = parser.parse_args()

    source = args.input.expanduser().resolve()
    output = (
        args.output.expanduser().resolve()
        if args.output is not None
        else source.with_name(source.stem + "-triage.json")
    )
    report = triage_alignment_batch(source, limit=args.limit, include_good=args.include_good)
    json_path = write_alignment_triage_json(report, output)
    csv_path = write_alignment_triage_csv(report, output.with_suffix(".csv"))
    print(f"triage cases: {report.selected_count}/{report.sample_count}")
    print(f"json: {json_path}")
    print(f"csv: {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
