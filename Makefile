# SB_Project — layer-by-layer build (see ../Implementation_Details.md)
# Targets grow as layers land. Layer 0: install / test / lint / fmt / smoke.

PY ?= python3

.PHONY: install test lint fmt smoke clean

install:            ## editable install with dev tools (add ,model / ,db in later layers)
	$(PY) -m pip install -e ".[dev]"

test:              ## run the test suite
	$(PY) -m pytest

lint:              ## static checks
	$(PY) -m ruff check .

fmt:               ## autoformat
	$(PY) -m ruff format .

smoke:             ## import the package without installing
	PYTHONPATH=src $(PY) -c "import pipeline; print('pipeline', pipeline.__version__)"

clean:
	rm -rf .pytest_cache .ruff_cache **/__pycache__ *.egg-info
