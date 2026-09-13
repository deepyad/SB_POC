"""Layer 5 — results storage and the one-transaction write that closes a job
(ADR-006): the ``results`` upsert and the matching ``jobs`` row's status flip
commit together, or not at all. No cross-system ack gap to reason about.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool


def _parse_iso_z(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def close_job_with_result(pool: ConnectionPool, row: dict[str, Any], job_status: str) -> None:
    """Upsert ``row`` (the dict from ``pipeline.result.score_conversation``)
    into ``results``, and set the matching ``jobs`` row's status — one
    transaction (ADR-006). ``job_status`` is ``'done'`` for scored/partial/
    rejected-by-content, or ``'dead'`` for poison / a missing blob (ADR-012).
    """
    if job_status not in ("done", "dead"):
        raise ValueError(f"job_status must be 'done' or 'dead', got {job_status!r}")

    provenance = row["provenance"]
    params: dict[str, Any] = {
        "tenant_id": row["tenant_id"],
        "conversation_id": row["conversation_id"],
        "content_hash": row["content_hash"],
        "status": row["status"],
        "overall_sentiment": Jsonb(row["overall_sentiment"]),
        "sentiment_trajectory": Jsonb(row["sentiment_trajectory"]),
        "per_turn": Jsonb(row["per_turn"]),
        "dropped_turns": Jsonb(row["dropped_turns"]),
        "error": Jsonb(row["error"]),
        "schema_version": row["schema_version"],
        "model_name": provenance["model_name"],
        "model_revision": provenance["model_revision"],
        "params": Jsonb(row["params"]),
        "scored_at": _parse_iso_z(provenance["scored_at"]),
        "job_status": job_status,
    }

    with pool.connection() as conn, conn.transaction():
        conn.execute(
            """
            INSERT INTO results (
                tenant_id, conversation_id, content_hash, status,
                overall_sentiment, sentiment_trajectory, per_turn, dropped_turns, error,
                schema_version, model_name, model_revision, params, scored_at
            ) VALUES (
                %(tenant_id)s, %(conversation_id)s, %(content_hash)s, %(status)s,
                %(overall_sentiment)s, %(sentiment_trajectory)s, %(per_turn)s,
                %(dropped_turns)s, %(error)s,
                %(schema_version)s, %(model_name)s, %(model_revision)s, %(params)s, %(scored_at)s
            )
            ON CONFLICT (tenant_id, conversation_id) DO UPDATE SET
                content_hash         = EXCLUDED.content_hash,
                status               = EXCLUDED.status,
                overall_sentiment    = EXCLUDED.overall_sentiment,
                sentiment_trajectory = EXCLUDED.sentiment_trajectory,
                per_turn             = EXCLUDED.per_turn,
                dropped_turns        = EXCLUDED.dropped_turns,
                error                = EXCLUDED.error,
                schema_version       = EXCLUDED.schema_version,
                model_name           = EXCLUDED.model_name,
                model_revision       = EXCLUDED.model_revision,
                params               = EXCLUDED.params,
                scored_at            = EXCLUDED.scored_at
            """,
            params,
        )
        conn.execute(
            "UPDATE jobs SET status = %(job_status)s "
            "WHERE tenant_id = %(tenant_id)s AND conversation_id = %(conversation_id)s",
            params,
        )


def get_result(pool: ConnectionPool, tenant_id: str, conversation_id: str) -> dict[str, Any] | None:
    """Same nested shape as ``score_conversation``'s return value, so the
    worker's de-dup check (ADR-005) can compare like for like."""
    with pool.connection() as conn:
        row = conn.execute(
            """
            SELECT tenant_id, conversation_id, content_hash, status,
                   overall_sentiment, sentiment_trajectory, per_turn, dropped_turns, error,
                   schema_version, model_name, model_revision, params, scored_at
            FROM results WHERE tenant_id = %s AND conversation_id = %s
            """,
            (tenant_id, conversation_id),
        ).fetchone()
    if row is None:
        return None
    (
        tenant_id_,
        conversation_id_,
        content_hash,
        status,
        overall_sentiment,
        sentiment_trajectory,
        per_turn,
        dropped_turns,
        error,
        schema_version,
        model_name,
        model_revision,
        params,
        scored_at,
    ) = row
    return {
        "tenant_id": tenant_id_,
        "conversation_id": conversation_id_,
        "content_hash": content_hash,
        "schema_version": schema_version,
        "provenance": {
            "model_name": model_name,
            "model_revision": model_revision,
            "scored_at": scored_at.astimezone(scored_at.tzinfo)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z"),
        },
        "params": params,
        "status": status,
        "overall_sentiment": overall_sentiment,
        "sentiment_trajectory": sentiment_trajectory,
        "per_turn": per_turn,
        "dropped_turns": dropped_turns,
        "error": error,
    }
