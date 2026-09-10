"""Layer 1 — turn a raw conversation dict into a validated internal form.

The pipeline must never reject a whole conversation just because some of its
turns are malformed (brief §4, fixture ``c-000031``): usable turns are kept,
broken ones are recorded in ``dropped_turns`` with a reason, and only a
structurally unusable document becomes a :class:`Rejection` (ADR-012).

Ordering follows **array position**, not ``seq`` — ``seq`` is coerced to an int
when possible and otherwise ignored (ADR-012, fixture ``c-000021``).

A turn is dropped when scoring could not use it:

======================  ===================================================
reason                   cause
======================  ===================================================
``non_object_turn``      the array element is not a JSON object
``unknown_role``         ``role`` missing or not customer / agent / system
``missing_text``         no ``text`` key
``null_text``            ``text`` is ``null``
``non_string_text``      ``text`` is a number / list / object
``missing_ts``           no ``ts`` key, or ``ts`` is ``null``
======================  ===================================================

Empty / whitespace / punctuation-only ``text`` is **not** dropped here — the
turn is kept and Layer 2 marks it unscoreable (the deliberate null-vs-0.0 line).
"""

from __future__ import annotations

from dataclasses import dataclass

RECOGNISED_ROLES = frozenset({"customer", "agent", "system"})

DropReason = str  # see the table above


@dataclass(frozen=True)
class ParsedTurn:
    """A turn we can hand to the scorer."""

    index: int  # position in the source array — the ordering key
    role: str  # one of RECOGNISED_ROLES
    text: str  # verbatim; may be "" / whitespace (Layer 2 marks those unscoreable)
    seq: int | None  # best-effort; never used for ordering
    ts: str | None  # verbatim string, or None if it was present but not a string


@dataclass(frozen=True)
class DroppedTurn:
    """A turn we could not use, kept for the record (ADR-012)."""

    index: int
    reason: DropReason


@dataclass(frozen=True)
class ParsedConversation:
    tenant_id: str
    conversation_id: str
    channel: str | None
    started_at: str | None
    turns: tuple[ParsedTurn, ...]
    dropped_turns: tuple[DroppedTurn, ...]


@dataclass(frozen=True)
class Rejection:
    """The document is structurally unusable — no per-turn work is possible.

    reason ∈ { not_an_object, missing_tenant_id, missing_conversation_id,
               no_turns_key, turns_not_list, no_recognised_roles }
    """

    reason: str
    detail: str = ""


def _coerce_seq(value: object) -> int | None:
    if isinstance(value, bool):  # bool is an int subclass — reject it explicitly
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _parse_turn(index: int, raw: object) -> ParsedTurn | DroppedTurn:
    if not isinstance(raw, dict):
        return DroppedTurn(index, "non_object_turn")

    role = raw.get("role")
    if not isinstance(role, str) or role not in RECOGNISED_ROLES:
        return DroppedTurn(index, "unknown_role")

    if "text" not in raw:
        return DroppedTurn(index, "missing_text")
    text = raw["text"]
    if text is None:
        return DroppedTurn(index, "null_text")
    if not isinstance(text, str):
        return DroppedTurn(index, "non_string_text")

    ts_raw = raw.get("ts")
    if ts_raw is None:  # missing key or explicit null
        return DroppedTurn(index, "missing_ts")
    ts = ts_raw if isinstance(ts_raw, str) else None

    return ParsedTurn(
        index=index,
        role=role,
        text=text,
        seq=_coerce_seq(raw.get("seq")),
        ts=ts,
    )


def parse_conversation(raw: object) -> ParsedConversation | Rejection:
    """Validate one conversation document.

    Returns a :class:`ParsedConversation` (possibly with ``dropped_turns`` and/or
    an empty ``turns`` tuple) or a :class:`Rejection` when nothing can be scored.
    """
    if not isinstance(raw, dict):
        return Rejection("not_an_object", f"top level is {type(raw).__name__}")

    tenant_id = raw.get("tenant_id")
    if not isinstance(tenant_id, str) or not tenant_id:
        return Rejection("missing_tenant_id")
    conversation_id = raw.get("conversation_id")
    if not isinstance(conversation_id, str) or not conversation_id:
        return Rejection("missing_conversation_id")

    if "turns" not in raw:
        return Rejection("no_turns_key")
    turns_raw = raw["turns"]
    if not isinstance(turns_raw, list):
        return Rejection("turns_not_list", f"turns is {type(turns_raw).__name__}")

    kept: list[ParsedTurn] = []
    dropped: list[DroppedTurn] = []
    for i, element in enumerate(turns_raw):
        parsed = _parse_turn(i, element)
        if isinstance(parsed, ParsedTurn):
            kept.append(parsed)
        else:
            dropped.append(parsed)

    # A non-empty turns array with nothing usable = c-000032 (only "bot" roles).
    # An empty turns array (c-000018) is NOT rejected here — it parses to zero
    # turns and Layer 4 reports it as `rejected` (no customer turns).
    if turns_raw and not kept:
        return Rejection("no_recognised_roles", f"{len(dropped)} turns, none usable")

    channel = raw.get("channel")
    started_at = raw.get("started_at")
    return ParsedConversation(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        channel=channel if isinstance(channel, str) else None,
        started_at=started_at if isinstance(started_at, str) else None,
        turns=tuple(kept),
        dropped_turns=tuple(dropped),
    )


def customer_turns(parsed: ParsedConversation) -> tuple[ParsedTurn, ...]:
    """The turns the two metrics are computed over (ADR-011)."""
    return tuple(t for t in parsed.turns if t.role == "customer")
