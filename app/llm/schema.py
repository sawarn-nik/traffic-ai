"""
Pydantic schema for a single traffic disruption event.

This is the single source of truth for what the LLM must return.
LangChain's PydanticOutputParser uses this to:
  1. Auto-generate the JSON schema description injected into the prompt
  2. Validate and coerce the LLM's response into a typed Python object
  3. Raise a clear error (instead of silent garbage) if the LLM fails

Fields map directly to the paper's Layer 1 outputs:
  severity  → σ(t)  — disruption severity score
  confidence → κ(t) — confidence in the extraction
"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class EventType(str, Enum):
    accident     = "accident"
    congestion   = "congestion"
    road_closure = "road_closure"
    construction = "construction"
    protest      = "protest"
    weather      = "weather"
    waterlogging = "waterlogging"
    vip_movement = "vip_movement"
    unknown      = "unknown"


class Severity(str, Enum):
    low    = "low"
    medium = "medium"
    high   = "high"


class TrafficEventSchema(BaseModel):
    """Structured traffic disruption event extracted from unstructured text."""

    event_type: EventType = Field(
        description=(
            "Type of disruption: accident, congestion, road_closure, "
            "construction, protest, weather, waterlogging, vip_movement, or unknown"
        )
    )
    location: Optional[str] = Field(
        default=None,
        description="Specific place name, road name, or landmark mentioned in the text"
    )
    road_name: Optional[str] = Field(
        default=None,
        description="Road or highway name if explicitly mentioned, otherwise null"
    )
    severity: Severity = Field(
        description=(
            "Severity of the disruption — "
            "high: major accident/full closure/large protest/severe flooding; "
            "medium: partial blockage/moderate congestion/minor accident; "
            "low: slow traffic/minor delay/advisory only"
        )
    )
    confidence: float = Field(
        description=(
            "How confident you are in this extraction, between 0.0 and 1.0. "
            "Reflects how clearly the text describes a real disruption."
        )
    )
    reason: str = Field(
        description="Brief reason for the disruption in one sentence"
    )
    time_mentioned: Optional[str] = Field(
        default=None,
        description="Any time or date reference found in the text, otherwise null"
    )
    is_future_event: bool = Field(
        default=False,
        description=(
            "True if the event is announced or planned (anticipatory), "
            "False if it is ongoing or already happened"
        )
    )

    # ── Validators ────────────────────────────────────────────────────────────

    @field_validator("confidence")
    @classmethod
    def clamp_confidence(cls, v: float) -> float:
        """Ensure confidence stays within [0.0, 1.0]."""
        return max(0.0, min(1.0, float(v)))

    @field_validator("location", "road_name", "time_mentioned", mode="before")
    @classmethod
    def empty_string_to_none(cls, v):
        """Treat empty strings and the literal string 'null' as None."""
        if isinstance(v, str) and v.strip().lower() in ("", "null", "none", "n/a"):
            return None
        return v

    @field_validator("reason", mode="before")
    @classmethod
    def default_reason(cls, v):
        if not v or str(v).strip().lower() in ("", "null", "none"):
            return "unknown"
        return str(v).strip()
