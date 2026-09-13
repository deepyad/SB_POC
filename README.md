# SB_Project — sentiment scoring pipeline

Scorebuddy technical challenge. A worker pulls completed support conversations off
a queue, scores the sentiment of each turn, derives two conversation-level
metrics (`overall_sentiment`, `sentiment_trajectory`), and writes one durable
result per conversation.

- Design decisions: `../Architecture_Decision_Record.md`
- Build order: `../Implementation_Details.md`
- Assessed write-up: `NOTES.md`

## Status

Built layer by layer. Current: **Layer 6 — queue + ingest.**

| Layer | State |
| --- | --- |
| 0 Scaffold & config | ✅ |
| 1 Input schema & hashing | ✅ |
| 2 Sentiment model wrapper | ✅ |
| 3 The two metrics | ✅ |
| 4 Result assembly | ✅ |
| 5 Storage (Postgres) | ✅ |
| 6 Queue + ingest | ✅ |
| 7 Worker loop | ⬜ |
| 8 Packaging / clean clone | ⬜ |
| 9 Throughput + NOTES.md | ⬜ |

## Develop (Layers 1–4, pure Python)

Requires Python 3.11+ (macOS: `brew install python@3.11`).

```bash
/opt/homebrew/bin/python3.11 -m venv .venv && source .venv/bin/activate
make install      # pip install -e ".[dev]" — editable install, so `import
                  # pipeline` works from anywhere: pytest, a plain script, or
                  # a debugger, with no PYTHONPATH juggling.
make test         # fast tests, no model download
make lint
```

Layer 2 (the sentiment model) needs the `model` extra and a one-time download:

```bash
pip install -e ".[dev,model]"
make warm-model    # downloads the pinned model, ~479 MB, ~30-60s first time
make test-slow     # or `make test-all` to run everything
```

Layer 4 wires validation + scoring + the two metrics into one row — no database
involved, just a dict in, a dict out:

```bash
python -m pipeline score-file data/conversations/acme__c-000001.json
```

Layer 5 needs Docker and the `db` extra:

```bash
pip install -e ".[dev,db]"
make up          # docker compose up -d postgres
make migrate     # applies migrations/*.sql, idempotent
make test-db     # storage/queue tests via testcontainers (own throwaway
                 # Postgres, independent of `make up`)
```

Layer 6 loads a directory of conversations into the queue, de-duplicated:

```bash
make ingest DIR=data/conversations
# files_seen=28 enqueued=27 already_tracked=1 parse_errors=0
```

`.vscode/settings.json` points the Python extension at `.venv` and turns on
pytest as the test runner, so the Testing sidebar (flask icon) discovers and
debugs tests correctly. Using the file-level "Debug Python File" run button on
a test file instead runs it as a bare script and will fail with
`ModuleNotFoundError: No module named 'pipeline'` — use the Testing sidebar, or
`make test`, or `pytest --trace` from a terminal.

The full run instructions (Docker, one command to a scored result) land in
Layer 8.
