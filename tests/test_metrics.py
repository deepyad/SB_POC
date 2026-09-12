"""Layer 3 — the two metrics, edge-case matrix (ADR-009, ADR-010, brief §3).

Uses a plain stand-in for a scored turn rather than pipeline.sentiment.TurnScore,
so these tests need no model and stay fast (see metrics.ScoredLike).
"""

from dataclasses import dataclass

import pytest

from pipeline.config import Config
from pipeline.metrics import overall_sentiment, sentiment_trajectory


@dataclass
class T:
    scored: bool = True
    signed: float | None = 0.0
    confidence: float | None = 0.8


def scored(*values: float, confidence: float = 0.8) -> list[T]:
    return [T(scored=True, signed=v, confidence=confidence) for v in values]


def unscored() -> T:
    return T(scored=False, signed=None, confidence=None)


CFG = Config()  # defaults: lambda=0.5, tau=0.15, B=2.0, meaningful_min_turns=3


# --- degenerate n --------------------------------------------------------------


def test_zero_scored_turns_gives_null_for_both():
    turns = [unscored(), unscored()]
    assert overall_sentiment(turns, CFG) is None
    assert sentiment_trajectory(turns, CFG) is None


def test_empty_turn_list_gives_null_for_both():
    assert overall_sentiment([], CFG) is None
    assert sentiment_trajectory([], CFG) is None


def test_single_turn_overall_defined_trajectory_null():
    turns = scored(-0.6)
    result = overall_sentiment(turns, CFG)
    assert result is not None
    assert result["score"] == pytest.approx(-0.6)
    assert result["label"] == "negative"
    assert result["basis"] == "single_turn"
    assert result["n_customer_turns_scored"] == 1

    assert sentiment_trajectory(turns, CFG) is None


def test_two_turns_trajectory_defined_but_not_meaningful():
    turns = scored(-0.5, 0.5)
    result = sentiment_trajectory(turns, CFG)
    assert result is not None
    assert result["meaningful"] is False
    assert result["n_customer_turns_scored"] == 2
    assert result["value"] > 0  # went from negative to positive


def test_unscored_turns_are_skipped_not_counted():
    # An unscored turn in the middle must not shift position or count toward n.
    turns = [
        T(scored=True, signed=-0.5, confidence=0.9),
        unscored(),
        T(scored=True, signed=0.5, confidence=0.9),
    ]
    overall = overall_sentiment(turns, CFG)
    assert overall["n_customer_turns_scored"] == 2
    traj = sentiment_trajectory(turns, CFG)
    assert traj["n_customer_turns_scored"] == 2
    assert traj["value"] > 0


# --- null vs 0.0, the deliberate line ------------------------------------------


def test_flat_scores_give_real_zero_not_null():
    turns = scored(-0.4, -0.4, -0.4, -0.4)
    result = sentiment_trajectory(turns, CFG)
    assert result is not None  # measured
    assert result["value"] == 0.0  # real "no change", not "unmeasurable"


def test_null_and_zero_are_never_the_same_object_type():
    assert sentiment_trajectory([], CFG) is None
    assert sentiment_trajectory(scored(0.0, 0.0, 0.0), CFG)["value"] == 0.0


# --- direction and bounds ------------------------------------------------------


def test_monotonic_increase_is_positive_trajectory():
    turns = scored(-0.8, -0.3, 0.2, 0.7)
    assert sentiment_trajectory(turns, CFG)["value"] > 0


def test_monotonic_decrease_is_negative_trajectory():
    turns = scored(0.8, 0.3, -0.2, -0.7)
    assert sentiment_trajectory(turns, CFG)["value"] < 0


def test_trajectory_always_bounded():
    extreme = scored(*([1.0, -1.0] * 20))
    result = sentiment_trajectory(extreme, CFG)
    assert -1.0 < result["value"] < 1.0


