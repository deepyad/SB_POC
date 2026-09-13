"""cli.py end to end: each subcommand actually parses its args and wires the
already-tested pieces together. cli.py's functions hard-wire the real
`Scorer`/`PgJobQueue`/`open_pool` with no injection point — this is glue code,
so there is no fast/fake path here. Real Postgres (testcontainers) + the real
model. Marked db + slow.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("testcontainers")
pytest.importorskip("psycopg_pool")

from testcontainers.postgres import PostgresContainer  # noqa: E402

from pipeline import cli  # noqa: E402

pytestmark = [pytest.mark.db, pytest.mark.slow]

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "conversations"


@pytest.fixture(scope="module")
def pg_dsn():
    with PostgresContainer("postgres:16") as pg:
        yield pg.get_connection_url().replace("postgresql+psycopg2", "postgresql")


@pytest.fixture(autouse=True)
def _database_url_env(monkeypatch, pg_dsn):
    monkeypatch.setenv("SB_DATABASE_URL", pg_dsn)


def test_migrate_command(capsys):
    assert cli.main(["migrate"]) == 0
    out = capsys.readouterr().out
    assert "applied" in out or "up to date" in out


def test_score_file_command_prints_a_scored_row(capsys):
    exit_code = cli.main(["score-file", str(DATA_DIR / "acme__c-000001.json")])
    out = capsys.readouterr().out
    assert exit_code == 0
    row = json.loads(out)
    assert row["status"] == "scored"
    assert row["conversation_id"] == "c-000001"


def test_ingest_run_results_end_to_end(capsys):
    cli.main(["migrate"])
    capsys.readouterr()

    assert cli.main(["ingest", str(DATA_DIR)]) == 0
    ingest_out = capsys.readouterr().out
    assert "files_seen=28" in ingest_out
    assert "enqueued=27" in ingest_out

    assert cli.main(["run", "--once"]) == 0
    run_out = capsys.readouterr().out
    assert "processed=27" in run_out

    assert cli.main(["results", "--summary"]) == 0
    summary_out = capsys.readouterr().out
    assert "scored: 21" in summary_out
    assert "partial: 1" in summary_out
    assert "rejected: 5" in summary_out

    assert cli.main(["results"]) == 0
    full_out = capsys.readouterr().out
    rows = [json.loads(line) for line in full_out.splitlines() if line.strip()]
    assert len(rows) == 27
    assert {r["status"] for r in rows} == {"scored", "partial", "rejected"}


def test_ingest_writes_an_ingest_dead_letter_for_a_broken_file(tmp_path, capsys):
    cli.main(["migrate"])
    capsys.readouterr()
    (tmp_path / "broken.json").write_text("{not valid json")

    assert cli.main(["ingest", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "parse_errors=1" in out


def test_unknown_command_is_a_usage_error():
    with pytest.raises(SystemExit):
        cli.main(["not-a-real-command"])
