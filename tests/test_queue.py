"""Layer 6 — PgJobQueue against real Postgres: the claim, the reclaim, and the
concurrency guarantee `FOR UPDATE SKIP LOCKED` exists for (ADR-002). Needs
Docker; marked `db`, excluded from the default `make test`.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

pytest.importorskip("testcontainers")
pytest.importorskip("psycopg_pool")

from testcontainers.postgres import PostgresContainer  # noqa: E402

from pipeline.db import open_pool  # noqa: E402
from pipeline.migrate import apply_migrations  # noqa: E402
from pipeline.queue import PgJobQueue  # noqa: E402

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def pg_dsn():
    with PostgresContainer("postgres:16") as pg:
        yield pg.get_connection_url().replace("postgresql+psycopg2", "postgresql")


@pytest.fixture(scope="module")
def pool(pg_dsn):
    assert "001_init.sql" in apply_migrations(pg_dsn)
    p = open_pool(pg_dsn)
    yield p
    p.close()


@pytest.fixture
def queue(pool):
    return PgJobQueue(pool)


def job_row(pool, tenant_id, conversation_id):
    with pool.connection() as conn:
        return conn.execute(
            "SELECT status, delivery_count, claimed_by FROM jobs "
            "WHERE tenant_id = %s AND conversation_id = %s",
            (tenant_id, conversation_id),
        ).fetchone()


# --- enqueue: the ingest-side half of de-dup (ADR-005) -------------------------


def test_enqueue_new_job(queue, pool):
    assert queue.enqueue("acme", "q-1", "acme/q-1", "sha256:aaa") is True
    status, delivery_count, _ = job_row(pool, "acme", "q-1")
    assert status == "queued"
    assert delivery_count == 0


def test_enqueue_same_hash_is_a_noop(queue, pool):
    queue.enqueue("acme", "q-2", "acme/q-2", "sha256:bbb")
    # claim it, so status is no longer 'queued' — a no-op enqueue must not reset that
    queue.claim("w1", batch=10, lease_seconds=60)
    assert queue.enqueue("acme", "q-2", "acme/q-2", "sha256:bbb") is False
    status, _, _ = job_row(pool, "acme", "q-2")
    assert status == "claimed"  # untouched by the no-op re-ingest


def test_enqueue_different_hash_requeues(queue, pool):
    queue.enqueue("acme", "q-3", "acme/q-3", "sha256:ccc")
    queue.claim("w1", batch=10, lease_seconds=60)
    assert queue.enqueue("acme", "q-3", "acme/q-3", "sha256:ddd") is True
    status, delivery_count, claimed_by = job_row(pool, "acme", "q-3")
    assert status == "queued"
    assert delivery_count == 0  # reset — this is treated as fresh work
    assert claimed_by is None


# --- claim -----------------------------------------------------------------


def test_claim_sets_status_and_delivery_count(queue, pool):
    queue.enqueue("acme", "q-4", "acme/q-4", "sha256:eee")
    [claimed] = [
        j for j in queue.claim("w1", batch=50, lease_seconds=60) if j.conversation_id == "q-4"
    ]
    assert claimed.tenant_id == "acme"
    assert claimed.blob_key == "acme/q-4"
    assert claimed.delivery_count == 1
    status, delivery_count, claimed_by = job_row(pool, "acme", "q-4")
    assert (status, delivery_count, claimed_by) == ("claimed", 1, "w1")


def test_claim_returns_nothing_when_queue_empty(queue):
    queue.enqueue("acme", "q-5", "acme/q-5", "sha256:fff")
    queue.claim("w1", batch=50, lease_seconds=60)  # drains it
    again = [j for j in queue.claim("w1", batch=50, lease_seconds=60) if j.conversation_id == "q-5"]
    assert again == []  # already claimed and not yet stale — not reclaimed


def test_mark_done(queue, pool):
    queue.enqueue("acme", "q-6", "acme/q-6", "sha256:111")
    queue.claim("w1", batch=50, lease_seconds=60)
    queue.mark_done("acme", "q-6")
    status, _, _ = job_row(pool, "acme", "q-6")
    assert status == "done"


# --- the stale-claim reclaim: what makes the pipeline survive a dead worker ----


def test_stale_claim_is_reclaimed(queue, pool):
    queue.enqueue("acme", "q-7", "acme/q-7", "sha256:222")
    [first] = [
        j for j in queue.claim("w1", batch=50, lease_seconds=60) if j.conversation_id == "q-7"
    ]
    assert first.delivery_count == 1

    # simulate w1 dying: back-date claimed_at past the lease window
    with pool.connection() as conn:
        conn.execute(
            "UPDATE jobs SET claimed_at = now() - interval '120 seconds' "
            "WHERE tenant_id = 'acme' AND conversation_id = 'q-7'"
        )

    reclaimed = [
        j for j in queue.claim("w2", batch=50, lease_seconds=60) if j.conversation_id == "q-7"
    ]
    assert len(reclaimed) == 1
    assert reclaimed[0].delivery_count == 2  # incremented again
    status, delivery_count, claimed_by = job_row(pool, "acme", "q-7")
    assert (status, delivery_count, claimed_by) == ("claimed", 2, "w2")


def test_fresh_claim_is_not_reclaimed_within_the_lease(queue, pool):
    queue.enqueue("acme", "q-8", "acme/q-8", "sha256:333")
    queue.claim("w1", batch=50, lease_seconds=60)
    still_owned = [
        j for j in queue.claim("w2", batch=50, lease_seconds=60) if j.conversation_id == "q-8"
    ]
    assert still_owned == []


# --- the actual point of ADR-002: SKIP LOCKED means no double-claim -----------


def test_concurrent_claims_never_double_claim(queue, pool):
    ids = [f"c-{i}" for i in range(20)]
    for cid in ids:
        queue.enqueue("acme", cid, f"acme/{cid}", f"sha256:{cid}")

    def do_claim(worker_id: str) -> list[str]:
        return [j.conversation_id for j in queue.claim(worker_id, batch=5, lease_seconds=60)]

    with ThreadPoolExecutor(max_workers=4) as pool_exec:
        results = list(pool_exec.map(do_claim, [f"w{i}" for i in range(4)]))

    all_claimed = [cid for batch in results for cid in batch]
    ours = [cid for cid in all_claimed if cid in ids]

    assert len(ours) == len(set(ours))  # no conversation claimed twice
    assert len(ours) == 20  # every job claimed exactly once, across 4 workers
