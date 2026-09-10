# SB_Project — sentiment scoring pipeline

Scorebuddy technical challenge. A worker pulls completed support conversations off
a queue, scores the sentiment of each turn, derives two conversation-level
metrics (`overall_sentiment`, `sentiment_trajectory`), and writes one durable
result per conversation.

- Design decisions: `../Architecture_Decision_Record.md`
- Build order: `../Implementation_Details.md`
- Assessed write-up: `NOTES.md`

## Status

Built layer by layer. Current: **Layer 0 — scaffold, git, config.**

| Layer | State |
| --- | --- |
| 0 Scaffold & config | ✅ |
| 1 Input schema & hashing | ⬜ |
| 2 Sentiment model wrapper | ⬜ |
| 3 The two metrics | ⬜ |
| 4 Result assembly | ⬜ |
| 5 Storage (Postgres) | ⬜ |
| 6 Queue + ingest | ⬜ |
| 7 Worker loop | ⬜ |
| 8 Packaging / clean clone | ⬜ |
| 9 Throughput + NOTES.md | ⬜ |

## Develop (Layers 1–4, pure Python)

Requires Python 3.11+.

```bash
python3 -m venv .venv && source .venv/bin/activate
make install      # pip install -e ".[dev]"
make test
make lint
```

The full run instructions (Docker, one command to a scored result) land in
Layer 8.
