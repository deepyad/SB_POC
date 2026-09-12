"""Layer 3 — the two conversation-level metrics (ADR-009, ADR-010).

Pure functions: given the customer turns of one conversation, in order, return
either a metric dict or ``None``. No I/O, no model, no database — this is the
part of the pipeline the brief cares about most, and it is testable in complete
isolation.

Both functions take any sequence of :class:`ScoredLike` objects — anything with
``scored``, ``signed`` and ``confidence`` attributes (``pipeline.sentiment.
TurnScore`` satisfies this structurally; tests can use a plain stand-in without
importing the model wrapper at all). Turns with ``scored=False`` (empty /
whitespace / punctuation-only text, ADR-008) carry no signal and are skipped —
they still occupy a slot in the *input* list, but do not count toward ``n`` and
do not shift the positions used by :func:`sentiment_trajectory`.

``None`` means "not measurable" (no scored customer turns, or too few for a
trajectory). It is never conflated with a real ``0.0`` (measured, no change) —
that distinction is the point of this module (brief §3, "what we're looking
at" #1).
"""

from __future__ import annotations

import math
from typing import Protocol

from pipeline.config import Config


class ScoredLike(Protocol):
    scored: bool
    signed: float | None
    confidence: float | None


def _scored_pairs(turns: list) -> list[tuple[float, float]]:
    """(signed, confidence) for turns that actually carried a signal, in order."""
    return [(t.signed, t.confidence) for t in turns if t.scored]


def overall_sentiment(turns: list, cfg: Config) -> dict | None:
    """One label and score for the whole conversation (ADR-009).

    ``S = sum(w_i * signed_i) / sum(w_i)``, ``w_i = exp(-lambda*(n-1-i)) * conf_i``
    — later turns and more-confident turns count for more. For ``n == 1`` this
    reduces to the single turn's own score; the weighting is not a special case.

    Returns ``None`` when there is no customer turn with a signal at all
    (``n == 0``) — the conversation has nothing to report, not a score of zero.
    """
    scored = _scored_pairs(turns)
    n = len(scored)
    if n == 0:
        return None

    weights = [
        math.exp(-cfg.recency_lambda * (n - 1 - i)) * conf for i, (_, conf) in enumerate(scored)
    ]
    weight_total = sum(weights)
    if weight_total == 0:
        # Every scored turn had exactly zero model confidence — vanishingly
        # unlikely, but a real result must not divide by it. Fall back to an
        # unweighted mean rather than let ZeroDivisionError decide (brief §3.1).
        score = sum(signed for signed, _ in scored) / n
    else:
        score = (
            sum(w * signed for w, (signed, _) in zip(weights, scored, strict=True)) / weight_total
        )

    if score <= -cfg.label_threshold:
        label = "negative"
    elif score >= cfg.label_threshold:
        label = "positive"
    else:
        label = "neutral"

    return {
        "label": label,
        "score": round(score, 4),
        "n_customer_turns_scored": n,
        "basis": "single_turn" if n == 1 else "recency_confidence_weighted_mean",
    }


def sentiment_trajectory(turns: list, cfg: Config) -> dict | None:
    """Did the conversation get better or worse (ADR-010)?

    ``value = tanh(beta / B)`` where ``beta`` is the least-squares slope of the
    signed scores against normalised position ``x_i = i/(n-1) in [0, 1]`` —
    position among the *scored* turns, not the raw turn index. Normalising to
    ``[0, 1]`` is what makes conversations of very different lengths comparable;
    ``tanh`` keeps the result bounded and signed.

    Confidence is deliberately **not** used here (unlike ``overall_sentiment``):
    the slope is already a noisy estimator, and letting confidence reweight
    points would risk distorting the one thing this metric must get right —
    direction (ADR-010, brief §3.2 "make it deliberately and say so").

    Returns ``None`` when fewer than 2 customer turns carried a signal — a
    single point has no trajectory. With exactly 2, a value is still returned
    but flagged ``meaningful: False`` (a line through two points is not
    evidence). All-equal scores give ``value == 0.0`` — a real, measured "no
    change" — never ``None``.
    """
    scored = _scored_pairs(turns)
    n = len(scored)
    if n < 2:
        return None

    xs = [i / (n - 1) for i in range(n)]
    ys = [signed for signed, _ in scored]
    x_mean = sum(xs) / n
    y_mean = sum(ys) / n
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys, strict=True))
    denominator = sum((x - x_mean) ** 2 for x in xs)
    # denominator == 0 only if n < 2 (already excluded above): with n >= 2, xs
    # spans 0..1 so the x values are never all identical.
    beta = numerator / denominator
    value = math.tanh(beta / cfg.trajectory_divisor)

    return {
        "value": round(value, 4),
        "slope": round(beta, 4),
        "n_customer_turns_scored": n,
        "meaningful": n >= cfg.meaningful_min_turns,
    }
