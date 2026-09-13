"""Layer 6 — ingest + de-duplication, no database (FakeQueue + an in-memory
blob recorder). Real-Postgres claim behaviour is tests/test_queue.py.
"""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.ingest import ingest_directory
from pipeline.queue import FakeQueue

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "conversations"


class Recorder:
    """Records calls instead of touching a real store."""

    def __init__(self) -> None:
        self.blobs: dict[tuple[str, str], tuple[str, dict]] = {}
        self.dead_letters: list[tuple[str, str]] = []

    def store_blob(
        self, tenant_id: str, conversation_id: str, content_hash: str, raw: dict
    ) -> None:
        self.blobs[(tenant_id, conversation_id)] = (content_hash, raw)

    def record_dead_letter(self, filename: str, error: str) -> None:
        self.dead_letters.append((filename, error))


# --- against the real 27+1 fixture set -----------------------------------------


def test_ingesting_the_sample_dataset():
    queue = FakeQueue()
    rec = Recorder()
    stats = ingest_directory(
        DATA_DIR, queue=queue, store_blob=rec.store_blob, record_dead_letter=rec.record_dead_letter
    )

    assert stats.files_seen == 28  # 27 conversations + 1 duplicate file
    assert stats.parse_errors == 0  # every file is valid JSON with an identity
    assert stats.enqueued == 27  # one unique job per conversation_id
    assert stats.already_tracked == 1  # the acme__c-000002 duplicate
    assert rec.dead_letters == []
    assert len(queue._rows) == 27  # noqa: SLF001 — inspecting the fake's state is the point


def test_structurally_broken_conversation_is_still_ingested():
    # c-000029 (missing `turns`) and c-000030 (`turns` wrong type) are not
    # ingest's problem — Layer 4 decides they're `rejected` when scored.
    queue = FakeQueue()
    rec = Recorder()
    ingest_directory(
        DATA_DIR, queue=queue, store_blob=rec.store_blob, record_dead_letter=rec.record_dead_letter
    )

    assert ("acme", "c-000029") in queue._rows  # noqa: SLF001
    assert ("acme", "c-000030") in queue._rows  # noqa: SLF001
    assert ("acme", "c-000029") in rec.blobs


# --- duplicate delivery (ADR-005) ----------------------------------------------


def test_duplicate_file_does_not_create_two_queue_entries(tmp_path):
    raw = json.loads((DATA_DIR / "acme__c-000002.json").read_text())
    (tmp_path / "a.json").write_text(json.dumps(raw))
    (tmp_path / "b.json").write_text(json.dumps(raw))  # byte-identical content, different filename

    queue = FakeQueue()
    rec = Recorder()
    stats = ingest_directory(
        tmp_path, queue=queue, store_blob=rec.store_blob, record_dead_letter=rec.record_dead_letter
    )

    assert stats.files_seen == 2
    assert stats.enqueued == 1
    assert stats.already_tracked == 1
    assert len(queue._rows) == 1  # noqa: SLF001


def test_reingesting_same_directory_enqueues_nothing_new():
    queue = FakeQueue()
    rec = Recorder()
    ingest_directory(
        DATA_DIR, queue=queue, store_blob=rec.store_blob, record_dead_letter=rec.record_dead_letter
    )

    second = ingest_directory(
        DATA_DIR, queue=queue, store_blob=rec.store_blob, record_dead_letter=rec.record_dead_letter
    )

    assert second.enqueued == 0
    assert second.already_tracked == 28  # all 28 files, including the duplicate, unchanged
    assert len(queue._rows) == 27  # noqa: SLF001 — still 27 unique conversations


def test_changed_content_requeues(tmp_path):
    raw = {"tenant_id": "acme", "conversation_id": "c-x", "turns": []}
    path = tmp_path / "a.json"
    path.write_text(json.dumps(raw))

    queue = FakeQueue()
    rec = Recorder()
    ingest_directory(
        tmp_path, queue=queue, store_blob=rec.store_blob, record_dead_letter=rec.record_dead_letter
    )
    assert queue._rows[("acme", "c-x")].content_hash != ""  # noqa: SLF001

    raw["turns"] = [{"seq": 0, "role": "customer", "ts": "2026-01-01T00:00:00Z", "text": "hi"}]
    path.write_text(json.dumps(raw))
    second = ingest_directory(
        tmp_path, queue=queue, store_blob=rec.store_blob, record_dead_letter=rec.record_dead_letter
    )

    assert second.enqueued == 1  # the changed hash re-queues it
    assert second.already_tracked == 0


# --- malformed input: dead-letter, not blob/queue ------------------------------


def test_invalid_json_goes_to_dead_letter(tmp_path):
    (tmp_path / "broken.json").write_text("{not valid json")

    queue = FakeQueue()
    rec = Recorder()
    stats = ingest_directory(
        tmp_path, queue=queue, store_blob=rec.store_blob, record_dead_letter=rec.record_dead_letter
    )

    assert stats.parse_errors == 1
    assert stats.enqueued == 0
    assert rec.blobs == {}
    assert len(rec.dead_letters) == 1
    assert rec.dead_letters[0][0] == "broken.json"


def test_missing_identity_goes_to_dead_letter(tmp_path):
    (tmp_path / "no_id.json").write_text(json.dumps({"turns": []}))

    queue = FakeQueue()
    rec = Recorder()
    stats = ingest_directory(
        tmp_path, queue=queue, store_blob=rec.store_blob, record_dead_letter=rec.record_dead_letter
    )

    assert stats.parse_errors == 1
    assert rec.blobs == {}
    assert len(queue._rows) == 0  # noqa: SLF001
