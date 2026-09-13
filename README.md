# SB_Project — sentiment scoring pipeline

Scorebuddy technical challenge. A worker pulls completed support conversations off
a queue, scores the sentiment of each turn, derives two conversation-level
metrics (`overall_sentiment`, `sentiment_trajectory`), and writes one durable
result per conversation.

- Design decisions: `../Architecture_Decision_Record.md`
- Build order: `../Implementation_Details.md`
- Assessed write-up: `NOTES.md`

## Quickstart — clean clone, Docker only

Requires **Docker** (with Compose v2) and nothing else. First `docker build`
downloads the model — see below — everything after that is fully offline.

```bash
docker compose build       # ~2-4 min first time: downloads a CPU PyTorch
                            # wheel (~190 MB) and the pinned sentiment model
                            # (~479 MB). Nothing is fetched at runtime.
docker compose up -d postgres
docker compose run --rm worker migrate
docker compose run --rm worker ingest data/conversations
docker compose run --rm worker run --once
docker compose run --rm worker results --summary
```

Or the whole thing in one go: `bash scripts/smoke.sh`.

Expect, on the shipped sample data:
```
files_seen=28 enqueued=27 already_tracked=1 parse_errors=0
processed=27
scored: 21
partial: 1
rejected: 5
```

Scale it to show the queue boundary claim — two independent containers
claiming disjoint work from the same `jobs` table (ADR-002):
```bash
docker compose up -d --scale worker=2
```

Safe to run unattended: no `sudo`, nothing written outside the project, no
port opened beyond Postgres's `5432` (drop the `ports:` mapping in
`docker-compose.yml` if even that shouldn't be exposed), no TLS disabled, no
committed secrets — `sb`/`sb` in `docker-compose.yml` is a disposable local
dev credential for a container with no external network exposure.

## Status

Built layer by layer. Current: **Layer 8 — packaging (clean clone).**

| Layer | State |
| --- | --- |
| 0 Scaffold & config | ✅ |
| 1 Input schema & hashing | ✅ |
| 2 Sentiment model wrapper | ✅ |
| 3 The two metrics | ✅ |
| 4 Result assembly | ✅ |
| 5 Storage (Postgres) | ✅ |
| 6 Queue + ingest | ✅ |
| 7 Worker loop | ✅ (core complete) |
| 8 Packaging / clean clone | ✅ |
| 9 Throughput + NOTES.md | ⬜ |

## Develop locally (without Docker for the app itself)

Requires Python 3.11+ (macOS: `brew install python@3.11`). Postgres still
needs Docker (`make up`); the app runs in a local venv against it.

```bash
/opt/homebrew/bin/python3.11 -m venv .venv && source .venv/bin/activate
make install      # pip install -e ".[dev]" — editable install, so `import
                  # pipeline` works from anywhere: pytest, a plain script, or
                  # a debugger, with no PYTHONPATH juggling.
make test         # fast tests, no model, no Docker
make lint
```

Add extras as you go deeper:

```bash
pip install -e ".[dev,model]"    # Layer 2+: the sentiment model
make warm-model                  # downloads the pinned model, ~479 MB, ~30-60s
make test-slow                   # or `make test-all` for everything

pip install -e ".[dev,model,db]" # Layer 5+: Postgres
make up && make migrate          # docker compose up -d postgres; apply schema
make test-db                     # storage/queue tests, own throwaway Postgres
```

Local, one-command equivalents of the Docker path (same behaviour, runs
against the venv instead of a container):

```bash
python -m pipeline score-file data/conversations/acme__c-000001.json  # Layer 4
make ingest DIR=data/conversations                                     # Layer 6
make run-once && make results-summary                                  # Layer 7
```

`.vscode/settings.json` points the Python extension at `.venv` and turns on
pytest as the test runner, so the Testing sidebar (flask icon) discovers and
debugs tests correctly. Using the file-level "Debug Python File" run button on
a test file instead runs it as a bare script and will fail with
`ModuleNotFoundError: No module named 'pipeline'` — use the Testing sidebar, or
`make test`, or `pytest --trace` from a terminal.

## Makefile reference

| Target | What |
| --- | --- |
| `install`, `test`, `test-slow`, `test-db`, `test-all`, `lint`, `fmt` | local dev loop |
| `warm-model` | cache the pinned model locally (no Docker) |
| `up`, `down`, `db-reset`, `migrate`, `db-shell` | Postgres via Docker, app via venv |
| `ingest`, `run`, `run-once`, `results`, `results-summary` | the pipeline, via venv |
| `docker-build`, `docker-up`, `docker-down` | the full stack, in containers |
| `seed`, `docker-run-once`, `docker-results` | one-shot container commands |
| `verify` | two live containers score the same conversation; diff except `scored_at` |
| `smoke-test` | `scripts/smoke.sh` — the entire clean-clone sequence |
