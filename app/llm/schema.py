"""
schema.py — Pydantic schema for a single traffic disruption event.

This is the single source of truth for what the LLM must return.
LangChain's PydanticOutputParser uses this to:
  1. Auto-generate the JSON schema description injected into the prompt
  2. Validate and coerce the LLM's response into a typed Python object
  3. Raise a clear error (instead of silent garbage) if the LLM fails

Fields map directly to the paper's Layer 1 outputs:
  severity   → σ(t)  — disruption severity score
  confidence → κ(t)  — confidence in the extraction (enhanced multi-factor)

Enhanced fields added:
  location_inferred    — True if location was inferred, not directly stated
  location_source      — how the location was determined
  estimated_end_time   — LLM-estimated end time (ISO string or natural language)
  impact_duration_mins — estimated impact duration in minutes
  transport_relevant   — True if the event is transportation-related
"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class EventType(str, Enum):
    accident        = "accident"
    congestion      = "congestion"
    road_closure    = "road_closure"
    construction    = "construction"
    protest         = "protest"
    weather         = "weather"
    waterlogging    = "waterlogging"
    vip_movement    = "vip_movement"
    metro_disruption = "metro_disruption"
    train_delay     = "train_delay"
    transport_strike = "transport_strike"
    diversion       = "diversion"
    unknown         = "unknown"


class Severity(str, Enum):
    low    = "low"
    medium = "medium"
    high   = "high"


class LocationSource(str, Enum):
    direct       = "direct"        # explicitly stated in text
    road_name    = "road_name"     # inferred from road name in text
    landmark     = "landmark"      # inferred from nearby landmark
    coordinates  = "coordinates"   # reverse-geocoded from API coordinates
    llm_inferred = "llm_inferred"  # LLM inferred from context
    unknown      = "unknown"


class TrafficEventSchema(BaseModel):
    """
    Structured traffic disruption event extracted from unstructured text.

    Core Layer 1 outputs per the research proposal:
      severity   → σ(t) — disruption severity
      confidence → κ(t) — extraction confidence (multi-factor enhanced)
    """

    # ── Core event fields ─────────────────────────────────────────────────────

    event_type: EventType = Field(
        description=(
            "Type of disruption. Must be one of: accident, congestion, "
            "road_closure, construction, protest, weather, waterlogging, "
            "vip_movement, metro_disruption, train_delay, transport_strike, "
            "diversion, or unknown. "
            "Use 'unknown' ONLY if the text contains no transportation disruption."
        )
    )

    transport_relevant: bool = Field(
        default=True,
        description=(
            "True if this event is transportation-related (traffic, roads, "
            "metro, trains, buses, waterlogging, weather affecting travel). "
            "False if the text is about something unrelated to transport "
            "(e.g. sports, entertainment, politics with no road impact)."
        )
    )

    location: Optional[str] = Field(
        default=None,
        description=(
            "Specific place name, road name, or landmark where the disruption "
            "is occurring. Extract the most precise location available. "
            "Examples: 'AJC Bose Road near Park Circus', 'Howrah Bridge', "
            "'EM Bypass at Ruby crossing', 'Sealdah Station area'. "
            "If not explicitly stated but can be inferred from context, "
            "provide the inferred location."
        )
    )

    location_inferred: bool = Field(
        default=False,
        description=(
            "True if the location was inferred from context (road names, "
            "landmarks, area descriptions) rather than explicitly stated. "
            "False if the location was directly mentioned in the text."
        )
    )

    location_source: LocationSource = Field(
        default=LocationSource.unknown,
        description=(
            "How the location was determined: "
            "'direct' = explicitly stated, "
            "'road_name' = inferred from road name in text, "
            "'landmark' = inferred from nearby landmark, "
            "'coordinates' = from API geometry, "
            "'llm_inferred' = inferred by reasoning from context, "
            "'unknown' = could not determine."
        )
    )

    road_name: Optional[str] = Field(
        default=None,
        description=(
            "Road or highway name if explicitly mentioned. "
            "Examples: 'AJC Bose Road', 'EM Bypass', 'NH-16', 'Strand Road'. "
            "Null if no specific road is named."
        )
    )

    severity: Severity = Field(
        description=(
            "Severity of the disruption:\n"
            "  high   — major accident, full road/bridge closure, large rally/procession, "
            "severe waterlogging (knee-deep+), metro/train suspension\n"
            "  medium — partial blockage, moderate congestion, minor accident, "
            "moderate waterlogging, metro delay >20 min, diversion\n"
            "  low    — slow traffic, minor delay, advisory only, light waterlogging, "
            "brief VIP movement"
        )
    )

    confidence: float = Field(
        description=(
            "Base LLM confidence in this extraction, between 0.0 and 1.0. "
            "Reflects how clearly the text describes a real, specific disruption. "
            "1.0 = very clear, specific, confirmed event. "
            "0.5 = mentioned but vague. "
            "0.0 = no disruption or completely unclear."
        )
    )

    reason: str = Field(
        description=(
            "Brief, specific reason for the disruption in one sentence. "
            "Be concrete: 'Road blocked due to truck accident near Ultadanga flyover' "
            "not just 'accident'. Include the cause and affected area if known."
        )
    )

    time_mentioned: Optional[str] = Field(
        default=None,
        description=(
            "Any time or date reference found in the text. "
            "Preserve the original format from the text. "
            "Examples: 'today morning', '10 AM to 6 PM', 'Sunday', "
            "'from 8:00 to 14:00'. Null if no time is mentioned."
        )
    )

    is_future_event: bool = Field(
        default=False,
        description=(
            "True if the event is announced or planned but not yet happening. "
            "False if it is ongoing or already happened. "
            "Example: 'Durga Puja procession expected on Sunday' → True. "
            "'Road blocked due to accident' → False."
        )
    )

    estimated_end_time: Optional[str] = Field(
        default=None,
        description=(
            "Estimated or stated end time of the disruption. "
            "Use the official end time if stated in the text. "
            "Otherwise estimate based on event type: "
            "accident → 1-3 hours from now, "
            "congestion → 30 min-2 hours, "
            "road_closure → several hours or days, "
            "construction → days or weeks, "
            "waterlogging → until weather improves, "
            "vip_movement → 30-60 minutes, "
            "protest/rally → 2-6 hours. "
            "Format as natural language: 'approx. 2 hours', 'until evening', "
            "'3-5 days', or ISO time if known."
        )
    )

    impact_duration_mins: Optional[int] = Field(
        default=None,
        description=(
            "Estimated impact duration in minutes. "
            "Use midpoint of range: accident=120, congestion=60, "
            "road_closure=480, construction=10080 (1 week), "
            "waterlogging=240, vip_movement=45, protest=180, "
            "metro_disruption=60, train_delay=90, transport_strike=480. "
            "Use official duration if stated. Null if truly unknown."
        )
    )

    # ── Validators ────────────────────────────────────────────────────────────

    @field_validator("confidence")
    @classmethod
    def clamp_confidence(cls, v: float) -> float:
        """Ensure confidence stays within [0.0, 1.0]."""
        return max(0.0, min(1.0, float(v)))

    @field_validator("impact_duration_mins", mode="before")
    @classmethod
    def clamp_duration(cls, v):
        if v is None:
            return None
        try:
            val = int(v)
            return max(1, min(val, 525600))  # max 1 year in minutes
        except (TypeError, ValueError):
            return None

    @field_validator("location", "road_name", "time_mentioned",
                     "estimated_end_time", mode="before")
    @classmethod
    def empty_string_to_none(cls, v):
        """Treat empty strings and literal 'null'/'none'/'n/a' as None."""
        if isinstance(v, str) and v.strip().lower() in ("", "null", "none", "n/a", "unknown"):
            return None
        return v

    @field_validator("reason", mode="before")
    @classmethod
    def default_reason(cls, v):
        if not v or str(v).strip().lower() in ("", "null", "none", "unknown"):
            return "unknown"
        return str(v).strip()
