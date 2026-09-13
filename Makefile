# SB_Project — layer-by-layer build (see ../Implementation_Details.md)
# Targets grow as layers land. Layer 0: install / test / lint / fmt / smoke.

PY ?= python3

.PHONY: install test lint fmt smoke clean up down db-reset migrate db-shell run run-once results results-summary \
        docker-build docker-up docker-down seed docker-run-once docker-results verify smoke-test

install:            ## editable install with dev tools (add ,model / ,db in later layers)
	$(PY) -m pip install -e ".[dev]"

test:              ## fast tests only — no model, no Docker needed
	$(PY) -m pytest -m "not slow and not db"

test-slow:         ## tests needing the sentiment model (downloads ~500MB on first run)
	$(PY) -m pytest -m slow

test-db:           ## tests needing Docker (spin up throwaway Postgres via testcontainers)
	$(PY) -m pytest -m db

test-all:          ## everything
	$(PY) -m pytest

warm-model:        ## download + cache the pinned model revision
	$(PY) -m pipeline.warm_model

up:                ## start Postgres in the background (Layer 5+)
	docker compose up -d postgres

down:              ## stop containers, keep the data volume
	docker compose down

db-reset:          ## stop containers AND drop the data volume
	docker compose down -v

migrate:           ## apply migrations/*.sql (idempotent)
	$(PY) -m pipeline.migrate

db-shell:          ## open a psql shell in the running container
	docker compose exec postgres psql -U sb -d sb

DIR ?= data/conversations
ingest:            ## load a directory of conversations into the queue (Layer 6+)
	$(PY) -m pipeline ingest $(DIR)

run:               ## run the worker loop (long-running; Ctrl+C to stop)
	$(PY) -m pipeline run

run-once:          ## drain whatever is currently queued, then exit (Layer 7)
	$(PY) -m pipeline run --once

results:           ## dump all results rows as JSON, one per line
	$(PY) -m pipeline results

results-summary:   ## count results by status
	$(PY) -m pipeline results --summary

lint:              ## static checks
	$(PY) -m ruff check .

fmt:               ## autoformat
	$(PY) -m ruff format .

smoke:             ## import the package without installing
	PYTHONPATH=src $(PY) -c "import pipeline; print('pipeline', pipeline.__version__)"

clean:
	rm -rf .pytest_cache .ruff_cache **/__pycache__ *.egg-info

# --- Layer 8: the clean-clone path — Docker only, nothing else installed ------

docker-build:      ## build the worker image (bakes the model in, ~2-4 min first run)
	docker compose build

docker-up:         ## full stack in the background: postgres + a worker loop
	docker compose up -d

docker-down:       ## stop the full stack, keep the data volume
	docker compose down

seed:              ## ingest the sample dataset via a one-shot container
	docker compose run --rm worker ingest data/conversations

docker-run-once:   ## drain the queue once, via a one-shot container
	docker compose run --rm worker run --once

docker-results:    ## results summary, via a one-shot container
	docker compose run --rm worker results --summary

verify:            ## prove two separate containers agree except scored_at
	docker compose run --rm worker score-file data/conversations/acme__c-000001.json > /tmp/sb_verify_1.json
	docker compose run --rm worker score-file data/conversations/acme__c-000001.json > /tmp/sb_verify_2.json
	$(PY) scripts/verify_reproducibility.py /tmp/sb_verify_1.json /tmp/sb_verify_2.json

smoke-test:        ## the entire clean-clone sequence, end to end
	bash scripts/smoke.sh
