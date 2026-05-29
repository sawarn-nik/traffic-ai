"""
parser.py — compatibility shim

With LangChain + PydanticOutputParser, JSON parsing and validation
are handled automatically inside extractor.py.

This file is kept so any external code that imports parse_llm_output
still works. It simply converts a TrafficEventSchema object (or a raw
dict) into a plain dict — the same shape as before.
"""

from typing import Optional
from llm.schema import TrafficEventSchema


def parse_llm_output(raw) -> Optional[dict]:
    """
    Convert a TrafficEventSchema object or plain dict to a dict.
    Returns None if input is None or unparseable.
    """
    if raw is None:
        return None

    # Already a Pydantic model (normal case from extractor.py)
    if isinstance(raw, TrafficEventSchema):
        return raw.model_dump()

    # Plain dict (e.g. from tests or legacy code)
    if isinstance(raw, dict):
        return raw

    return None
