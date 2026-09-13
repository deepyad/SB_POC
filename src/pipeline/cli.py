"""Command-line entry points: ``python -m pipeline <command>``.

Layer 4 adds ``score-file``. Layer 6 adds ``ingest``. Layer 7 adds ``run``,
``results``.
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


def _cmd_ingest(args: argparse.Namespace) -> int:
    from pipeline.blobstore import upsert_blob
    from pipeline.db import open_pool
    from pipeline.ingest import ingest_directory
    from pipeline.queue import PgJobQueue

    cfg = Config.from_env()
    pool = open_pool(cfg.database_url)
    try:
        queue = PgJobQueue(pool)

        def store_blob(tenant_id: str, conversation_id: str, doc_hash: str, raw: dict) -> None:
            upsert_blob(pool, tenant_id, conversation_id, doc_hash, raw)

        def record_dead_letter(filename: str, error: str) -> None:
            with pool.connection() as conn:
                conn.execute(
                    "INSERT INTO ingest_dead_letters (filename, error) VALUES (%s, %s) "
                    "ON CONFLICT (filename) DO UPDATE SET error = EXCLUDED.error, seen_at = now()",
                    (filename, error),
                )

        stats = ingest_directory(
            Path(args.directory),
            queue=queue,
            store_blob=store_blob,
            record_dead_letter=record_dead_letter,
        )
        print(
            f"files_seen={stats.files_seen} enqueued={stats.enqueued} "
            f"already_tracked={stats.already_tracked} parse_errors={stats.parse_errors}"
        )
    finally:
        pool.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    score_file = sub.add_parser(
        "score-file", help="score one conversation JSON file and print the result row"
    )
    score_file.add_argument("path", help="path to a conversation JSON file")
    score_file.set_defaults(func=_cmd_score_file)

    ingest = sub.add_parser(
        "ingest", help="load a directory of conversation JSON files into the queue"
    )
    ingest.add_argument("directory", help="directory of conversation JSON files")
    ingest.set_defaults(func=_cmd_ingest)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
