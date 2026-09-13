"""Layer 2 — the sentiment model wrapper.

Needs the model, which needs network on first run (see warm_model.py) — these
are marked `slow` and excluded from the default `make test` (see `make test-all`
/ `make test-slow`).
"""

import pytest

from pipeline.config import Config
from pipeline.sentiment import Scorer

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def scorer():
    return Scorer(Config())


def _approx_equal(a, b, tol=1e-4):
    assert a.scored == b.scored
    assert a.label == b.label
    if a.scored:
        assert a.signed == pytest.approx(b.signed, abs=tol)
        assert a.confidence == pytest.approx(b.confidence, abs=tol)


def test_determinism(scorer):
    text = "This is genuinely useless, nobody can help me."
    [a] = scorer.score_texts([text])
    [b] = scorer.score_texts([text])
    _approx_equal(a, b)


def test_clear_negative_sign(scorer):
    [score] = scorer.score_texts(
        ["This is genuinely useless. I am furious and cancelling the order."]
    )
    assert score.scored
    assert score.label == "negative"
    assert score.signed < -0.2
    assert 0.0 <= score.confidence <= 1.0


def test_clear_positive_sign(scorer):
    [score] = scorer.score_texts(["Thank you so much, that was incredibly helpful and quick!"])
    assert score.scored
    assert score.label == "positive"
    assert score.signed > 0.2


def test_flat_information_request_is_not_strongly_signed(scorer):
    # c-000003-like: pure information request, no affect either way.
    [score] = scorer.score_texts(["Could you confirm the dimensions of the medium size?"])
    assert score.scored
    assert abs(score.signed) < 0.5


def test_empty_and_whitespace_and_punctuation_not_scored(scorer):
    results = scorer.score_texts(["", "   ", "\t\n  ", "...", "?!?!"])
    assert all(r.scored is False for r in results)
    assert all(r.reason == "empty_text" for r in results)
    assert all(r.signed is None and r.confidence is None and r.label is None for r in results)


def test_batch_size_override_does_not_change_the_answer(scorer):
    texts = ["Great job, thank you!", "This is terrible.", "Could you confirm the price?"]
    default_batch = scorer.score_texts(texts)
    one_at_a_time = scorer.score_texts(texts, batch_size=1)
    for a, b in zip(default_batch, one_at_a_time, strict=True):
        assert a.label == b.label
        assert a.signed == pytest.approx(b.signed, abs=1e-4)


def test_emoji_only_is_scored(scorer):
    for text in ("😡😡😡", "👍"):
        [score] = scorer.score_texts([text])
        assert score.scored is True, text


def test_long_text_does_not_raise(scorer):
    # Well past the 512-token limit; must truncate, not crash (fixture c-000027).
    long_text = "This is a very long complaint about a missing refund. " * 200
    [score] = scorer.score_texts([long_text])
    assert score.scored is True


def test_batch_matches_single_scoring(scorer):
    texts = ["Great job, thank you!", "This is terrible.", "", "😡😡😡"]
    batch = scorer.score_texts(texts)
    for text, b in zip(texts, batch, strict=True):
        [single] = scorer.score_texts([text])
        _approx_equal(b, single)


def test_mixed_language_does_not_raise(scorer, load_fixture):
    # c-000024/25/26: the model is English-only and will get these wrong, which
    # is a documented limitation, not a crash (brief §5.2).
    for filename in (
        "globex__c-000024.json",
        "globex__c-000025.json",
        "globex__c-000026.json",
    ):
        doc = load_fixture(filename)
        texts = [t["text"] for t in doc["turns"]]
        results = scorer.score_texts(texts)
        assert len(results) == len(texts)
