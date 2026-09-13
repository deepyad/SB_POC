"""Layer 7 — the worker loop: claim, score, persist, close — safely under
concurrency (ADR-006, ADR-011, ADR-012). Wires every prior layer together.

`process_one` handles a single already-claimed job and is deliberately
public — tests drive it directly to prove poison handling, the blob-missing
path, and the duplicate-delivery skip, without needing a live claim race.
`run` is the loop `process_one` sits inside.
"""

from __future__ import annotations

import socket
import time
import uuid
from datetime import UTC, datetime

from psycopg_pool import ConnectionPool

from pipeline.blobstore import get_blob
from pipeline.config import Config
from pipeline.queue import ClaimedJob, Queue
from pipeline.result import ScorerLike, _iso_z, score_conversation
from pipeline.resultstore import close_job_with_result, get_result


def worker_id() -> str:
    return f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"


def _rejected_row(
    tenant_id: str,
    conversation_id: str,
    content_hash: str,
    cfg: Config,
    now: datetime,
    reason: str,
    detail: str = "",
) -> dict:
    """A `results` row shaped like `score_conversation`'s rejected branch, for
    the two paths that never reach it: poison and a missing blob."""
    return {
        "tenant_id": tenant_id,
        "conversation_id": conversation_id,
        "content_hash": content_hash,
        "schema_version": cfg.schema_version,
        "provenance": {
            "model_name": cfg.model_name,
            "model_revision": cfg.model_revision,
            "scored_at": _iso_z(now),
        },
        "params": cfg.metric_params(),
        "status": "rejected",
        "overall_sentiment": None,
        "sentiment_trajectory": None,
        "per_turn": [],
        "dropped_turns": [],
        "error": {"reason": reason, "detail": detail},
    }


def process_one(
    job: ClaimedJob,
    cfg: Config,
    pool: ConnectionPool,
    queue: Queue,
    scorer: ScorerLike,
) -> str:
    """Process one claimed job to a terminal state. Returns the outcome:
    ``"done"``, ``"dead"``, or ``"skipped_duplicate"``.
    """
    now = datetime.now(UTC)

    # Poison: this job has been redelivered past the limit (ADR-012). Stop
    # retrying it — a human or a replay job looks at the `dead_letters` view.
    if job.delivery_count > cfg.max_delivery:
        row = _rejected_row(
            job.tenant_id,
            job.conversation_id,
            job.content_hash,
            cfg,
            now,
            "max_delivery_exceeded",
            f"delivery_count={job.delivery_count}",
        )
        close_job_with_result(pool, row, "dead")
        return "dead"

    # Duplicate delivery (ADR-005): a terminal result already exists for this
    # exact content — most likely a job reclaimed after its lease expired even
    # though the original worker's write had already committed. Skip the
    # (possibly expensive) re-scoring; just close the job.
    existing = get_result(pool, job.tenant_id, job.conversation_id)
    if existing is not None and existing["content_hash"] == job.content_hash:
        queue.mark_done(job.tenant_id, job.conversation_id)
        return "skipped_duplicate"

    blob = get_blob(pool, job.tenant_id, job.conversation_id)
    if blob is None:
        row = _rejected_row(
            job.tenant_id, job.conversation_id, job.content_hash, cfg, now, "blob_missing"
        )
        close_job_with_result(pool, row, "dead")
        return "dead"

    row = score_conversation(blob["raw"], cfg, scorer, now)
    job_status = "dead" if row["status"] == "rejected" else "done"
    close_job_with_result(pool, row, job_status)
    return job_status


def run(
    cfg: Config,
    pool: ConnectionPool,
    queue: Queue,
    scorer: ScorerLike,
    *,
    once: bool = False,
    id_: str | None = None,
) -> int:
    """Claim batches and process them until the queue is empty.

    ``once=True`` drains whatever is currently queued and returns the count —
    used by ``run --once`` and the tests. Without it, sleeps and retries
    forever (the production shape, one process per container).
    """
    wid = id_ or worker_id()
    processed = 0
    while True:
        jobs = queue.claim(wid, cfg.claim_batch, cfg.lease_seconds)
        if not jobs:
            if once:
                return processed
            time.sleep(cfg.poll_idle_seconds)
            continue
        for job in jobs:
            process_one(job, cfg, pool, queue, scorer)
            processed += 1
