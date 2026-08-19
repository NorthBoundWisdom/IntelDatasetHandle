from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from weld_data_workbench.sqlite_utils import closing_connection


def test_closing_connection_commits_and_explicitly_closes(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    connection = sqlite3.connect(path)

    with closing_connection(connection) as active:
        active.execute("CREATE TABLE values_table(value INTEGER NOT NULL)")
        active.execute("INSERT INTO values_table(value) VALUES(7)")

    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")

    verification = sqlite3.connect(path)
    try:
        assert verification.execute("SELECT value FROM values_table").fetchone() == (7,)
    finally:
        verification.close()


def test_closing_connection_rolls_back_and_closes_on_error(tmp_path: Path) -> None:
    path = tmp_path / "rollback.sqlite3"
    setup = sqlite3.connect(path)
    try:
        setup.execute("CREATE TABLE values_table(value INTEGER NOT NULL)")
        setup.commit()
    finally:
        setup.close()

    connection = sqlite3.connect(path)
    with pytest.raises(RuntimeError, match="stop"), closing_connection(connection) as active:
        active.execute("INSERT INTO values_table(value) VALUES(9)")
        raise RuntimeError("stop")

    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")

    verification = sqlite3.connect(path)
    try:
        assert verification.execute("SELECT COUNT(*) FROM values_table").fetchone() == (0,)
    finally:
        verification.close()
