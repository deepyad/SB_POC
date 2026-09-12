"""Layer 4 — result assembly: one function from a raw conversation dict to a
complete ``results`` row (ADR-012, ADR-013).

Wires together everything built so far — Layer 1 validation, Layer 2 scoring,
Layer 3 metrics — into the actual graded output. No database is involved yet
(that starts at Layer 5); this is the first point the whole scoring pipeline
runs end to end, reproducibly, from a plain dict to a plain dict.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Protocol

from pipeline.config import Config
from pipeline.hashing import content_hash
from pipeline.metrics import overall_sentiment, sentiment_trajectory
from pipeline.schema import Rejection, customer_turns, parse_conversation
from pipeline.sentiment import TurnScore


class ScorerLike(Protocol):
    """Anything with this method can be passed in — a real ``sentiment.Scorer``
    in production, a fast deterministic fake in tests (see ``metrics.ScoredLike``
    for the same pattern one layer down)."""

    def score_texts(self, texts: list[str]) -> list[TurnScore]: ...


def _iso_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def score_conversation(raw: object, cfg: Config, scorer: ScorerLike, now: datetime) -> dict:
    """Validate, score, and assemble one ``results`` row for one conversation.

    Deterministic given the same ``raw``, ``cfg`` and ``scorer`` output — the
    only field that can differ between two calls is ``provenance.scored_at``,
    which is exactly ``now`` and nothing else (brief §3.3, byte-identical
    output).
    """
    tenant_id = raw.get("tenant_id") if isinstance(raw, dict) else None
    conversation_id = raw.get("conversation_id") if isinstance(raw, dict) else None
    doc_hash = content_hash(raw) if isinstance(raw, dict) else None

    base = {
        "tenant_id": tenant_id,
        "conversation_id": conversation_id,
        "content_hash": doc_hash,
        "schema_version": cfg.schema_version,
        "provenance": {
            "model_name": cfg.model_name,
            "model_revision": cfg.model_revision,
            "scored_at": _iso_z(now),
        },
        "params": cfg.metric_params(),
    }

    parsed = parse_conversation(raw)
    if isinstance(parsed, Rejection):
        return {
            **base,
            "status": "rejected",
            "overall_sentiment": None,
            "sentiment_trajectory": None,
            "per_turn": [],
            "dropped_turns": [],
            "error": {"reason": parsed.reason, "detail": parsed.detail},
        }

    customer = customer_turns(parsed)
    # system turns are never scored (ADR-011). agent turns only if opted in —
    # stored in per_turn for context, never fed into the two metrics.
    agent = [t for t in parsed.turns if t.role == "agent"] if cfg.score_agent_turns else []
    to_score = list(customer) + agent

    turn_scores = scorer.score_texts([t.text for t in to_score]) if to_score else []
    score_by_index = dict(zip((t.index for t in to_score), turn_scores, strict=True))

    per_turn = [
        {
            "index": turn.index,
            "seq": turn.seq,
            "role": turn.role,
            "scored": ts.scored,
            "label": ts.label,
            "score": ts.signed,
            "confidence": ts.confidence,
            "reason": ts.reason,
        }
        for turn in parsed.turns
        if (ts := score_by_index.get(turn.index)) is not None
    ]

    customer_scores = [score_by_index[t.index] for t in customer]
    overall = overall_sentiment(customer_scores, cfg)
    trajectory = sentiment_trajectory(customer_scores, cfg)
    dropped_turns = [asdict(d) for d in parsed.dropped_turns]

    if overall is None:
        # 0 customer turns at all (c-000017/18), vs customer turns present but
        # every one of them was empty/whitespace/punctuation-only (ADR-011: n
        # can be 0 even when the conversation "has" customer turns).
        reason = "no_customer_turns" if len(customer) == 0 else "no_customer_signal"
        status = "rejected"
        error = {"reason": reason, "detail": f"{len(customer)} customer turn(s), 0 scored"}
    elif dropped_turns:
        status = "partial"
        error = None
    else:
        status = "scored"
        error = None

    return {
        **base,
        "status": status,
        "overall_sentiment": overall,
        "sentiment_trajectory": trajectory,
        "per_turn": per_turn,
        "dropped_turns": dropped_turns,
        "error": error,
    }
