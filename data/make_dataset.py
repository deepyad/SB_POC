"""Build the shipped sample dataset for the sentiment-pipeline challenge.

Deterministic: no randomness, no clock reads. Re-running overwrites byte-identically.
All content is synthetic. No real names, emails, phone numbers or order numbers that
resolve to anything.
"""

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timedelta, timezone

OUT = pathlib.Path(__file__).parent / "conversations"
TENANT_ACME = "acme"
TENANT_GLOBEX = "globex"
BASE = datetime(2026, 3, 2, 9, 14, 0, tzinfo=timezone.utc)


def ts(offset_seconds: int) -> str:
    return (BASE + timedelta(seconds=offset_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def convo(cid, tenant, channel, turn_specs, *, start_offset=0, **extra):
    """turn_specs: list of (role, text) or (role, text, seq_override)."""
    turns = []
    for i, spec in enumerate(turn_specs):
        role, text = spec[0], spec[1]
        seq = spec[2] if len(spec) > 2 else i
        turns.append(
            {
                "seq": seq,
                "role": role,
                "ts": ts(start_offset + i * 40),
                "text": text,
            }
        )
    doc = {
        "conversation_id": cid,
        "tenant_id": tenant,
        "channel": channel,
        "started_at": ts(start_offset),
        "turns": turns,
    }
    doc.update(extra)
    return doc


docs: list[dict] = []

# ---------------------------------------------------------------- normal arcs

# c-000001 — clean escalation: mildly annoyed -> furious
docs.append(convo("c-000001", TENANT_ACME, "chat", [
    ("customer", "Hi, my order was supposed to arrive on Tuesday and it hasn't turned up."),
    ("agent", "Thanks for flagging that. Let me pull up the tracking for you."),
    ("customer", "It just says label created. That's the same as it said four days ago."),
    ("agent", "You're right, the carrier hasn't scanned it. I can raise a lost parcel case."),
    ("customer", "A case? I've already waited a week. I needed this for the weekend."),
    ("agent", "I understand. The case takes 48 hours before I can issue a replacement."),
    ("customer", "This is genuinely useless. Nobody can tell me where my parcel is and now I'm being told to wait again."),
    ("customer", "Cancel the whole thing. I'll buy it elsewhere."),
]))

# c-000002 — clean recovery: angry -> satisfied
docs.append(convo("c-000002", TENANT_ACME, "chat", [
    ("customer", "I've been charged twice for the same order. This is unacceptable."),
    ("agent", "I'm sorry about that — I can see two authorisations on the account. Let me check."),
    ("customer", "I want the second one gone today, not in five working days."),
    ("agent", "Confirmed it's a duplicate. I've voided the second authorisation just now."),
    ("customer", "Oh. So it won't actually leave my account?"),
    ("agent", "Correct — it was never captured, so nothing will be taken. You'll see it drop off within the hour."),
    ("customer", "That's a relief. Thanks for sorting it out so quickly."),
    ("customer", "Really appreciate you actually explaining what happened."),
]))

# c-000003 — flat neutral: pure information request
docs.append(convo("c-000003", TENANT_ACME, "email", [
    ("customer", "Could you confirm the dimensions of the medium size?"),
    ("agent", "The medium measures 40cm x 30cm x 15cm."),
    ("customer", "And the weight?"),
    ("agent", "1.2kg empty."),
    ("customer", "Understood, thank you."),
]))

# c-000004 — never recovers: negative throughout, no swing
docs.append(convo("c-000004", TENANT_GLOBEX, "ticketing", [
    ("customer", "The export has been failing every night for a week."),
    ("agent", "Let me look at the job logs."),
    ("customer", "I raised this last Tuesday and was told it was fixed. It isn't."),
    ("agent", "I can see the retries. The job is timing out at the same step each night."),
    ("customer", "So the same failure, still unresolved, eight days later."),
    ("agent", "I'm escalating this to the platform team now."),
    ("customer", "That's what the last ticket said too."),
]))

# c-000005 — whiplash: swings hard between positive and negative
docs.append(convo("c-000005", TENANT_ACME, "chat", [
    ("customer", "Brilliant, the new dashboard is exactly what I asked for!"),
    ("agent", "Glad to hear it. Anything else I can help with?"),
    ("customer", "Actually no, it's broken. All my saved filters are gone. This is a disaster."),
    ("agent", "Let me check whether they were migrated."),
    ("customer", "Found them under the old tab. Fantastic, panic over, sorry!"),
    ("agent", "No problem at all."),
    ("customer", "Spoke too soon — the shared ones still aren't there and my team is blocked."),
    ("customer", "Honestly the rollout has been a mess."),
    ("agent", "Understood. Shared filters migrate in a second pass; I'll get you a timeline."),
    ("customer", "Great, that's all I needed to know. Thanks!"),
]))

# c-000006 — gradual improvement, ends neutral rather than positive
docs.append(convo("c-000006", TENANT_GLOBEX, "email", [
    ("customer", "Nothing in the onboarding guide matches the actual screens. Waste of an afternoon."),
    ("agent", "Apologies — the guide predates last month's redesign. I'll send the current one."),
    ("customer", "Right. Is there a changelog so I know what else is stale?"),
    ("agent", "Yes, linked at the top of the new guide."),
    ("customer", "OK, that's more workable."),
    ("customer", "I'll go through it and come back if anything else is off."),
]))

# c-000007 — starts positive, degrades (negative trajectory from a positive base)
docs.append(convo("c-000007", TENANT_ACME, "chat", [
    ("customer", "Loving the new integration so far, setup was painless."),
    ("agent", "Great to hear!"),
    ("customer", "Hmm, though the sync seems to be dropping records."),
    ("agent", "How many are you seeing missing?"),
    ("customer", "About a fifth of them. That's a lot worse than I first thought."),
    ("customer", "I can't put this live if it silently loses data."),
]))

# c-000008 — agent-heavy with sparse customer turns
docs.append(convo("c-000008", TENANT_GLOBEX, "ticketing", [
    ("system", "Ticket created via web form."),
    ("customer", "Password reset link expired before I could use it."),
    ("agent", "I can send a fresh one. Links are valid for 15 minutes."),
    ("agent", "Sent to the address on file."),
    ("agent", "Let me know if it doesn't arrive within a few minutes."),
    ("customer", "Got it, worked fine. Thanks."),
    ("system", "Ticket resolved."),
]))

# c-000009 — mild, polite dissatisfaction (low-magnitude negative)
docs.append(convo("c-000009", TENANT_ACME, "email", [
    ("customer", "Not a complaint exactly, but the invoice layout is quite hard to read."),
    ("agent", "Thanks — what specifically is causing trouble?"),
    ("customer", "The tax line is below the total, which trips up our finance team every month."),
    ("agent", "That's fair. I'll pass it to the billing team as feedback."),
    ("customer", "Appreciated, though I suspect it'll sit in a backlog."),
]))

# c-000010 — long-ish healthy conversation, ends positive
docs.append(convo("c-000010", TENANT_GLOBEX, "chat", [
    ("customer", "Trying to set up SSO and the metadata upload keeps erroring."),
    ("agent", "What does the error say?"),
    ("customer", "Invalid certificate. But it's the same file our other vendor accepted."),
    ("agent", "Some providers export a chain rather than a single cert. Can you check how many BEGIN blocks are in it?"),
    ("customer", "Three."),
    ("agent", "That's the issue — we need just the signing cert, the first block."),
    ("customer", "Trying that now."),
    ("customer", "That worked. Well spotted."),
    ("agent", "Anything else on the SSO side?"),
    ("customer", "No, that was the blocker. Thanks, genuinely helpful."),
]))

# ------------------------------------------------- degenerate / edge fixtures

# c-000016 — single customer turn: trajectory and volatility undefined
docs.append(convo("c-000016", TENANT_ACME, "chat", [
    ("customer", "Do you ship to Ireland?"),
]))

# c-000017 — zero customer turns: every customer metric undefined
docs.append(convo("c-000017", TENANT_ACME, "ticketing", [
    ("system", "Ticket auto-created by monitoring: failed webhook delivery."),
    ("agent", "Investigated — receiving endpoint returned 503 for 20 minutes."),
    ("agent", "Deliveries retried successfully. Closing."),
    ("system", "Ticket closed without customer contact."),
]))

# c-000018 — empty turns array
docs.append(convo("c-000018", TENANT_ACME, "chat", []))

# c-000019 — empty and whitespace-only text
docs.append(convo("c-000019", TENANT_ACME, "chat", [
    ("customer", ""),
    ("agent", "Sorry, I didn't catch that — could you resend?"),
    ("customer", "   "),
    ("customer", "\t\n  "),
    ("agent", "Still not coming through on my side."),
    ("customer", "Sorry, phone keyboard. My delivery is late."),
]))

# c-000020 — two customer turns only: volatility technically defined, meaningless
docs.append(convo("c-000020", TENANT_GLOBEX, "email", [
    ("customer", "The report totals look wrong."),
    ("agent", "Which report and which period?"),
    ("customer", "Monthly summary, February. Actually I had a filter applied — it's fine."),
]))

# c-000021 — non-monotonic seq (malformed-ish but parseable)
docs.append(convo("c-000021", TENANT_ACME, "chat", [
    ("customer", "First message about a damaged item.", 0),
    ("agent", "Sorry to hear that — can you share a photo?", 3),
    ("customer", "Photo attached. The corner is crushed.", 1),
    ("agent", "Thanks, I'll arrange a replacement.", 2),
    ("customer", "Great, thank you.", 2),
]))

# c-000022 — emoji-only and punctuation-only turns
docs.append(convo("c-000022", TENANT_ACME, "chat", [
    ("customer", "😡😡😡"),
    ("agent", "I can see you're frustrated. What's happened?"),
    ("customer", "?!?!"),
    ("agent", "Could you tell me a little more so I can help?"),
    ("customer", "👍"),
    ("customer", "..."),
]))

# c-000023 — sarcasm and double negation
docs.append(convo("c-000023", TENANT_GLOBEX, "email", [
    ("customer", "Oh fantastic, another outage. Just what I needed on a Monday."),
    ("agent", "Apologies for the disruption — we're investigating now."),
    ("customer", "No, honestly, it's not like we don't have deadlines or anything."),
    ("agent", "Understood. I'll update you as soon as I have a root cause."),
    ("customer", "Wonderful. Can't wait."),
    ("customer", "I wouldn't say I'm not unhappy about this."),
]))

# c-000024 — French: English model returns confident wrong answers
docs.append(convo("c-000024", TENANT_GLOBEX, "email", [
    ("customer", "Bonjour, ma commande n'est jamais arrivée et personne ne me répond."),
    ("agent", "Je suis désolé pour ce retard. Je vérifie le suivi tout de suite."),
    ("customer", "C'est inadmissible, j'attends depuis trois semaines."),
    ("agent", "Je comprends votre frustration. Je vous envoie un remplacement aujourd'hui."),
    ("customer", "Merci beaucoup, c'est très gentil de votre part."),
]))

# c-000025 — Japanese
docs.append(convo("c-000025", TENANT_GLOBEX, "chat", [
    ("customer", "注文した商品がまだ届いていません。とても困っています。"),
    ("agent", "ご不便をおかけして申し訳ございません。配送状況を確認いたします。"),
    ("customer", "早急に対応してください。"),
    ("agent", "本日中に再発送の手続きをいたします。"),
    ("customer", "ありがとうございます。助かりました。"),
]))

# c-000026 — mixed-language within one conversation
docs.append(convo("c-000026", TENANT_GLOBEX, "chat", [
    ("customer", "Hola, I need to change the delivery address por favor."),
    ("agent", "Of course — what's the new address?"),
    ("customer", "Ya lo cambié en la web pero the confirmation email shows the old one."),
    ("agent", "The email is cached; the shipment will use the updated address."),
    ("customer", "Perfecto, gracias!"),
]))

# c-000027 — one ~4,000 character turn: exceeds token limits
_long = (
    "I am going to lay out the entire history of this issue because every time I contact "
    "support I get asked to start again from the beginning and I would rather write it "
    "once. The first order was placed at the start of the month and arrived with the "
    "wrong item inside, a cable instead of the adapter, and the packing slip listed the "
    "adapter so the error happened at the warehouse rather than at checkout. I reported "
    "it the same day and was told to keep the cable and that a replacement adapter would "
    "ship within two working days. Nothing shipped. I chased on the fourth day and was "
    "told the replacement was blocked because the original had not been marked as "
    "returned, which contradicted the instruction to keep the cable. The second agent "
    "cancelled the first replacement and raised a new one, which generated a refund "
    "notification I did not ask for and which I assume means the replacement was "
    "converted into a refund somewhere in your system. A week later I had neither the "
    "adapter nor the refund, so I called and was told the refund was pending on the "
    "warehouse confirming receipt of an item I had been told to keep. At this point I "
    "asked for the whole order to be cancelled and refunded and was told that was not "
    "possible because a replacement was already in flight, which is the opposite of what "
    "the previous agent said. I have now spoken to four people, each of whom has given me "
    "a different account of what state my order is in, and I have a cable I did not order, "
    "no adapter, and no refund. What I want is very simple and I will restate it clearly "
    "so it cannot be misread again. I want confirmation in writing of what is actually in "
    "flight right now, either a replacement or a refund but not both, I want a date, and I "
    "want to not be asked to explain this a fifth time. If the honest answer is that the "
    "adapter is out of stock and nobody wants to say so, tell me that and refund me, "
    "because I can buy one locally today. What I cannot keep doing is spending twenty "
    "minutes per contact re-establishing facts that are already in the ticket history, "
    "which I assume your agents can see, because otherwise I do not understand what the "
    "ticket history is for. I would also like to know why the packing slip was correct but "
    "the box was not, since that suggests the picking process has no verification step, "
    "and if that is the case then this will happen to other customers and my individual "
    "refund does not fix it. I have been a customer for several years and this is the first "
    "time anything has gone wrong, so I am not writing this to be difficult, I am writing "
    "it because the recovery process has been considerably worse than the original mistake "
    "and somebody should probably know that. Please just tell me the true state of the "
    "order and a date, and I will stop writing very long messages. "
    "For completeness, here are the reference numbers I have been given so far, none of "
    "which appear to relate to each other: the original order acknowledgement, the first "
    "replacement authorisation, the cancellation of that authorisation, the second "
    "replacement, and the unexplained refund notification. Each one arrived from a "
    "different sender address and only two of them mention the item at all, so if your "
    "systems are joining these records on something other than the order, that would "
    "explain why every agent sees a different picture. I mention it only because it seems "
    "like the sort of thing that would be useful for somebody there to know, and because "
    "I would rather this ended with the process being fixed than with me being given a "
    "goodwill voucher I have no use for. To summarise, so that nothing here needs "
    "re-reading: wrong item received, told to keep it, replacement promised, replacement "
    "blocked by a return that was never expected, replacement cancelled, refund raised "
    "without being requested, refund blocked by the same phantom return, and no "
    "resolution after three weeks. One reply, with the true current state and a date, "
    "closes this out."
)
docs.append(convo("c-000027", TENANT_ACME, "email", [
    ("customer", _long),
    ("agent", "Thank you for the detail — let me establish the actual state of the order and come back with a date."),
    ("customer", "Thank you, that's all I asked for."),
]))

# c-000028 — ~200 turns: batching and load-balance behaviour become visible
_long_turns: list[tuple[str, str]] = []
_cust_lines = [
    "It's still not working.",
    "I tried that, same error.",
    "Restarted, no change.",
    "Now it's showing a different error.",
    "This is taking a very long time.",
    "OK that step worked.",
    "Back to the previous error now.",
    "I've cleared the cache as asked.",
    "Nothing in the console output.",
    "Are we getting anywhere with this?",
]
_agent_lines = [
    "Let me check that on my side.",
    "Can you try clearing the cache?",
    "What does the console show?",
    "Please restart the client and retry.",
    "I'm checking the server logs now.",
    "That narrows it down, thanks.",
    "Can you confirm the version number?",
    "Trying a different configuration.",
    "I've applied a change — retry now.",
    "Bear with me while I escalate this.",
]
for i in range(200):
    if i % 25 == 24:
        _long_turns.append(("system", f"Session checkpoint {i // 25 + 1}."))
    elif i % 2 == 0:
        _long_turns.append(("customer", _cust_lines[(i // 2) % len(_cust_lines)]))
    else:
        _long_turns.append(("agent", _agent_lines[(i // 2) % len(_agent_lines)]))
docs.append(convo("c-000028", TENANT_GLOBEX, "chat", _long_turns))

# ------------------------------------------------------- malformed / invalid

# c-000029 — missing turns key entirely
docs.append({
    "conversation_id": "c-000029",
    "tenant_id": TENANT_ACME,
    "channel": "chat",
    "started_at": ts(0),
})

# c-000030 — turns is the wrong type
docs.append({
    "conversation_id": "c-000030",
    "tenant_id": TENANT_ACME,
    "channel": "chat",
    "started_at": ts(0),
    "turns": "My order is late",
})

# c-000031 — turn objects missing required fields / wrong types
docs.append({
    "conversation_id": "c-000031",
    "tenant_id": TENANT_ACME,
    "channel": "email",
    "started_at": ts(0),
    "turns": [
        {"seq": 0, "role": "customer", "ts": ts(0), "text": "The item arrived broken."},
        {"seq": 1, "role": "agent", "text": "Sorry about that."},
        {"seq": 2, "role": "customer", "ts": ts(80), "text": None},
        {"seq": "3", "role": "shopper", "ts": "not-a-timestamp", "text": 42},
        {"role": "customer", "ts": ts(160), "text": "Still waiting."},
    ],
})

# c-000032 — unknown role value only
docs.append(convo("c-000032", TENANT_GLOBEX, "chat", [
    ("bot", "Hi! I'm the automated assistant. How can I help?"),
    ("bot", "I didn't understand that. Transferring you."),
]))

for d in docs:
    path = OUT / f"{d['tenant_id']}__{d['conversation_id']}.json"
    path.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

# c-000002 duplicated under a second filename — same conversation_id, byte-identical
dup = next(d for d in docs if d["conversation_id"] == "c-000002")
(OUT / "acme__c-000002.duplicate.json").write_text(
    json.dumps(dup, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
)

print(f"wrote {len(docs)} conversations + 1 duplicate to {OUT}")
counts: dict[str, int] = {}
for d in docs:
    counts[d["tenant_id"]] = counts.get(d["tenant_id"], 0) + 1
print("per tenant:", counts)
print("total turns:", sum(len(d.get("turns") or []) for d in docs if isinstance(d.get("turns"), list)))
