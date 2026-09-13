"""Layer 2 — the sentiment model wrapper (ADR-007, ADR-008).

Loads a pinned revision of a 3-class (negative / neutral / positive) model once
and scores batches of turn text. CPU, eval mode, no sampling — classification is
an argmax over a forward pass, so the same input gives the same output.

Empty, whitespace-only, or punctuation/ellipsis-only text carries no sentiment
signal (ADR-008) and is never sent to the model: it comes back as an unscored
``TurnScore`` with a reason, which Layer 3's metrics use to exclude it from
aggregation — the deliberate null-vs-0.0 line. Emoji-only text *is* sent to the
model (the corpus it was trained on is tweets, which are full of emoji).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pipeline.config import Config

# Any Unicode "word" character (letters/digits in any script, incl. Japanese,
# French accents, etc.) counts as signal. So does an emoji. Pure whitespace,
# ellipses ("...") and bare punctuation ("?!?!") do not.
_WORD_CHAR = re.compile(r"\w", re.UNICODE)
_EMOJI = re.compile(
    "["
    "\U0001f300-\U0001faff"  # pictographs, emoticons, transport, supplemental symbols
    "\U00002600-\U000027bf"  # misc symbols & dingbats (☀️ ✅ ❌ ...)
    "\U0001f1e6-\U0001f1ff"  # regional indicators (flags)
    "]",
    re.UNICODE,
)


def _has_scoreable_signal(text: str) -> bool:
    return bool(_WORD_CHAR.search(text) or _EMOJI.search(text))


def _disable_safetensors_auto_conversion() -> None:
    """Stop ``transformers`` from silently fetching a *second* copy of the
    weights from an unpinned ref.

    Loading a ``.bin`` checkpoint that has no ``model.safetensors`` file yet
    makes ``PreTrainedModel.from_pretrained`` spawn a background thread that
    opens (or joins) a community PR converting it to safetensors and downloads
    that conversion — from ``refs/pr/<n>``, a ref we never pinned. It is
    unconditional: passing ``use_safetensors=False`` (which we do, to load our
    pinned ``pytorch_model.bin``) does not prevent it, it only picks which
    file *we* load. Left alone it roughly doubles the download (an extra
    ~478 MB observed for this model) and reaches a moving target, which
    conflicts with ADR-007 (self-contained, no surprise network calls). The
    Thread's target is looked up by name in ``modeling_utils`` at call time, so
    rebinding it here to a no-op is enough; it is idempotent.
    """
    import transformers.modeling_utils as _mu

    _mu.auto_conversion = lambda *_args, **_kwargs: (None, None)


@dataclass(frozen=True)
class TurnScore:
    """The per-turn scoring output (ADR-008)."""

    scored: bool
    label: str | None  # "negative" | "neutral" | "positive"
    signed: float | None  # p_positive - p_negative, in [-1, 1]
    confidence: float | None  # max class probability
    reason: str | None = None  # set when scored is False, e.g. "empty_text"


class Scorer:
    """Loads the pinned model once; call :meth:`score_texts` many times."""

    def __init__(self, cfg: Config):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        _disable_safetensors_auto_conversion()

        self._cfg = cfg
        self._torch = torch
        self._tokenizer = AutoTokenizer.from_pretrained(cfg.model_name, revision=cfg.model_revision)
        # use_safetensors=False: load our pinned pytorch_model.bin, not an
        # auto-selected safetensors file (this repo's pinned revision has none).
        self._model = AutoModelForSequenceClassification.from_pretrained(
            cfg.model_name, revision=cfg.model_revision, use_safetensors=False
        )
        self._model.eval()

        # Map by label *name*, not position — robust to the model's id2label
        # ordering (this model happens to be 0=negative,1=neutral,2=positive,
        # but we never assume that).
        id2label = self._model.config.id2label
        self._label_by_idx = {int(k): str(v).lower() for k, v in id2label.items()}
        self._idx_by_label = {v: k for k, v in self._label_by_idx.items()}
        for required in ("negative", "neutral", "positive"):
            if required not in self._idx_by_label:
                raise ValueError(f"{cfg.model_name}@{cfg.model_revision} has no {required!r} class")

    def score_texts(self, texts: list[str], batch_size: int | None = None) -> list[TurnScore]:
        """Score each string; empty/whitespace/punctuation-only ones are skipped.

        `batch_size` overrides `cfg.batch_size` for this call only — used by
        `scripts/bench.py` to compare batch sizes without reloading the model
        (`Config` is frozen, so it can't just be mutated between calls).
        """
        results: list[TurnScore | None] = [None] * len(texts)
        to_score_idx: list[int] = []
        to_score_text: list[str] = []
        for i, text in enumerate(texts):
            if _has_scoreable_signal(text):
                to_score_idx.append(i)
                to_score_text.append(text)
            else:
                results[i] = TurnScore(
                    scored=False, label=None, signed=None, confidence=None, reason="empty_text"
                )

        batch_size = batch_size or self._cfg.batch_size
        for start in range(0, len(to_score_text), batch_size):
            idx_chunk = to_score_idx[start : start + batch_size]
            text_chunk = to_score_text[start : start + batch_size]
            for i, score in zip(idx_chunk, self._score_batch(text_chunk), strict=True):
                results[i] = score

        assert all(r is not None for r in results)  # every slot was filled
        return results  # type: ignore[return-value]

    def _score_batch(self, texts: list[str]) -> list[TurnScore]:
        torch = self._torch
        encoded = self._tokenizer(
            texts,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=self._cfg.max_tokens,
        )
        with torch.no_grad():
            logits = self._model(**encoded).logits
        probs = torch.softmax(logits, dim=-1)

        neg_i = self._idx_by_label["negative"]
        pos_i = self._idx_by_label["positive"]

        out: list[TurnScore] = []
        for row in probs:
            top_idx = int(torch.argmax(row).item())
            out.append(
                TurnScore(
                    scored=True,
                    label=self._label_by_idx[top_idx],
                    signed=row[pos_i].item() - row[neg_i].item(),
                    confidence=row[top_idx].item(),
                    reason=None,
                )
            )
        return out
