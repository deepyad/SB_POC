"""Single source of truth for every tunable in the pipeline (ADR-014).

Nothing in the pipeline reads a magic number from its own module scope. Functions
take a :class:`Config`; the worker copies the relevant subset into every
``results`` row's ``params`` block so a stored number stays reproducible even
after the defaults change (ADR-013, brief §3.3).

Override any field from the environment with an ``SB_`` prefix, e.g.
``SB_RECENCY_LAMBDA=0.7`` or ``SB_DATABASE_URL=postgresql://...``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import Any

# Bump when the shape of a `results` row changes (ADR-013).
SCHEMA_VERSION = "1.0.0"

_ENV_PREFIX = "SB_"


@dataclass(frozen=True)
class Config:
    """Immutable run configuration. Construct once, pass it down.

    ``frozen`` gives reproducibility a hand: a Config that reached a ``results``
    row cannot have been mutated afterwards.
    """

    # --- model (ADR-007) -------------------------------------------------------
    model_name: str = "cardiffnlp/twitter-roberta-base-sentiment-latest"
    # Pinned commit (Layer 2) — id2label = {0: negative, 1: neutral, 2: positive}.
    # "the model" cannot silently change under us (ADR-007, ADR-013 provenance).
    model_revision: str = "3216a57f2a0d9c45a2e6c20157c20c49fb4bf9c7"
    max_tokens: int = 512
    batch_size: int = 32  # tuned from scripts/bench.py in Layer 9

    # --- per-turn scoring (ADR-008) ------------------------------------------
    # Empty / whitespace-only / punctuation-or-ellipsis-only turns carry no
    # sentiment signal: they are not scored and are excluded from the metrics
    # (this is the deliberate null-vs-0.0 choice). Emoji-only turns ARE scored.
    empty_text_policy: str = "excluded"

    # --- overall_sentiment (ADR-009) --------------------------------------
    # Recency- and confidence-weighted mean: w_i = exp(-lambda * (n-1-i)) * conf_i
    recency_lambda: float = 0.5
    # |S| >= label_threshold  ->  positive / negative;  else neutral.
    label_threshold: float = 0.15

    # --- sentiment_trajectory (ADR-010) ---------------------------------
    # value = tanh(beta / trajectory_divisor), beta = OLS slope over normalised
    # position. A full -1 -> +1 sweep across the whole conversation gives
    # beta = 2, so divisor 2.0 maps that to value ~= 0.76.
    trajectory_divisor: float = 2.0
    # Fewer than this many customer turns -> trajectory carries meaningful=false
    # (a line through 2 points is not evidence). Value is still emitted.
    meaningful_min_turns: int = 3

    # --- metric scope (ADR-011) --------------------------------------------
    roles_in_metrics: tuple[str, ...] = ("customer",)
    # --score-agent flag: score & store agent turns in per_turn (never in the
    # two metrics). Off by default so the throughput number reflects real work.
    score_agent_turns: bool = False

    # --- queue / worker (ADR-002, ADR-006, ADR-012) ----------------------
    lease_seconds: int = 60  # a claimed job idle longer than this is reclaimed
    max_delivery: int = 3  # delivery_count past this -> rejected + dead (poison)
    claim_batch: int = 16  # rows claimed per SKIP LOCKED round
    poll_idle_seconds: float = 1.0  # sleep when a claim returns nothing

    # --- storage ----------------------------------------------------------
    database_url: str = "postgresql://sb:sb@localhost:5432/sb"

    # --- provenance -----------------------------------------------------------
    schema_version: str = SCHEMA_VERSION

    # ------------------------------------------------------------------------
    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Config:
        """Build a Config from defaults overlaid with ``SB_``-prefixed env vars.

        Unknown ``SB_`` vars are ignored. Values are coerced to each field's
        declared type; ``roles_in_metrics`` accepts a comma-separated list.
        """
        source = os.environ if env is None else env
        overrides: dict[str, Any] = {}
        for f in fields(cls):
            raw = source.get(_ENV_PREFIX + f.name.upper())
            if raw is None:
                continue
            overrides[f.name] = _coerce(f.name, f.type, raw)
        return cls(**overrides)

    def metric_params(self) -> dict[str, Any]:
        """The subset echoed into every ``results`` row's ``params`` (ADR-013)."""
        return {
            "signed_score": "p_pos - p_neg",
            "overall": {
                "method": "recency_confidence_weighted_mean",
                "lambda": self.recency_lambda,
                "label_threshold": self.label_threshold,
            },
            "trajectory": {
                "method": "tanh_ols_slope_norm_position",
                "B": self.trajectory_divisor,
                "meaningful_min_turns": self.meaningful_min_turns,
            },
            "empty_text_policy": self.empty_text_policy,
            "roles_in_metrics": list(self.roles_in_metrics),
        }


def _coerce(name: str, type_: Any, raw: str) -> Any:
    """Coerce an env string to the field's type. `type_` may be a string
    annotation (from ``from __future__ import annotations``)."""
    text = str(type_)
    if name == "roles_in_metrics":
        return tuple(part.strip() for part in raw.split(",") if part.strip())
    if "bool" in text:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    if "int" in text:
        return int(raw)
    if "float" in text:
        return float(raw)
    return raw
