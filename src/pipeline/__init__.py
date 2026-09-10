"""Scorebuddy sentiment scoring pipeline.

A worker that pulls completed support conversations off a queue, scores the
sentiment of each turn, derives two conversation-level metrics, and writes one
durable result per conversation.

Design of record: ../Architecture_Decision_Record.md
Build order:      ../Implementation_Details.md
"""

from pipeline.config import SCHEMA_VERSION, Config

__all__ = ["Config", "SCHEMA_VERSION"]
__version__ = "0.1.0"
