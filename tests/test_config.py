"""Layer 0 — Config loads, is immutable, and coerces env overrides."""

import dataclasses

import pytest

from pipeline import SCHEMA_VERSION, Config


def test_defaults_load():
    cfg = Config()
    assert cfg.model_name == "cardiffnlp/twitter-roberta-base-sentiment-latest"
    assert cfg.recency_lambda == 0.5
    assert cfg.label_threshold == 0.15
    assert cfg.trajectory_divisor == 2.0
    assert cfg.meaningful_min_turns == 3
    assert cfg.roles_in_metrics == ("customer",)
    assert cfg.score_agent_turns is False
    assert cfg.max_delivery == 3
    assert cfg.schema_version == SCHEMA_VERSION


def test_is_frozen():
    cfg = Config()
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.recency_lambda = 0.9  # type: ignore[misc]


def test_from_env_empty_equals_defaults():
    assert Config.from_env({}) == Config()


def test_from_env_coerces_types():
    cfg = Config.from_env(
        {
            "SB_RECENCY_LAMBDA": "0.7",
            "SB_BATCH_SIZE": "8",
            "SB_SCORE_AGENT_TURNS": "true",
            "SB_ROLES_IN_METRICS": "customer, agent",
            "SB_DATABASE_URL": "postgresql://x:y@db:5432/z",
        }
    )
    assert cfg.recency_lambda == 0.7
    assert isinstance(cfg.recency_lambda, float)
    assert cfg.batch_size == 8
    assert isinstance(cfg.batch_size, int)
    assert cfg.score_agent_turns is True
    assert cfg.roles_in_metrics == ("customer", "agent")
    assert cfg.database_url == "postgresql://x:y@db:5432/z"


def test_from_env_ignores_unknown_prefixed_vars():
    cfg = Config.from_env({"SB_NOT_A_FIELD": "whatever", "SB_RECENCY_LAMBDA": "0.3"})
    assert cfg.recency_lambda == 0.3


def test_metric_params_carries_the_tunables():
    params = Config(recency_lambda=0.6, trajectory_divisor=1.5).metric_params()
    assert params["overall"]["lambda"] == 0.6
    assert params["trajectory"]["B"] == 1.5
    assert params["roles_in_metrics"] == ["customer"]
    assert params["empty_text_policy"] == "excluded"
