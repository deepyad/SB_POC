"""Shared test helpers."""

import json
from pathlib import Path

import pytest

_CONV_DIR = Path(__file__).resolve().parent.parent / "data" / "conversations"


@pytest.fixture
def load_fixture():
    """Return ``load_fixture("acme__c-000001.json") -> dict`` for the sample data."""

    def _load(filename: str) -> dict:
        return json.loads((_CONV_DIR / filename).read_text(encoding="utf-8"))

    return _load
