#!/usr/bin/env bash
# Layer 8 — the clean-clone sequence, automated for a manual check (brief §9).
# Requires only Docker. Run from the repo root:  bash scripts/smoke.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> docker compose build (downloads the model, ~2-4 min on first run)"
docker compose build

echo "==> starting Postgres"
docker compose up -d postgres

echo "==> waiting for Postgres to report healthy"
for _ in $(seq 1 30); do
  health=$(docker inspect --format='{{.State.Health.Status}}' "$(docker compose ps -q postgres)" 2>/dev/null || echo "")
  [ "$health" = "healthy" ] && break
  sleep 1
done
if [ "$health" != "healthy" ]; then
  echo "Postgres did not become healthy in time" >&2
  exit 1
fi

echo "==> applying migrations"
docker compose run --rm worker migrate

echo "==> ingesting the sample dataset (27 conversations + 1 duplicate)"
docker compose run --rm worker ingest data/conversations

echo "==> scoring everything queued"
docker compose run --rm worker run --once

echo "==> results summary"
docker compose run --rm worker results --summary

echo "==> reproducibility check: the same conversation scored by two separate containers"
docker compose run --rm worker score-file data/conversations/acme__c-000001.json > /tmp/sb_smoke_run1.json
docker compose run --rm worker score-file data/conversations/acme__c-000001.json > /tmp/sb_smoke_run2.json
python3 scripts/verify_reproducibility.py /tmp/sb_smoke_run1.json /tmp/sb_smoke_run2.json
rm -f /tmp/sb_smoke_run1.json /tmp/sb_smoke_run2.json

echo "==> SMOKE TEST PASSED — a clean clone with only Docker produces a scored result"
