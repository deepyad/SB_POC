"""Scorebuddy sentiment scoring pipeline.

A worker that pulls completed support conversations off a queue, scores the
sentiment of each turn, derives two conversation-level metrics, and writes one
durable result per conversation.

See the repo root ``README.md`` for how to run it, and for pointers to the
design-of-record and build-order documents (outside this repo, one level
above ``SB_Project/`` — not shipped as part of the package).
"""

from pipeline.config import SCHEMA_VERSION, Config
from pipeline.hashing import content_hash
from pipeline.schema import (
    DroppedTurn,
    ParsedConversation,
    ParsedTurn,
    Rejection,
    customer_turns,
    parse_conversation,
)

__all__ = [
    "SCHEMA_VERSION",
    "Config",
    "content_hash",
    "parse_conversation",
    "customer_turns",
    "ParsedConversation",
    "ParsedTurn",
    "DroppedTurn",
    "Rejection",
]
__version__ = "0.2.0"
