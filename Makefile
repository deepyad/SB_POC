# SB_Project — layer-by-layer build (see ../Implementation_Details.md)
# Targets grow as layers land. Layer 0: install / test / lint / fmt / smoke.

PY ?= python3

.PHONY: install test lint fmt smoke clean up down db-reset migrate db-shell

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

lint:              ## static checks
	$(PY) -m ruff check .

fmt:               ## autoformat
	$(PY) -m ruff format .

smoke:             ## import the package without installing
	PYTHONPATH=src $(PY) -c "import pipeline; print('pipeline', pipeline.__version__)"

clean:
	rm -rf .pytest_cache .ruff_cache **/__pycache__ *.egg-info
