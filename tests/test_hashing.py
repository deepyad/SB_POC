"""Layer 1 — content_hash is canonical and stable (ADR-005)."""

from pipeline.hashing import content_hash


def test_key_order_does_not_matter():
    assert content_hash({"a": 1, "b": 2, "c": [1, 2]}) == content_hash(
        {"c": [1, 2], "b": 2, "a": 1}
    )


def test_format_is_prefixed_hex():
    h = content_hash({"x": 1})
    assert h.startswith("sha256:")
    hexpart = h.split(":", 1)[1]
    assert len(hexpart) == 64
    int(hexpart, 16)  # raises if not hex


def test_duplicate_fixture_hashes_equal(load_fixture):
    a = content_hash(load_fixture("acme__c-000002.json"))
    b = content_hash(load_fixture("acme__c-000002.duplicate.json"))
    assert a == b


def test_different_conversations_differ(load_fixture):
    assert content_hash(load_fixture("acme__c-000001.json")) != content_hash(
        load_fixture("acme__c-000002.json")
    )


def test_non_ascii_is_stable(load_fixture):
    # c-000025 is Japanese — hashing must not depend on unicode escaping.
    doc = load_fixture("globex__c-000025.json")
    assert content_hash(doc) == content_hash(doc)


def test_change_in_content_changes_hash(load_fixture):
    doc = load_fixture("acme__c-000001.json")
    before = content_hash(doc)
    doc["turns"][0]["text"] = doc["turns"][0]["text"] + " (edited)"
    assert content_hash(doc) != before
