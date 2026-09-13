"""Layer 5 — storage: migrations, blobstore, and the one-transaction
result+job write (ADR-006). Real Postgres via testcontainers — needs Docker.
Marked `db`; excluded from the default `make test`.
"""

from __future__ import annotations

import pytest
from testcontainers.postgres import PostgresContainer

from pipeline.blobstore import blob_key, get_blob, upsert_blob
from pipeline.config import Config
from pipeline.db import open_pool
from pipeline.migrate import apply_migrations
from pipeline.resultstore import close_job_with_result, get_result

pytestmark = pytest.mark.db

CFG = Config()


@pytest.fixture(scope="module")
def pg_dsn():
    with PostgresContainer("postgres:16") as pg:
        # testcontainers defaults to a SQLAlchemy-style URL; psycopg3 wants a
        # plain libpq DSN.
        yield pg.get_connection_url().replace("postgresql+psycopg2", "postgresql")


@pytest.fixture(scope="module")
def pool(pg_dsn):
    applied = apply_migrations(pg_dsn)
    assert "001_init.sql" in applied
    p = open_pool(pg_dsn)
    yield p
    p.close()


def sample_row(
    conversation_id: str, tenant_id: str = "acme", status: str = "scored", score: float = 0.5
) -> dict:
    return {
        "tenant_id": tenant_id,
        "conversation_id": conversation_id,
        "content_hash": "sha256:deadbeef",
        "schema_version": CFG.schema_version,
        "provenance": {
            "model_name": CFG.model_name,
            "model_revision": CFG.model_revision,
            "scored_at": "2026-09-13T10:00:00Z",
        },
        "params": CFG.metric_params(),
        "status": status,
        "overall_sentiment": {
            "label": "positive",
            "score": score,
            "n_customer_turns_scored": 2,
            "basis": "recency_confidence_weighted_mean",
        },
        "sentiment_trajectory": {
            "value": 0.3,
            "slope": 0.6,
            "n_customer_turns_scored": 2,
            "meaningful": False,
        },
        "per_turn": [
            {
                "index": 0,
                "seq": 0,
                "role": "customer",
                "scored": True,
                "label": "positive",
                "score": score,
                "confidence": 0.9,
                "reason": None,
            }
        ],
        "dropped_turns": [],
        "error": None,
    }


def insert_job(pool, tenant_id: str, conversation_id: str, status: str = "claimed") -> None:
    with pool.connection() as conn:
        conn.execute(
            """
            INSERT INTO jobs (tenant_id, conversation_id, blob_key, content_hash, status)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, conversation_id) DO UPDATE SET status = EXCLUDED.status
            """,
            (
                tenant_id,
                conversation_id,
                blob_key(tenant_id, conversation_id),
                "sha256:deadbeef",
                status,
            ),
        )


def job_status(pool, tenant_id: str, conversation_id: str) -> str:
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT status FROM jobs WHERE tenant_id = %s AND conversation_id = %s",
            (tenant_id, conversation_id),
        ).fetchone()
    return row[0]


# --- migrations -----------------------------------------------------------


def test_migrations_are_idempotent(pg_dsn, pool):
    # `pool` fixture already applied migrations once against pg_dsn.
    assert apply_migrations(pg_dsn) == []


# --- blobstore --------------------------------------------------------------


def test_blob_upsert_and_get_roundtrip(pool):
    raw = {"tenant_id": "acme", "conversation_id": "c-blob-1", "turns": []}
    upsert_blob(pool, "acme", "c-blob-1", "sha256:aaa", raw)
    assert get_blob(pool, "acme", "c-blob-1") == {"raw": raw, "content_hash": "sha256:aaa"}


def test_get_blob_missing_returns_none(pool):
    assert get_blob(pool, "acme", "does-not-exist") is None


_INGESTED_AT_SQL = (
    "SELECT ingested_at FROM conversation_blobs WHERE tenant_id=%s AND conversation_id=%s"
)


def test_blob_upsert_same_hash_is_a_noop(pool):
    raw = {"tenant_id": "acme", "conversation_id": "c-blob-2", "turns": [1]}
    upsert_blob(pool, "acme", "c-blob-2", "sha256:bbb", raw)
    with pool.connection() as conn:
        before = conn.execute(_INGESTED_AT_SQL, ("acme", "c-blob-2")).fetchone()[0]

    upsert_blob(pool, "acme", "c-blob-2", "sha256:bbb", raw)  # same hash again

    with pool.connection() as conn:
        after = conn.execute(_INGESTED_AT_SQL, ("acme", "c-blob-2")).fetchone()[0]
    assert before == after  # the IS DISTINCT FROM guard skipped the write entirely


def test_blob_upsert_different_hash_updates(pool):
    upsert_blob(pool, "acme", "c-blob-3", "sha256:ccc", {"v": 1})
    upsert_blob(pool, "acme", "c-blob-3", "sha256:ddd", {"v": 2})
    assert get_blob(pool, "acme", "c-blob-3") == {"raw": {"v": 2}, "content_hash": "sha256:ddd"}


# --- resultstore: the one-transaction write (ADR-006) --------------------------


def test_close_job_with_result_writes_both_rows(pool):
    insert_job(pool, "acme", "c-res-1")
    row = sample_row("c-res-1")

    close_job_with_result(pool, row, "done")

    assert get_result(pool, "acme", "c-res-1") == row
    assert job_status(pool, "acme", "c-res-1") == "done"


def test_close_job_with_result_dead_status(pool):
    insert_job(pool, "acme", "c-res-2")
    row = sample_row("c-res-2", status="rejected", score=0.0)
    row["overall_sentiment"] = None
    row["sentiment_trajectory"] = None
    row["error"] = {"reason": "no_customer_turns", "detail": "0 customer turn(s), 0 scored"}

    close_job_with_result(pool, row, "dead")

    assert get_result(pool, "acme", "c-res-2")["status"] == "rejected"
    assert job_status(pool, "acme", "c-res-2") == "dead"


def test_close_job_with_result_rejects_bad_job_status(pool):
    with pytest.raises(ValueError):
        close_job_with_result(pool, sample_row("c-res-x"), "queued")


def test_get_result_missing_returns_none(pool):
    assert get_result(pool, "acme", "does-not-exist") is None


def test_result_upsert_overwrites_on_conflict(pool):
    insert_job(pool, "acme", "c-res-3")
    close_job_with_result(pool, sample_row("c-res-3", score=0.1), "done")
    close_job_with_result(pool, sample_row("c-res-3", score=0.9), "done")
    assert get_result(pool, "acme", "c-res-3")["overall_sentiment"]["score"] == 0.9


# --- atomicity: the point of ADR-006 -------------------------------------------


def test_transaction_is_atomic_on_failure(pool):
    insert_job(pool, "acme", "c-atomic-1")
    bad_row = sample_row("c-atomic-1")
    bad_row["status"] = "bogus-status"  # violates the results.status CHECK constraint

    with pytest.raises(Exception):  # noqa: B017 — any DB error proves the point
        close_job_with_result(pool, bad_row, "done")

    # Neither half of the transaction committed: no results row, job untouched.
    assert get_result(pool, "acme", "c-atomic-1") is None
    assert job_status(pool, "acme", "c-atomic-1") == "claimed"
