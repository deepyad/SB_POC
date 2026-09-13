# SB_Project worker image (Layer 8, ADR-007).
#
# Self-contained on purpose: the pinned sentiment model is downloaded and
# baked in at BUILD time (this RUN step needs network), so the running
# container never touches the network (brief §9 — nothing external at
# runtime). First `docker build` takes roughly 2-4 minutes and downloads:
#   - ~190 MB  CPU-only PyTorch wheel
#   - ~479 MB  the pinned model revision (cardiffnlp/twitter-roberta-base-
#               sentiment-latest @ 3216a57f...)
# No GPU, no account, no API key — just network access during the build.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Create the non-root user *before* anything heavy is written, and COPY
# straight in as that user. Chowning a directory *after* it already holds the
# ~500 MB model (as an earlier version of this file did) makes Docker's
# layered filesystem duplicate that content into the new layer — nearly
# doubling the image for a metadata-only change. Never chown after the fact.
RUN useradd --create-home --uid 1000 sb
WORKDIR /app
COPY --chown=sb:sb pyproject.toml ./
COPY --chown=sb:sb src ./src
COPY --chown=sb:sb migrations ./migrations
COPY --chown=sb:sb data ./data

USER sb
ENV PATH="/home/sb/.local/bin:${PATH}"

# CPU-only torch, from its own index — the default PyPI wheel pulls CUDA
# dependencies and is ~4x larger for no benefit on a CPU-only worker
# (ADR-007). Installed first so the extras below see it already satisfied.
# `db` here is psycopg only (testcontainers lives under `dev` instead — a
# test-infra SDK has no business in the runtime image).
RUN pip install --user --index-url https://download.pytorch.org/whl/cpu "torch==2.6.0" \
    && pip install --user -e ".[model,db]"

# Bake the pinned model weights in now, as `sb` — the one and only
# network-dependent step at build time. Running as `sb` from the start means
# the cache lands in $HOME (/home/sb/.cache/huggingface) and is already where
# it needs to be; no separate cache-directory dance required.
RUN python -m pipeline.warm_model

# Nothing at runtime should be able to reach the network for weights, even by
# accident (ADR-007's safetensors-auto-conversion finding is exactly the kind
# of thing this guards against). Set only now — offline mode would have made
# the warm_model download above fail.
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

ENTRYPOINT ["python", "-m", "pipeline"]
CMD ["run"]
