"""Layer 6 — get conversations from a directory into the system, de-duplicated
(ADR-002, ADR-004, ADR-005).

Ingest never validates a conversation's *content* — a structurally broken
document (missing `turns`, wrong types) still gets a blob and a queue entry;
Layer 4's `score_conversation` is what decides it's `rejected`. Ingest only
rejects what it cannot even route: a file that isn't valid JSON, or one
missing the identity (`tenant_id`/`conversation_id`) needed to key it.

`store_blob` and `record_dead_letter` are injected callables rather than
objects, so tests can pass simple in-memory recorders with no database at all;
production wires them to `blobstore.upsert_blob` / an `ingest_dead_letters`
insert.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pipeline.blobstore import blob_key as make_blob_key
from pipeline.hashing import content_hash
from pipeline.queue import Queue

StoreBlob = Callable[[str, str, str, dict], None]
RecordDeadLetter = Callable[[str, str], None]


@dataclass
class IngestStats:
    files_seen: int = 0
    parse_errors: int = 0
    enqueued: int = 0
    already_tracked: int = 0


def ingest_directory(
    directory: Path,
    *,
    queue: Queue,
    store_blob: StoreBlob,
    record_dead_letter: RecordDeadLetter | None = None,
) -> IngestStats:
    stats = IngestStats()

    for path in sorted(directory.glob("*.json")):
        stats.files_seen += 1

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            stats.parse_errors += 1
            if record_dead_letter is not None:
                record_dead_letter(path.name, f"{type(exc).__name__}: {exc}")
            continue

        tenant_id = raw.get("tenant_id") if isinstance(raw, dict) else None
        conversation_id = raw.get("conversation_id") if isinstance(raw, dict) else None
        if (
            not isinstance(tenant_id, str)
            or not tenant_id
            or not isinstance(conversation_id, str)
            or not conversation_id
        ):
            stats.parse_errors += 1
            if record_dead_letter is not None:
                record_dead_letter(path.name, "missing or invalid tenant_id/conversation_id")
            continue

        doc_hash = content_hash(raw)
        store_blob(tenant_id, conversation_id, doc_hash, raw)

        newly = queue.enqueue(
            tenant_id, conversation_id, make_blob_key(tenant_id, conversation_id), doc_hash
        )
        if newly:
            stats.enqueued += 1
        else:
            stats.already_tracked += 1

    return stats
