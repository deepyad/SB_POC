"""Scorebuddy sentiment scoring pipeline.

A worker that pulls completed support conversations off a queue, scores the
sentiment of each turn, derives two conversation-level metrics, and writes one
durable result per conversation.

Design of record: ../Architecture_Decision_Record.md
Build order:      ../Implementation_Details.md
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
