"""Layer 4 — score_conversation wires validation + scoring + metrics into one
row. Fast tests use FakeScorer (no model). A handful of slow tests re-run the
same fixtures through the real Scorer for genuine end-to-end proof.
"""

from datetime import UTC, datetime, timedelta

import pytest

from pipeline.config import Config
from pipeline.hashing import content_hash
from pipeline.result import score_conversation
from pipeline.sentiment import TurnScore, _has_scoreable_signal

NOW = datetime(2026, 9, 12, 12, 0, 0, tzinfo=UTC)
CFG = Config()


class FakeScorer:
    """Deterministic, keyword-based stand-in — no model needed.

    Blank/whitespace text -> unscored (mirrors the real empty-text rule).
    Otherwise: a few marker words pick the sign; anything else is neutral.
    """

    NEGATIVE_WORDS = ("bad", "broken", "terrible", "furious", "useless", "unacceptable", "cancel")
    POSITIVE_WORDS = ("good", "great", "thank", "relief", "helpful", "appreciate")

    def score_texts(self, texts: list[str]) -> list[TurnScore]:
        out = []
        for t in texts:
            if not _has_scoreable_signal(
                t
            ):  # same empty/whitespace/punctuation rule as the real Scorer
                out.append(
                    TurnScore(
                        scored=False, label=None, signed=None, confidence=None, reason="empty_text"
                    )
                )
                continue
            low = t.lower()
            if any(w in low for w in self.NEGATIVE_WORDS):
                out.append(TurnScore(scored=True, label="negative", signed=-0.8, confidence=0.9))
            elif any(w in low for w in self.POSITIVE_WORDS):
                out.append(TurnScore(scored=True, label="positive", signed=0.8, confidence=0.9))
            else:
                out.append(TurnScore(scored=True, label="neutral", signed=0.0, confidence=0.6))
        return out


FAKE = FakeScorer()


# --- clean and malformed documents, status classification ---------------------


def test_clean_conversation_is_scored(load_fixture):
    row = score_conversation(load_fixture("acme__c-000001.json"), CFG, FAKE, NOW)
    assert row["status"] == "scored"
    assert row["tenant_id"] == "acme"
    assert row["conversation_id"] == "c-000001"
    assert row["overall_sentiment"]["label"] == "negative"  # escalation, "useless"/"cancel"
    assert row["sentiment_trajectory"] is not None
    assert row["dropped_turns"] == []
    assert row["error"] is None


def test_no_customer_turns_is_rejected(load_fixture):
    row = score_conversation(load_fixture("acme__c-000017.json"), CFG, FAKE, NOW)
    assert row["status"] == "rejected"
    assert row["error"] == {"reason": "no_customer_turns", "detail": "0 customer turn(s), 0 scored"}
    assert row["overall_sentiment"] is None
    assert row["sentiment_trajectory"] is None


def test_empty_turns_array_is_rejected(load_fixture):
    row = score_conversation(load_fixture("acme__c-000018.json"), CFG, FAKE, NOW)
    assert row["status"] == "rejected"
    assert row["error"]["reason"] == "no_customer_turns"


def test_missing_turns_key_is_rejected(load_fixture):
    row = score_conversation(load_fixture("acme__c-000029.json"), CFG, FAKE, NOW)
    assert row["status"] == "rejected"
    assert row["error"]["reason"] == "no_turns_key"
    assert row["per_turn"] == []
    assert row["dropped_turns"] == []


def test_turns_wrong_type_is_rejected(load_fixture):
    row = score_conversation(load_fixture("acme__c-000030.json"), CFG, FAKE, NOW)
    assert row["error"]["reason"] == "turns_not_list"


def test_no_recognised_roles_is_rejected(load_fixture):
    row = score_conversation(load_fixture("globex__c-000032.json"), CFG, FAKE, NOW)
    assert row["error"]["reason"] == "no_recognised_roles"


def test_mixed_bad_turns_is_partial(load_fixture):
    row = score_conversation(load_fixture("acme__c-000031.json"), CFG, FAKE, NOW)
    assert row["status"] == "partial"
    assert row["error"] is None
    assert row["dropped_turns"] == [
        {"index": 1, "reason": "missing_ts"},
        {"index": 2, "reason": "null_text"},
        {"index": 3, "reason": "unknown_role"},
    ]
    assert [t["role"] for t in row["per_turn"]] == ["customer", "customer"]
    assert row["overall_sentiment"] is not None  # 2 scoreable customer turns remain


def test_all_customer_turns_blank_is_no_customer_signal():
    raw = {
        "conversation_id": "c-synthetic",
        "tenant_id": "acme",
        "channel": "chat",
        "started_at": "2026-01-01T00:00:00Z",
        "turns": [
            {"seq": 0, "role": "customer", "ts": "2026-01-01T00:00:00Z", "text": "   "},
            {"seq": 1, "role": "customer", "ts": "2026-01-01T00:00:05Z", "text": "..."},
        ],
    }
    row = score_conversation(raw, CFG, FAKE, NOW)
    assert row["status"] == "rejected"
    assert row["error"]["reason"] == "no_customer_signal"  # distinct from no_customer_turns


# --- per_turn / dropped_turns shape --------------------------------------------


