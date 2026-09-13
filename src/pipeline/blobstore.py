"""Layer 5 — the durable copy of each raw conversation (ADR-003, ADR-004).

This is the target of the claim-check pointer: the queue carries a
``blob_key``, the transcript itself lives here.
"""

from __future__ import annotations

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool


def blob_key(tenant_id: str, conversation_id: str) -> str:
    return f"{tenant_id}/{conversation_id}"


def upsert_blob(
    pool: ConnectionPool, tenant_id: str, conversation_id: str, content_hash: str, raw: dict
) -> None:
    """Insert or update the blob. A no-op (not even ``ingested_at`` changes) if
    the content hash is unchanged — re-ingesting an identical file costs nothing.
    """
    with pool.connection() as conn:
        conn.execute(
            """
            INSERT INTO conversation_blobs (tenant_id, conversation_id, content_hash, raw_json)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (tenant_id, conversation_id) DO UPDATE
                SET content_hash = EXCLUDED.content_hash,
                    raw_json     = EXCLUDED.raw_json,
                    ingested_at  = now()
                WHERE conversation_blobs.content_hash IS DISTINCT FROM EXCLUDED.content_hash
            """,
            (tenant_id, conversation_id, content_hash, Jsonb(raw)),
        )


def get_blob(pool: ConnectionPool, tenant_id: str, conversation_id: str) -> dict | None:
    """Returns ``{"raw": <dict>, "content_hash": <str>}``, or ``None`` if missing
    (ADR-004: a worker seeing this is a ``blob_missing`` rejection)."""
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT raw_json, content_hash FROM conversation_blobs "
            "WHERE tenant_id = %s AND conversation_id = %s",
            (tenant_id, conversation_id),
        ).fetchone()
    if row is None:
        return None
    raw_json, content_hash = row
    return {"raw": raw_json, "content_hash": content_hash}
