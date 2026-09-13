"""Layer 5 — a psycopg connection pool.

No module-level singleton: the worker, scripts, and tests each open a pool
against the DSN they need and close it when done. That keeps a test's
ephemeral testcontainers Postgres fully isolated from any other pool, and
keeps this module honest about not hiding global state.
"""

from __future__ import annotations

from psycopg_pool import ConnectionPool


def open_pool(database_url: str) -> ConnectionPool:
    return ConnectionPool(database_url, min_size=1, max_size=10, open=True)
