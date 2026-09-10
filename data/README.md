# Sample dataset

27 synthetic conversations (28 files — one is a deliberate duplicate) in the shape
described in Section 2.1 of the main `README.md`. This is a **starting point, not a
spec**: it exists so you don't spend your time box writing a data generator.

Files are `data/conversations/<tenant>__<conversation_id>.json`, one conversation per
file. Two tenants (`acme`, `globex`) so tenant-scoped keys and prefixes are exercised.
328 turns in total, which is small enough to score end-to-end in one run.

Everything here is invented. No real customer data, no real names, emails, phone
numbers or order references.

## What's in it

**Sentiment arcs** — the normal cases, for sanity-checking that your two metrics behave
the way your definitions claim. `c-000005` is worth a look once you've written
`overall_sentiment`: it averages out to roughly nothing, which may or may not be what
you want to report.

| id | Arc |
| --- | --- |
| `c-000001` | Clean escalation — mildly annoyed to furious, ends in cancellation |
| `c-000002` | Clean recovery — angry opening, genuinely satisfied close |
| `c-000003` | Flat neutral — pure information request, no affect either way |
| `c-000004` | Never recovers — steadily negative, no swing |
| `c-000005` | Whiplash — swings hard positive/negative four times, ends positive |
| `c-000006` | Gradual improvement that lands neutral, not positive |
| `c-000007` | Starts positive, degrades — negative trajectory from a positive base |
| `c-000008` | Agent-heavy, sparse customer turns, `system` turns present |
| `c-000009` | Mild, polite dissatisfaction — low-magnitude negative |
| `c-000010` | Longer healthy conversation, resolves positive |

**Edge cases** — these are the ones that break naive implementations, mostly about the
difference between `null` and `0.0`:

| id | Why it's here |
| --- | --- |
| `c-000016` | Single turn — trajectory is *undefined*, not zero |
| `c-000017` | Zero customer turns (agent + system only) — every customer metric undefined |
| `c-000018` | Empty `turns: []` — must not crash, must not silently score `0.0` |
| `c-000019` | Empty string and whitespace-only `text` (spaces, tab/newline) |
| `c-000020` | Exactly two customer turns — trajectory is technically defined and statistically meaningless |
| `c-000021` | Non-monotonic and duplicate `seq` values |
| `c-000022` | Emoji-only and punctuation-only turns — low signal |
| `c-000023` | Sarcasm and double negation — a small model will likely get these wrong |
| `c-000024` | French — an English model returns a *confident wrong answer* |
| `c-000025` | Japanese |
| `c-000026` | Mixed language within a single conversation |
| `c-000027` | One ~3,900-character turn — exceeds typical token limits: truncate or chunk? |
| `c-000028` | 200 turns — batching, and the load-balance question when work-per-conversation varies 200x |

**Malformed records** — these must fail cleanly without poisoning the rest of the batch.
How you categorise and route them is your call:

| id | Defect |
| --- | --- |
| `c-000029` | `turns` key missing entirely |
| `c-000030` | `turns` is a string, not an array |
| `c-000031` | Turn objects with a missing `ts`, a `null` text, an integer text, a `seq` as string, an unknown role, a missing `seq` |
| `c-000032` | Only `bot` roles — no recognised `customer`/`agent`/`system` turn |

**Duplicate** — `acme__c-000002.duplicate.json` is byte-identical to
`acme__c-000002.json` and carries the same `conversation_id`. Two files, one
conversation: if you enqueue the directory, you get the double-delivery case for free.

## Notes

- Ids are intentionally non-contiguous (`c-000010` → `c-000016`) so you can add fixtures
  without renumbering.
- All timestamps are derived from a fixed base instant, so nothing here depends on when
  it was generated.
- Ordering within a file follows array position, which for `c-000021` deliberately
  disagrees with `seq`. Decide which one you trust.

## Regenerating

`python data/make_dataset.py` rewrites `data/conversations/` in place. It's fully
deterministic — no RNG, no clock reads — so re-running produces byte-identical files,
and you can extend it or clone the set up to a larger volume for a throughput number.

You're free to extend, regenerate or replace any of this — say so in `NOTES.md` if you
change it, and keep additions synthetic.
