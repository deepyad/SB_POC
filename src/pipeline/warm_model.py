"""Run once — locally, or as a Docker build step (ADR-007) — to download and
cache the pinned model revision so the worker never touches the network at
runtime (``HF_HUB_OFFLINE=1``).

    python -m pipeline.warm_model
"""

from __future__ import annotations

from pipeline.config import Config


def main() -> None:
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    from pipeline.sentiment import _disable_safetensors_auto_conversion

    _disable_safetensors_auto_conversion()  # see sentiment.py for why

    cfg = Config.from_env()
    print(f"Warming {cfg.model_name} @ {cfg.model_revision} ...")
    AutoTokenizer.from_pretrained(cfg.model_name, revision=cfg.model_revision)
    # use_safetensors=False: load our pinned pytorch_model.bin, not an
    # auto-selected safetensors file (this repo's pinned revision has none).
    AutoModelForSequenceClassification.from_pretrained(
        cfg.model_name, revision=cfg.model_revision, use_safetensors=False
    )
    print("done.")


if __name__ == "__main__":
    main()