def test_overall_score_always_within_signed_range():
    for values in ([-1.0], [1.0] * 5, [-1.0, 1.0, -1.0, 1.0]):
        result = overall_sentiment(scored(*values), CFG)
        assert -1.0 <= result["score"] <= 1.0


# --- label thresholds -----------------------------------------------------------


def test_label_thresholds():
    assert overall_sentiment(scored(0.0), CFG)["label"] == "neutral"
    assert overall_sentiment(scored(0.15), CFG)["label"] == "positive"
    assert overall_sentiment(scored(-0.15), CFG)["label"] == "negative"
    assert overall_sentiment(scored(0.1), CFG)["label"] == "neutral"


# --- confidence weighting (overall_sentiment only) -----------------------------


def test_low_confidence_turn_counts_less():
    # Same two-turn shape (negative then positive), only the first turn's
    # confidence differs. A weaker "negative @ 0.51" should pull the aggregate
    # less far down than a confident "negative @ 0.99" (brief §3.2).
    weak_negative_first = [
        T(scored=True, signed=-0.9, confidence=0.51),
        T(scored=True, signed=0.9, confidence=0.95),
    ]
    strong_negative_first = [
        T(scored=True, signed=-0.9, confidence=0.99),
        T(scored=True, signed=0.9, confidence=0.95),
    ]
    weak_score = overall_sentiment(weak_negative_first, CFG)["score"]
    strong_score = overall_sentiment(strong_negative_first, CFG)["score"]
    assert weak_score > strong_score


def test_zero_confidence_falls_back_to_unweighted_mean_not_crash():
    turns = [
        T(scored=True, signed=-0.5, confidence=0.0),
        T(scored=True, signed=0.5, confidence=0.0),
    ]
    result = overall_sentiment(turns, CFG)
    assert result is not None
    assert result["score"] == pytest.approx(0.0)


# --- worked examples, pinned to independently computed values -----------------


def test_worked_example_recovery_arc():
    # c-000002-like: angry -> satisfied.
    turns = [
        T(scored=True, signed=-0.80, confidence=0.90),
        T(scored=True, signed=-0.60, confidence=0.80),
        T(scored=True, signed=0.30, confidence=0.70),
        T(scored=True, signed=0.90, confidence=0.95),
    ]
    overall = overall_sentiment(turns, CFG)
    assert overall["score"] == pytest.approx(0.34505, abs=1e-4)
    assert overall["label"] == "positive"

    traj = sentiment_trajectory(turns, CFG)
    assert traj["slope"] == pytest.approx(1.8, abs=1e-4)
    assert traj["value"] == pytest.approx(0.71630, abs=1e-4)
    assert traj["meaningful"] is True


def test_worked_example_escalation_arc():
    # c-000001-like: mildly annoyed -> furious.
    turns = [
        T(scored=True, signed=-0.2, confidence=0.70),
        T(scored=True, signed=-0.5, confidence=0.85),
        T(scored=True, signed=-0.9, confidence=0.97),
    ]
    overall = overall_sentiment(turns, CFG)
    assert overall["score"] == pytest.approx(-0.67828, abs=1e-4)
    assert overall["label"] == "negative"

    traj = sentiment_trajectory(turns, CFG)
    assert traj["slope"] == pytest.approx(-0.7, abs=1e-4)
    assert traj["value"] == pytest.approx(-0.33638, abs=1e-4)


# --- determinism -----------------------------------------------------------------


def test_same_input_gives_byte_identical_output():
    turns = scored(-0.3, 0.1, 0.6, -0.2, 0.4)
    assert overall_sentiment(turns, CFG) == overall_sentiment(turns, CFG)
    assert sentiment_trajectory(turns, CFG) == sentiment_trajectory(turns, CFG)


def test_params_are_configurable_not_hardcoded():
    turns = scored(-0.8, -0.6, 0.3, 0.9)
    default = overall_sentiment(turns, CFG)
    aggressive_recency = overall_sentiment(turns, Config(recency_lambda=2.0))
    assert default["score"] != aggressive_recency["score"]
