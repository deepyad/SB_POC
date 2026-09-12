"""Command-line entry points: ``python -m pipeline <command>``.

Layer 4 adds ``score-file``. Layers 6/7 add ``ingest``, ``run``, ``results``.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from pipeline.config import Config
from pipeline.result import score_conversation


def _cmd_score_file(args: argparse.Namespace) -> int:
    cfg = Config.from_env()
    raw = json.loads(Path(args.path).read_text(encoding="utf-8"))

    from pipeline.sentiment import Scorer  # heavy import — only on the path that scores

    scorer = Scorer(cfg)
    row = score_conversation(raw, cfg, scorer, now=datetime.now(UTC))
    print(json.dumps(row, indent=2, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    score_file = sub.add_parser(
        "score-file", help="score one conversation JSON file and print the result row"
    )
    score_file.add_argument("path", help="path to a conversation JSON file")
    score_file.set_defaults(func=_cmd_score_file)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
