"""Layer 5 — apply migrations/*.sql, in filename order, idempotently.

Tracked in a `schema_migrations` table so re-running is a safe no-op once
applied. Not run automatically — it's an explicit step (`make migrate`
locally, `docker compose run --rm worker migrate` in Docker) before `ingest`
and `run`, not something the `worker` service's default command does on
every start.

    python -m pipeline.migrate
"""

from __future__ import annotations

import pathlib

import psycopg

from pipeline.config import Config

MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "migrations"


def apply_migrations(database_url: str) -> list[str]:
    applied: list[str] = []
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename    TEXT PRIMARY KEY,
                applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        already = {r[0] for r in conn.execute("SELECT filename FROM schema_migrations").fetchall()}
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in already:
                continue
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations (filename) VALUES (%s)", (path.name,))
            applied.append(path.name)
    return applied


def main() -> None:
    cfg = Config.from_env()
    applied = apply_migrations(cfg.database_url)
    print(f"applied: {', '.join(applied)}" if applied else "already up to date")


if __name__ == "__main__":
    main()
