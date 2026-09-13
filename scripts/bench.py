"""Layer 9 — the throughput number NOTES.md's scale section is built on
(brief §5.1: "backed by a number from your own measured throughput, not a
guess").

Replicates the 27 fixtures' customer turns, preserving conversation
boundaries, up to a target turn count, and scores them through the exact same
`Scorer.score_texts` the worker calls — batched (the real behaviour) and
one-at-a-time (the naive baseline), so the batching speedup is measured, not
assumed.

    python scripts/bench.py [--target-turns 10000] [--batch-size 32]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pipeline.config import Config  # noqa: E402
from pipeline.schema import ParsedConversation, customer_turns, parse_conversation  # noqa: E402
from pipeline.sentiment import Scorer  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "conversations"


def load_conversations() -> list[list[str]]:
    """One list of non-empty customer-turn texts per valid fixture conversation."""
    conversations: list[list[str]] = []
    for path in sorted(DATA_DIR.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        parsed = parse_conversation(raw)
        if not isinstance(parsed, ParsedConversation):
            continue
        texts = [t.text for t in customer_turns(parsed) if t.text.strip()]
        if texts:
            conversations.append(texts)
    return conversations


def replicate(conversations: list[list[str]], target_turns: int) -> list[list[str]]:
    if not conversations:
        raise SystemExit("no fixture conversations with scoreable customer turns found")
    out: list[list[str]] = []
    total = 0
    i = 0
    while total < target_turns:
        conv = conversations[i % len(conversations)]
        out.append(conv)
        total += len(conv)
        i += 1
    return out


def run(
    scorer: Scorer, conversations: list[list[str]], batch_size: int
) -> tuple[float, int, list[float]]:
    """Score every conversation; return (elapsed_seconds, total_turns, per_conversation_ms)."""
    per_conv_ms: list[float] = []
    total_turns = 0
    start = time.perf_counter()
    for texts in conversations:
        t0 = time.perf_counter()
        scorer.score_texts(texts, batch_size=batch_size)
        per_conv_ms.append((time.perf_counter() - t0) * 1000)
        total_turns += len(texts)
    elapsed = time.perf_counter() - start
    return elapsed, total_turns, per_conv_ms


def percentile(data: list[float], p: float) -> float:
    ordered = sorted(data)
    k = round((p / 100) * (len(ordered) - 1))
    return ordered[k]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-turns", type=int, default=10_000)
    parser.add_argument(
        "--batch-size", type=int, default=None, help="defaults to Config.batch_size"
    )
    args = parser.parse_args()

    cfg = Config()
    batch_size = args.batch_size or cfg.batch_size

    print(f"Loading {cfg.model_name} @ {cfg.model_revision} ...")
    load_start = time.perf_counter()
    scorer = Scorer(cfg)
    print(f"Model load: {time.perf_counter() - load_start:.1f}s")

    base = load_conversations()
    conversations = replicate(base, args.target_turns)
    total_target_turns = sum(len(c) for c in conversations)
    print(
        f"Benchmarking {len(conversations)} conversations, {total_target_turns} customer "
        f"turns (replicated from {len(base)} real conversations, {sum(len(c) for c in base)} turns)"
    )

    # Warm-up: exclude one-time lazy-init overhead (thread pools, kernel
    # selection) from the timed runs.
    scorer.score_texts(["warm up the model"], batch_size=1)

    print("\nRunning unbatched (batch_size=1) ...")
    unbatched_elapsed, unbatched_turns, _ = run(scorer, conversations, batch_size=1)

    print(f"Running batched (batch_size={batch_size}) ...")
    batched_elapsed, batched_turns, per_conv_ms = run(scorer, conversations, batch_size=batch_size)

    unbatched_tps = unbatched_turns / unbatched_elapsed
    batched_tps = batched_turns / batched_elapsed
    conv_per_sec = len(conversations) / batched_elapsed

    print("\n=== Results ===")
    print(
        f"Unbatched:  {unbatched_tps:8.1f} turns/sec  "
        f"({unbatched_elapsed:.2f}s for {unbatched_turns} turns)"
    )
    print(
        f"Batched:    {batched_tps:8.1f} turns/sec  "
        f"({batched_elapsed:.2f}s for {batched_turns} turns) "
        f"-- {batched_tps / unbatched_tps:.2f}x unbatched"
    )
    print(f"Conversations/sec (batched): {conv_per_sec:.2f}")
    print(
        f"Per-conversation latency (batched): p50={percentile(per_conv_ms, 50):.1f}ms "
        f"p95={percentile(per_conv_ms, 95):.1f}ms max={max(per_conv_ms):.1f}ms"
    )


if __name__ == "__main__":
    main()
