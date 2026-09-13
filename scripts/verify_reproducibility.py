"""Layer 8 — `make verify`: prove two independent, live scoring runs of the
same conversation agree byte-for-byte except `provenance.scored_at` (brief
§3.3). Used against two `score-file` invocations, e.g. two separate
`docker compose run` containers, not two calls in the same process — that is
the more convincing claim.

    python scripts/verify_reproducibility.py run1.json run2.json
"""

from __future__ import annotations

import json
import sys


def _without_scored_at(row: dict) -> dict:
    return {**row, "provenance": {**row["provenance"], "scored_at": None}}


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(f"usage: {argv[0]} <run1.json> <run2.json>", file=sys.stderr)
        return 2

    with open(argv[1], encoding="utf-8") as f:
        a = json.load(f)
    with open(argv[2], encoding="utf-8") as f:
        b = json.load(f)

    if _without_scored_at(a) == _without_scored_at(b):
        same_timestamp = a["provenance"]["scored_at"] == b["provenance"]["scored_at"]
        print(
            "OK: identical except provenance.scored_at"
            + (" (which also happened to match — fast runs)" if same_timestamp else "")
        )
        return 0

    print("MISMATCH: the two runs are not reproducible", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
