from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def closing_connection(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Commit/rollback a SQLite transaction and always close its connection.

    ``sqlite3.Connection`` is itself a transaction context manager, but leaving
    that context does not close the connection.  Keeping the explicit close in
    one helper prevents API queries and workspace stores from relying on garbage
    collection to release file descriptors.
    """

    try:
        with connection:
            yield connection
    finally:
        connection.close()
