"""Command-line entry points: ``python -m pipeline <command>``.

Layer 4 adds ``score-file``. Layer 6 adds ``ingest``. Layer 7 adds ``run``,
``results``. Layer 8 adds ``migrate`` — ``pipeline.migrate`` already has its
own ``__main__`` for local dev (``make migrate``); this is the same thing
reachable through the single Docker entrypoint (``docker compose run --rm
worker migrate``).
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


def _cmd_run(args: argparse.Namespace) -> int:
    from pipeline.db import open_pool
    from pipeline.queue import PgJobQueue
    from pipeline.sentiment import Scorer  # heavy import — only on the path that scores
    from pipeline.worker import run

    cfg = Config.from_env()
    pool = open_pool(cfg.database_url)
    try:
        queue = PgJobQueue(pool)
        scorer = Scorer(cfg)
        processed = run(cfg, pool, queue, scorer, once=args.once)
        print(f"processed={processed}")
    finally:
        pool.close()
    return 0


def _cmd_results(args: argparse.Namespace) -> int:
    from pipeline.db import open_pool

    cfg = Config.from_env()
    pool = open_pool(cfg.database_url)
    try:
        with pool.connection() as conn:
            if args.summary:
                rows = conn.execute(
                    "SELECT status, count(*) FROM results GROUP BY 1 ORDER BY 1"
                ).fetchall()
                for status, count in rows:
                    print(f"{status}: {count}")
            else:
                rows = conn.execute(
                    "SELECT tenant_id, conversation_id, status, overall_sentiment, "
                    "sentiment_trajectory FROM results ORDER BY tenant_id, conversation_id"
                ).fetchall()
                for tenant_id, conversation_id, status, overall, trajectory in rows:
                    print(
                        json.dumps(
                            {
                                "tenant_id": tenant_id,
                                "conversation_id": conversation_id,
                                "status": status,
                                "overall_sentiment": overall,
                                "sentiment_trajectory": trajectory,
                            },
                            ensure_ascii=False,
                        )
                    )
    finally:
        pool.close()
    return 0


def _cmd_migrate(args: argparse.Namespace) -> int:
    from pipeline.migrate import apply_migrations

    cfg = Config.from_env()
    applied = apply_migrations(cfg.database_url)
    print(f"applied: {', '.join(applied)}" if applied else "already up to date")
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

    run = sub.add_parser("run", help="claim and score jobs from the queue")
    run.add_argument(
        "--once", action="store_true", help="drain the currently queued jobs, then exit"
    )
    run.set_defaults(func=_cmd_run)

    results = sub.add_parser("results", help="dump results, or a status summary")
    results.add_argument(
        "--summary", action="store_true", help="print counts by status instead of full rows"
    )
    results.set_defaults(func=_cmd_results)

    migrate = sub.add_parser("migrate", help="apply migrations/*.sql (idempotent)")
    migrate.set_defaults(func=_cmd_migrate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
