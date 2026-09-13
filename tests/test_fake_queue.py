"""FakeQueue on its own: exists to satisfy the Queue Protocol for fast tests,
but only `enqueue` was actually exercised elsewhere (test_ingest.py) — nothing
in the codebase happens to call `claim`/`mark_done` on it, since `process_one`
needs a real Postgres pool regardless of which Queue it's given. Direct tests
here so the double is proven correct even though it's currently unused past
`enqueue`.
"""

import time

from pipeline.queue import FakeQueue


def test_claim_returns_queued_jobs_and_increments_delivery_count():
    q = FakeQueue()
    q.enqueue("acme", "c-1", "acme/c-1", "sha256:aaa")

    [claimed] = q.claim("w1", batch=10, lease_seconds=60)

    assert claimed.tenant_id == "acme"
    assert claimed.conversation_id == "c-1"
    assert claimed.delivery_count == 1


def test_claim_respects_batch_size():
    q = FakeQueue()
    for i in range(5):
        q.enqueue("acme", f"c-{i}", f"acme/c-{i}", f"sha256:{i}")

    assert len(q.claim("w1", batch=3, lease_seconds=60)) == 3


def test_claimed_job_is_not_reclaimed_within_the_lease():
    q = FakeQueue()
    q.enqueue("acme", "c-1", "acme/c-1", "sha256:aaa")
    q.claim("w1", batch=10, lease_seconds=60)

    assert q.claim("w2", batch=10, lease_seconds=60) == []


def test_stale_claim_is_reclaimed():
    q = FakeQueue()
    q.enqueue("acme", "c-1", "acme/c-1", "sha256:aaa")
    q.claim("w1", batch=10, lease_seconds=0)  # lease "expires" immediately
    time.sleep(0.01)

    reclaimed = q.claim("w2", batch=10, lease_seconds=0)

    assert len(reclaimed) == 1
    assert reclaimed[0].delivery_count == 2


def test_mark_done_updates_status_and_is_a_noop_for_unknown_jobs():
    q = FakeQueue()
    q.enqueue("acme", "c-1", "acme/c-1", "sha256:aaa")
    q.claim("w1", batch=10, lease_seconds=60)

    q.mark_done("acme", "c-1")
    assert q.claim("w2", batch=10, lease_seconds=0) == []  # done, never reclaimed

    q.mark_done("acme", "does-not-exist")  # must not raise
