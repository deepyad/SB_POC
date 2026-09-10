"""Layer 1 — canonical content hash for de-duplication (ADR-005).

The idempotency key is the hash of the conversation's *content*, not of the
delivery or the file bytes, so a re-serialised or key-reordered copy of the same
conversation still collapses to one result. Used at ingest (skip re-enqueue) and
in the worker (skip re-scoring).
"""

from __future__ import annotations

import hashlib
import json

_PREFIX = "sha256:"


def content_hash(raw: dict) -> str:
    """Stable ``"sha256:<hex>"`` digest of a conversation document.

    Canonicalisation: sorted keys, no insignificant whitespace, non-ASCII kept
    as real characters (so the digest does not depend on escaping choices).
    """
    canonical = json.dumps(
        raw,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{_PREFIX}{digest}"
