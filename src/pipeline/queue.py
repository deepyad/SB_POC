"""Layer 6 — the queue: a claim with `FOR UPDATE SKIP LOCKED` (ADR-002).

`PgJobQueue` and `FakeQueue` both satisfy `Queue`, so `ingest.py` and (Layer 7)
`worker.py` work identically against a real Postgres or an in-memory stand-in
for fast tests — the same pattern as `sentiment.Scorer` / a fake scorer.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

from psycopg_pool import ConnectionPool


@dataclass(frozen=True)
class ClaimedJob:
    tenant_id: str
    conversation_id: str
    blob_key: str
    content_hash: str
    delivery_count: int


class Queue(Protocol):
    def enqueue(
        self, tenant_id: str, conversation_id: str, blob_key: str, content_hash: str
    ) -> bool:
        """True if this created a new queue entry or requeued a changed one;
        False if an entry with the same content hash was already tracked
        (ADR-005 — the ingest-side half of de-duplication)."""
        ...

    def claim(self, worker_id: str, batch: int, lease_seconds: int) -> list[ClaimedJob]:
        """Atomically claim up to `batch` jobs that are queued, or were claimed
        by someone else more than `lease_seconds` ago (a dead worker's work
        comes back). Two callers running this concurrently get disjoint jobs."""
        ...

    def mark_done(self, tenant_id: str, conversation_id: str) -> None:
        """Close a job with no results write — the duplicate-delivery skip
        path (ADR-005): a terminal result already exists for this content
        hash, so there is nothing new to score, just the job to close."""
        ...


class PgJobQueue:
    """The real queue: a `jobs` table claimed with `FOR UPDATE SKIP LOCKED`."""

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def enqueue(
        self, tenant_id: str, conversation_id: str, blob_key: str, content_hash: str
    ) -> bool:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO jobs (tenant_id, conversation_id, blob_key, content_hash, status)
                VALUES (%(tenant_id)s, %(conversation_id)s, %(blob_key)s,
                        %(content_hash)s, 'queued')
                ON CONFLICT (tenant_id, conversation_id) DO UPDATE SET
                    blob_key       = EXCLUDED.blob_key,
                    content_hash   = EXCLUDED.content_hash,
                    status         = 'queued',
                    claimed_by     = NULL,
                    claimed_at     = NULL,
                    delivery_count = 0,
                    last_error     = NULL,
                    enqueued_at    = now()
                WHERE jobs.content_hash IS DISTINCT FROM EXCLUDED.content_hash
                RETURNING 1
                """,
                {
                    "tenant_id": tenant_id,
                    "conversation_id": conversation_id,
                    "blob_key": blob_key,
                    "content_hash": content_hash,
                },
            ).fetchone()
        return row is not None

    def claim(self, worker_id: str, batch: int, lease_seconds: int) -> list[ClaimedJob]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                WITH claimable AS (
                    SELECT tenant_id, conversation_id FROM jobs
                    WHERE status = 'queued'
                       OR (status = 'claimed'
                           AND claimed_at < now() - make_interval(secs => %(lease)s))
                    ORDER BY enqueued_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT %(batch)s
                )
                UPDATE jobs SET
                    status         = 'claimed',
                    claimed_by     = %(worker_id)s,
                    claimed_at     = now(),
                    delivery_count = jobs.delivery_count + 1
                FROM claimable
                WHERE jobs.tenant_id = claimable.tenant_id
                  AND jobs.conversation_id = claimable.conversation_id
                RETURNING jobs.tenant_id, jobs.conversation_id, jobs.blob_key,
                          jobs.content_hash, jobs.delivery_count
                """,
                {"worker_id": worker_id, "lease": lease_seconds, "batch": batch},
            ).fetchall()
        return [ClaimedJob(*row) for row in rows]

    def mark_done(self, tenant_id: str, conversation_id: str) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "UPDATE jobs SET status = 'done' WHERE tenant_id = %s AND conversation_id = %s",
                (tenant_id, conversation_id),
            )


@dataclass
class _FakeRow:
    blob_key: str
    content_hash: str
    status: str = "queued"
    delivery_count: int = 0
    claimed_at: float | None = None


class FakeQueue:
    """In-memory stand-in for tests — same behaviour as `PgJobQueue`, no DB."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], _FakeRow] = {}

    def enqueue(
        self, tenant_id: str, conversation_id: str, blob_key: str, content_hash: str
    ) -> bool:
        key = (tenant_id, conversation_id)
        existing = self._rows.get(key)
        if existing is not None and existing.content_hash == content_hash:
            return False
        self._rows[key] = _FakeRow(blob_key=blob_key, content_hash=content_hash)
        return True

    def claim(self, worker_id: str, batch: int, lease_seconds: int) -> list[ClaimedJob]:
        del worker_id
        now = time.monotonic()
        claimed: list[ClaimedJob] = []
        for (tenant_id, conversation_id), r in self._rows.items():
            if len(claimed) >= batch:
                break
            stale = (
                r.status == "claimed"
                and r.claimed_at is not None
                and (now - r.claimed_at) > lease_seconds
            )
            if r.status == "queued" or stale:
                r.status = "claimed"
                r.claimed_at = now
                r.delivery_count += 1
                claimed.append(
                    ClaimedJob(
                        tenant_id, conversation_id, r.blob_key, r.content_hash, r.delivery_count
                    )
                )
        return claimed

    def mark_done(self, tenant_id: str, conversation_id: str) -> None:
        row = self._rows.get((tenant_id, conversation_id))
        if row is not None:
            row.status = "done"