def test_per_turn_carries_full_scoring_detail(load_fixture):
    row = score_conversation(load_fixture("acme__c-000009.json"), CFG, FAKE, NOW)
    first = row["per_turn"][0]
    assert set(first) == {
        "index",
        "seq",
        "role",
        "scored",
        "label",
        "score",
        "confidence",
        "reason",
    }
    assert first["role"] == "customer"
    assert first["scored"] is True


def test_system_turns_never_appear_in_per_turn(load_fixture):
    row = score_conversation(load_fixture("globex__c-000008.json"), CFG, FAKE, NOW)
    assert all(t["role"] != "system" for t in row["per_turn"])


def test_agent_turns_excluded_by_default(load_fixture):
    row = score_conversation(load_fixture("acme__c-000001.json"), CFG, FAKE, NOW)
    assert all(t["role"] != "agent" for t in row["per_turn"])


def test_score_agent_turns_flag_adds_them_without_changing_metrics(load_fixture):
    raw = load_fixture("acme__c-000001.json")
    default_row = score_conversation(raw, CFG, FAKE, NOW)
    with_agent = score_conversation(raw, Config(score_agent_turns=True), FAKE, NOW)

    assert any(t["role"] == "agent" for t in with_agent["per_turn"])
    assert not any(t["role"] == "agent" for t in default_row["per_turn"])
    # Agent turns never feed the metrics — same customer-only result either way.
    assert with_agent["overall_sentiment"] == default_row["overall_sentiment"]
    assert with_agent["sentiment_trajectory"] == default_row["sentiment_trajectory"]


# --- provenance, params, hashing -----------------------------------------------


def test_provenance_and_params(load_fixture):
    row = score_conversation(load_fixture("acme__c-000001.json"), CFG, FAKE, NOW)
    assert row["provenance"]["model_name"] == CFG.model_name
    assert row["provenance"]["model_revision"] == CFG.model_revision
    assert row["provenance"]["scored_at"] == "2026-09-12T12:00:00Z"
    assert row["params"] == CFG.metric_params()
    assert row["schema_version"] == CFG.schema_version


def test_naive_datetime_is_treated_as_utc(load_fixture):
    naive_now = datetime(2026, 1, 1, 12, 0, 0)  # no tzinfo at all
    row = score_conversation(load_fixture("acme__c-000001.json"), CFG, FAKE, naive_now)
    assert row["provenance"]["scored_at"] == "2026-01-01T12:00:00Z"


def test_content_hash_matches_layer1_and_is_stable(load_fixture):
    raw = load_fixture("acme__c-000001.json")
    row = score_conversation(raw, CFG, FAKE, NOW)
    assert row["content_hash"] == content_hash(raw)


def test_duplicate_fixture_gets_same_hash(load_fixture):
    a = score_conversation(load_fixture("acme__c-000002.json"), CFG, FAKE, NOW)
    b = score_conversation(load_fixture("acme__c-000002.duplicate.json"), CFG, FAKE, NOW)
    assert a["content_hash"] == b["content_hash"]


# --- reproducibility (brief §3.3) ----------------------------------------------


def test_same_now_gives_byte_identical_row(load_fixture):
    raw = load_fixture("acme__c-000005.json")
    a = score_conversation(raw, CFG, FAKE, NOW)
    b = score_conversation(raw, CFG, FAKE, NOW)
    assert a == b


def test_different_now_differs_only_in_scored_at(load_fixture):
    raw = load_fixture("acme__c-000005.json")
    a = score_conversation(raw, CFG, FAKE, NOW)
    b = score_conversation(raw, CFG, FAKE, NOW + timedelta(hours=1))
    assert a["provenance"]["scored_at"] != b["provenance"]["scored_at"]
    a_without_ts = {**a, "provenance": {**a["provenance"], "scored_at": None}}
    b_without_ts = {**b, "provenance": {**b["provenance"], "scored_at": None}}
    assert a_without_ts == b_without_ts


# --- a handful of slow, real-model integration checks --------------------------


@pytest.mark.slow
class TestWithRealScorer:
    @pytest.fixture(scope="class")
    def scorer(self):
        from pipeline.sentiment import Scorer

        return Scorer(Config())

    def test_end_to_end_escalation(self, scorer, load_fixture):
        row = score_conversation(load_fixture("acme__c-000001.json"), CFG, scorer, NOW)
        assert row["status"] == "scored"
        assert row["overall_sentiment"]["label"] == "negative"
        assert row["sentiment_trajectory"]["value"] < 0

    def test_end_to_end_no_customer_turns(self, scorer, load_fixture):
        row = score_conversation(load_fixture("acme__c-000017.json"), CFG, scorer, NOW)
        assert row["status"] == "rejected"

    def test_end_to_end_partial(self, scorer, load_fixture):
        row = score_conversation(load_fixture("acme__c-000031.json"), CFG, scorer, NOW)
        assert row["status"] == "partial"
        assert len(row["dropped_turns"]) == 3

    def test_end_to_end_reproducible(self, scorer, load_fixture):
        raw = load_fixture("globex__c-000010.json")
        a = score_conversation(raw, CFG, scorer, NOW)
        b = score_conversation(raw, CFG, scorer, NOW)
        assert a == b
