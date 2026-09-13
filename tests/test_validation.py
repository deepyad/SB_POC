"""Layer 1 — parse_conversation against the sample fixtures (brief §4)."""

from pipeline.schema import (
    DroppedTurn,
    ParsedConversation,
    Rejection,
    customer_turns,
    parse_conversation,
)

# --- normal documents parse cleanly --------------------------------------------


def test_clean_conversation_parses(load_fixture):
    parsed = parse_conversation(load_fixture("acme__c-000001.json"))
    assert isinstance(parsed, ParsedConversation)
    assert parsed.tenant_id == "acme"
    assert parsed.conversation_id == "c-000001"
    assert len(parsed.turns) == 8
    assert parsed.dropped_turns == ()
    assert len(customer_turns(parsed)) == 5


def test_system_turns_are_kept_not_dropped(load_fixture):
    # c-000008 has `system` turns — a recognised role, so they stay in `turns`.
    # Excluding them from the *metrics* is Layer 3/4's job, not parsing's.
    parsed = parse_conversation(load_fixture("globex__c-000008.json"))
    assert isinstance(parsed, ParsedConversation)
    roles = {t.role for t in parsed.turns}
    assert "system" in roles and "customer" in roles
    assert parsed.dropped_turns == ()


# --- degenerate but parseable ------------------------------------------------


def test_zero_customer_turns_is_not_a_rejection(load_fixture):
    # c-000017: system + agent only. Structurally fine; "no customer turns" is a
    # metric outcome (Layer 4), not a parse failure.
    parsed = parse_conversation(load_fixture("acme__c-000017.json"))
    assert isinstance(parsed, ParsedConversation)
    assert customer_turns(parsed) == ()


def test_empty_turns_array_parses_to_zero_turns(load_fixture):
    parsed = parse_conversation(load_fixture("acme__c-000018.json"))
    assert isinstance(parsed, ParsedConversation)
    assert parsed.turns == ()
    assert parsed.dropped_turns == ()


def test_whitespace_only_text_is_kept_at_parse_time(load_fixture):
    # c-000019: "", "   ", "\t\n  ". Still strings — kept here; Layer 2 marks
    # them unscoreable.
    parsed = parse_conversation(load_fixture("acme__c-000019.json"))
    assert isinstance(parsed, ParsedConversation)
    assert len(parsed.turns) == 6
    assert parsed.dropped_turns == ()
    assert any(t.text.strip() == "" for t in parsed.turns)


def test_seq_is_ignored_for_ordering(load_fixture):
    # c-000021: array order and `seq` deliberately disagree; `seq` has a
    # duplicate. We trust array order and coerce `seq` (ADR-012).
    parsed = parse_conversation(load_fixture("acme__c-000021.json"))
    assert isinstance(parsed, ParsedConversation)
    assert [t.index for t in parsed.turns] == [0, 1, 2, 3, 4]
    assert parsed.turns[0].text.startswith("First message")
    assert parsed.turns[2].text.startswith("Photo attached")  # array pos 2, seq 1
    assert [t.seq for t in parsed.turns] == [0, 3, 1, 2, 2]  # coerced, unsorted
    assert parsed.dropped_turns == ()


# --- malformed turn objects: keep the good, record the bad ------------------


def test_mixed_bad_turns_are_dropped_individually(load_fixture):
    # c-000031: turn 0 valid; turn 1 missing ts; turn 2 null text;
    # turn 3 unknown role ("shopper"); turn 4 missing seq (coerced, kept).
    parsed = parse_conversation(load_fixture("acme__c-000031.json"))
    assert isinstance(parsed, ParsedConversation)

    kept_ix = [t.index for t in parsed.turns]
    assert kept_ix == [0, 4]
    assert parsed.turns[1].seq is None  # index 4 had no seq

    dropped = {d.index: d.reason for d in parsed.dropped_turns}
    assert dropped == {1: "missing_ts", 2: "null_text", 3: "unknown_role"}


# --- structurally unusable documents: Rejection -----------------------------


def test_missing_turns_key_is_rejected(load_fixture):
    rej = parse_conversation(load_fixture("acme__c-000029.json"))
    assert isinstance(rej, Rejection)
    assert rej.reason == "no_turns_key"


def test_turns_wrong_type_is_rejected(load_fixture):
    rej = parse_conversation(load_fixture("acme__c-000030.json"))
    assert isinstance(rej, Rejection)
    assert rej.reason == "turns_not_list"


def test_no_recognised_roles_is_rejected(load_fixture):
    # c-000032: only "bot" turns.
    rej = parse_conversation(load_fixture("globex__c-000032.json"))
    assert isinstance(rej, Rejection)
    assert rej.reason == "no_recognised_roles"


def test_missing_identity_is_rejected():
    assert parse_conversation({"tenant_id": "acme", "turns": []}).reason == (
        "missing_conversation_id"
    )
    assert parse_conversation({"conversation_id": "c-1", "turns": []}).reason == (
        "missing_tenant_id"
    )
    assert parse_conversation("not a dict").reason == "not_an_object"


# --- individual turn drop reasons not hit by the shipped fixtures -------------
# c-000031 covers missing_ts / null_text / unknown_role together; these round
# out the remaining reasons in schema._parse_turn with synthetic turns.


def _one_turn_conversation(turn):
    return {"tenant_id": "acme", "conversation_id": "c-synthetic", "turns": [turn, GOOD_TURN]}


GOOD_TURN = {"seq": 1, "role": "customer", "ts": "2026-01-01T00:00:00Z", "text": "hello"}


def test_non_object_turn_is_dropped():
    parsed = parse_conversation(_one_turn_conversation("not a turn object"))
    assert parsed.dropped_turns == (DroppedTurn(0, "non_object_turn"),)


def test_missing_text_key_is_dropped():
    turn = {"seq": 0, "role": "customer", "ts": "2026-01-01T00:00:00Z"}  # no "text" at all
    parsed = parse_conversation(_one_turn_conversation(turn))
    assert parsed.dropped_turns == (DroppedTurn(0, "missing_text"),)


def test_non_string_text_on_a_recognised_role_is_dropped():
    # Distinct from c-000031's turn, where the non-string text is on an
    # unrecognised role and unknown_role wins first.
    turn = {"seq": 0, "role": "customer", "ts": "2026-01-01T00:00:00Z", "text": 42}
    parsed = parse_conversation(_one_turn_conversation(turn))
    assert parsed.dropped_turns == (DroppedTurn(0, "non_string_text"),)


def test_boolean_seq_is_coerced_to_none_not_treated_as_an_int():
    turn = {"seq": True, "role": "customer", "ts": "2026-01-01T00:00:00Z", "text": "hi"}
    parsed = parse_conversation(_one_turn_conversation(turn))
    assert parsed.turns[0].seq is None  # bool is an int subclass; rejected explicitly


def test_unparseable_string_seq_is_coerced_to_none():
    turn = {"seq": "not-a-number", "role": "customer", "ts": "2026-01-01T00:00:00Z", "text": "hi"}
    parsed = parse_conversation(_one_turn_conversation(turn))
    assert parsed.turns[0].seq is None
