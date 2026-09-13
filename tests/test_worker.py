"""Layer 7 — the worker loop: claim -> score -> persist -> close, safely
(ADR-006, ADR-011, ADR-012). Real Postgres via testcontainers; FakeScorer for
speed except where noted. Needs Docker; marked `db`.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

pytest.importorskip("testcontainers")
pytest.importorskip("psycopg_pool")

from testcontainers.postgres import PostgresContainer  # noqa: E402

from pipeline.blobstore import upsert_blob  # noqa: E402
from pipeline.config import Config  # noqa: E402
from pipeline.db import open_pool  # noqa: E402
from pipeline.hashing import content_hash  # noqa: E402
from pipeline.ingest import ingest_directory  # noqa: E402
from pipeline.migrate import apply_migrations  # noqa: E402
from pipeline.queue import ClaimedJob, PgJobQueue  # noqa: E402
from pipeline.resultstore import get_result  # noqa: E402
from pipeline.sentiment import TurnScore, _has_scoreable_signal  # noqa: E402
from pipeline.worker import process_one, run  # noqa: E402

pytestmark = pytest.mark.db

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "conversations"
CFG = Config()


class FakeScorer:
    """Deterministic, keyword-based stand-in — no model needed. Mirrors the
    real empty-text rule so status classification (which depends only on that,
    not on sentiment values) matches the real Scorer exactly. Duplicated from
    test_result.py's FakeScorer rather than shared, to keep each test file
    self-contained."""

    NEGATIVE_WORDS = ("bad", "broken", "terrible", "furious", "useless", "unacceptable", "cancel")
    POSITIVE_WORDS = ("good", "great", "thank", "relief", "helpful", "appreciate")

    def score_texts(self, texts: list[str]) -> list[TurnScore]:
        out = []
        for t in texts:
            if not _has_scoreable_signal(t):
                out.append(
                    TurnScore(
                        scored=False, label=None, signed=None, confidence=None, reason="empty_text"
                    )
                )
                continue
            low = t.lower()
            if any(w in low for w in self.NEGATIVE_WORDS):
                out.append(TurnScore(scored=True, label="negative", signed=-0.8, confidence=0.9))
            elif any(w in low for w in self.POSITIVE_WORDS):
                out.append(TurnScore(scored=True, label="positive", signed=0.8, confidence=0.9))
            else:
                out.append(TurnScore(scored=True, label="neutral", signed=0.0, confidence=0.6))
        return out


class RaisingScorer:
    """Proves a code path never calls the (possibly expensive) scorer."""

    def score_texts(self, texts: list[str]) -> list[TurnScore]:
        raise AssertionError(f"score_texts should not have been called with {texts!r}")


FAKE = FakeScorer()


@pytest.fixture(scope="module")
def pg_dsn():
    with PostgresContainer("postgres:16") as pg:
        yield pg.get_connection_url().replace("postgresql+psycopg2", "postgresql")


@pytest.fixture
def pool(pg_dsn):
    apply_migrations(pg_dsn)
    p = open_pool(pg_dsn)
    with p.connection() as conn:
        conn.execute("TRUNCATE conversation_blobs, jobs, results, ingest_dead_letters")
    yield p
    p.close()


@pytest.fixture
def queue(pool):
    return PgJobQueue(pool)


def ingest_all(pool, queue):
    return ingest_directory(
        DATA_DIR,
        queue=queue,
        store_blob=lambda t, c, h, r: upsert_blob(pool, t, c, h, r),
    )


# --- the exit criterion: all 27 fixtures, expected status each ----------------

EXPECTED_STATUS: dict[str, str] = {
    **{f"c-{i:06d}": "scored" for i in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)},
    "c-000016": "scored",  # single customer turn
    "c-000017": "rejected",  # zero customer turns
    "c-000018": "rejected",  # empty turns array
    "c-000019": "scored",  # some blank turns, one real one — still scored
    "c-000020": "scored",  # exactly two customer turns
    "c-000021": "scored",  # non-monotonic seq
    "c-000022": "scored",  # emoji scored, punctuation-only skipped
    "c-000023": "scored",  # sarcasm — not our problem, still parses & scores
    "c-000024": "scored",  # French
    "c-000025": "scored",  # Japanese
    "c-000026": "scored",  # mixed language
    "c-000027": "scored",  # very long turn
    "c-000028": "scored",  # 200 turns
    "c-000029": "rejected",  # missing turns key
    "c-000030": "rejected",  # turns wrong type
    "c-000031": "partial",  # mixed bad turns, 2 good customer turns remain
    "c-000032": "rejected",  # only bot roles
}


def test_full_drain_matches_expected_status_per_fixture(pool, queue):
    assert len(EXPECTED_STATUS) == 27

    ingest_all(pool, queue)
    processed = run(CFG, pool, queue, FAKE, once=True)
    assert processed == 27

    with pool.connection() as conn:
        rows = conn.execute("SELECT conversation_id, status FROM results").fetchall()
    actual = dict(rows)

    assert actual == EXPECTED_STATUS

    with pool.connection() as conn:
        remaining = conn.execute(
            "SELECT count(*) FROM jobs WHERE status IN ('queued', 'claimed')"
        ).fetchone()[0]
    assert remaining == 0

    with pool.connection() as conn:
        done_dead = dict(conn.execute("SELECT status, count(*) FROM jobs GROUP BY 1").fetchall())
    assert done_dead.get("done", 0) == sum(
        1 for s in EXPECTED_STATUS.values() if s in ("scored", "partial")
    )
    assert done_dead.get("dead", 0) == sum(1 for s in EXPECTED_STATUS.values() if s == "rejected")


def test_second_run_finds_nothing_left_to_claim(pool, queue):
    ingest_all(pool, queue)
    run(CFG, pool, queue, FAKE, once=True)

    ingest_all(pool, queue)  # re-ingest: unchanged content, no-op enqueue
    second = run(CFG, pool, queue, FAKE, once=True)
    assert second == 0


# --- process_one, tested directly: poison, missing blob, duplicate skip -------


def test_poison_job_is_rejected_and_marked_dead(pool, queue):
    queue.enqueue("acme", "p-1", "acme/p-1", "sha256:aaa")
    job = ClaimedJob("acme", "p-1", "acme/p-1", "sha256:aaa", delivery_count=CFG.max_delivery + 1)

    outcome = process_one(job, CFG, pool, queue, RaisingScorer())

    assert outcome == "dead"
    result = get_result(pool, "acme", "p-1")
    assert result["status"] == "rejected"
    assert result["error"] == {
        "reason": "max_delivery_exceeded",
        "detail": f"delivery_count={CFG.max_delivery + 1}",
    }
    with pool.connection() as conn:
        status = conn.execute(
            "SELECT status FROM jobs WHERE tenant_id='acme' AND conversation_id='p-1'"
        ).fetchone()[0]
    assert status == "dead"


def test_missing_blob_is_rejected_and_marked_dead(pool, queue):
    # enqueued directly, never given a blob — simulates the pointer outliving the blob
    queue.enqueue("acme", "p-2", "acme/p-2", "sha256:bbb")
    job = ClaimedJob("acme", "p-2", "acme/p-2", "sha256:bbb", delivery_count=1)

    outcome = process_one(job, CFG, pool, queue, RaisingScorer())

    assert outcome == "dead"
    result = get_result(pool, "acme", "p-2")
    assert result["status"] == "rejected"
    assert result["error"]["reason"] == "blob_missing"


def test_duplicate_delivery_skips_scoring_entirely(pool, queue):
    raw = {
        "tenant_id": "acme",
        "conversation_id": "p-3",
        "turns": [
            {"seq": 0, "role": "customer", "ts": "2026-01-01T00:00:00Z", "text": "thank you"}
        ],
    }
    doc_hash = content_hash(raw)
    upsert_blob(pool, "acme", "p-3", doc_hash, raw)
    queue.enqueue("acme", "p-3", "acme/p-3", doc_hash)

    job = ClaimedJob("acme", "p-3", "acme/p-3", doc_hash, delivery_count=1)
    first_outcome = process_one(job, CFG, pool, queue, FAKE)
    assert first_outcome == "done"
    first_result = get_result(pool, "acme", "p-3")

    # Simulate a stale-claim reclaim of the SAME (already-scored) job: same
    # content hash, higher delivery_count. The RaisingScorer proves scoring
    # is skipped, not just re-run to the same answer.
    reclaimed = ClaimedJob("acme", "p-3", "acme/p-3", doc_hash, delivery_count=2)
    second_outcome = process_one(reclaimed, CFG, pool, queue, RaisingScorer())

    assert second_outcome == "skipped_duplicate"
    assert get_result(pool, "acme", "p-3") == first_result  # untouched
    with pool.connection() as conn:
        status = conn.execute(
            "SELECT status FROM jobs WHERE tenant_id='acme' AND conversation_id='p-3'"
        ).fetchone()[0]
    assert status == "done"


def test_changed_content_after_reclaim_is_rescored_not_skipped(pool, queue):
    raw_v1 = {
        "tenant_id": "acme",
        "conversation_id": "p-4",
        "turns": [
            {"seq": 0, "role": "customer", "ts": "2026-01-01T00:00:00Z", "text": "thank you"}
        ],
    }
    hash_v1 = content_hash(raw_v1)
    upsert_blob(pool, "acme", "p-4", hash_v1, raw_v1)
    process_one(ClaimedJob("acme", "p-4", "acme/p-4", hash_v1, 1), CFG, pool, queue, FAKE)

    raw_v2 = {
        **raw_v1,
        "turns": [
            {"seq": 0, "role": "customer", "ts": "2026-01-01T00:00:00Z", "text": "this is bad"}
        ],
    }
    hash_v2 = content_hash(raw_v2)
    upsert_blob(pool, "acme", "p-4", hash_v2, raw_v2)

    outcome = process_one(ClaimedJob("acme", "p-4", "acme/p-4", hash_v2, 1), CFG, pool, queue, FAKE)
    assert outcome == "done"
    assert get_result(pool, "acme", "p-4")["overall_sentiment"]["label"] == "negative"


# --- reproducibility of process_one itself (brief §3.3) ------------------------


def test_process_one_reproducible_except_scored_at(pool, queue):
    raw = {
        "tenant_id": "acme",
        "conversation_id": "p-5",
        "turns": [
            {"seq": 0, "role": "customer", "ts": "2026-01-01T00:00:00Z", "text": "great job"}
        ],
    }
    doc_hash = content_hash(raw)
    upsert_blob(pool, "acme", "p-5", doc_hash, raw)
    job = ClaimedJob("acme", "p-5", "acme/p-5", doc_hash, delivery_count=1)

    process_one(job, CFG, pool, queue, FAKE)
    first = get_result(pool, "acme", "p-5")

    # A stale-claim reclaim re-scores it (content unchanged, but delivery_count
    # bumped) — the row must come back identical except possibly scored_at
    # (which can land in the same second as a fast, back-to-back call).
    process_one(
        ClaimedJob("acme", "p-5", "acme/p-5", doc_hash, delivery_count=2), CFG, pool, queue, FAKE
    )
    second = get_result(pool, "acme", "p-5")

    first_no_ts = {**first, "provenance": {**first["provenance"], "scored_at": None}}
    second_no_ts = {**second, "provenance": {**second["provenance"], "scored_at": None}}
    assert first_no_ts == second_no_ts


# --- concurrency: two workers draining the same queue --------------------------


def test_two_concurrent_workers_process_every_job_exactly_once(pool, queue):
    ingest_all(pool, queue)

    def drain(wid: str) -> int:
        return run(CFG, pool, queue, FAKE, once=True, id_=wid)

    with ThreadPoolExecutor(max_workers=2) as pool_exec:
        counts = list(pool_exec.map(drain, ["worker-a", "worker-b"]))

    assert sum(counts) == 27  # every job processed, none twice, none missed
    with pool.connection() as conn:
        remaining = conn.execute(
            "SELECT count(*) FROM jobs WHERE status IN ('queued', 'claimed')"
        ).fetchone()[0]
        total_results = conn.execute("SELECT count(*) FROM results").fetchone()[0]
    assert remaining == 0
    assert total_results == 27
