from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import AppConfig
from .index.database import connect_database

SPLIT_ARTIFACT_SCHEMA_VERSION = 1


def _stable_unit(seed: int, value: str) -> float:
    digest = hashlib.sha256(f"{seed}:{value}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / float(2**64)


@dataclass(frozen=True, slots=True)
class LeakageAudit:
    total_sessions: int
    cross_split_sessions: dict[str, list[str]]
    cross_split_sample_count: int
    exact_asset_hash_cross_split: dict[str, list[str]]

    @property
    def has_session_leakage(self) -> bool:
        return bool(self.cross_split_sessions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_sessions": self.total_sessions,
            "cross_split_session_count": len(self.cross_split_sessions),
            "cross_split_sessions": self.cross_split_sessions,
            "cross_split_sample_count": self.cross_split_sample_count,
            "exact_asset_hash_cross_split": self.exact_asset_hash_cross_split,
        }


def audit_upstream_split(config: AppConfig) -> LeakageAudit:
    with connect_database(config.index_path, read_only=True) as connection:
        rows = connection.execute(
            "SELECT session_id, split, COUNT(*) FROM samples "
            "WHERE session_id IS NOT NULL AND split IS NOT NULL "
            "GROUP BY session_id, split ORDER BY session_id, split"
        ).fetchall()
        by_session: dict[str, dict[str, int]] = defaultdict(dict)
        for session_id, split, count in rows:
            by_session[str(session_id)][str(split)] = int(count)

        cross = {
            session: sorted(splits) for session, splits in by_session.items() if len(splits) > 1
        }
        cross_samples = sum(sum(by_session[session].values()) for session in cross)

        duplicate_rows = connection.execute(
            "SELECT sha256, GROUP_CONCAT(DISTINCT s.split), COUNT(*) "
            "FROM assets a JOIN samples s ON s.sample_id = a.sample_id "
            "WHERE a.sha256 IS NOT NULL AND s.split IS NOT NULL "
            "GROUP BY sha256 HAVING COUNT(DISTINCT s.split) > 1 ORDER BY sha256"
        ).fetchall()
        exact_hashes: dict[str, list[str]] = {}
        for sha256, raw_splits, _count in duplicate_rows:
            exact_hashes[str(sha256)] = sorted(str(raw_splits).split(","))

    return LeakageAudit(
        total_sessions=len(by_session),
        cross_split_sessions=cross,
        cross_split_sample_count=cross_samples,
        exact_asset_hash_cross_split=exact_hashes,
    )


def _validate_ratios(train: float, validation: float, test: float) -> None:
    values = (train, validation, test)
    if any(value < 0 for value in values):
        raise ValueError("Split ratios must be non-negative")
    if abs(sum(values) - 1.0) > 1e-9:
        raise ValueError("Split ratios must sum to 1.0")


def session_holdout_assignments(
    config: AppConfig,
    *,
    seed: int = 0,
    train: float = 0.7,
    validation: float = 0.15,
    test: float = 0.15,
) -> dict[str, str]:
    """Assign each acquisition session to exactly one experimental partition."""

    _validate_ratios(train, validation, test)
    with connect_database(config.index_path, read_only=True) as connection:
        sessions = [
            str(row[0])
            for row in connection.execute(
                "SELECT DISTINCT session_id FROM samples "
                "WHERE session_id IS NOT NULL ORDER BY session_id"
            ).fetchall()
        ]

    train_edge = train
    validation_edge = train + validation
    assignments: dict[str, str] = {}
    for session in sessions:
        value = _stable_unit(seed, session)
        if value < train_edge:
            split = "train"
        elif value < validation_edge:
            split = "validation"
        else:
            split = "test"
        assignments[session] = split
    return assignments


def grouped_kfold_assignments(
    config: AppConfig, *, folds: int = 5, seed: int = 0
) -> dict[str, int]:
    if folds < 2:
        raise ValueError("folds must be at least 2")
    with connect_database(config.index_path, read_only=True) as connection:
        sessions = [
            str(row[0])
            for row in connection.execute(
                "SELECT DISTINCT session_id FROM samples "
                "WHERE session_id IS NOT NULL ORDER BY session_id"
            ).fetchall()
        ]
    ranked = sorted(sessions, key=lambda session: (_stable_unit(seed, session), session))
    return {session: index % folds for index, session in enumerate(ranked)}


def sample_assignments_from_sessions(
    config: AppConfig, session_assignments: dict[str, str | int]
) -> dict[str, str | int]:
    with connect_database(config.index_path, read_only=True) as connection:
        rows = connection.execute(
            "SELECT sample_id, session_id FROM samples ORDER BY sample_id"
        ).fetchall()
    result: dict[str, str | int] = {}
    for sample_id, session_id in rows:
        session = str(session_id)
        if session not in session_assignments:
            raise KeyError(f"No experimental split assignment for session {session!r}")
        result[str(sample_id)] = session_assignments[session]
    return result


def _artifact_id(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def write_split_artifact(
    config: AppConfig,
    output: Path,
    *,
    mode: str = "holdout",
    seed: int = 0,
    train: float = 0.7,
    validation: float = 0.15,
    test: float = 0.15,
    folds: int = 5,
) -> dict[str, Any]:
    if mode == "holdout":
        sessions: dict[str, str | int] = session_holdout_assignments(
            config,
            seed=seed,
            train=train,
            validation=validation,
            test=test,
        )
        parameters: dict[str, Any] = {
            "train": train,
            "validation": validation,
            "test": test,
        }
    elif mode == "kfold":
        sessions = grouped_kfold_assignments(config, folds=folds, seed=seed)
        parameters = {"folds": folds}
    else:
        raise ValueError("mode must be 'holdout' or 'kfold'")

    samples = sample_assignments_from_sessions(config, sessions)
    body: dict[str, Any] = {
        "schema_version": SPLIT_ARTIFACT_SCHEMA_VERSION,
        "mode": mode,
        "seed": seed,
        "parameters": parameters,
        "session_assignments": dict(sorted(sessions.items())),
        "sample_assignments": dict(sorted(samples.items())),
    }
    artifact = {"split_artifact_id": _artifact_id(body), **body}
    destination = output.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return artifact
