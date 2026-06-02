from sqlalchemy import (
    create_engine, Column, Integer, String,
    Float, Boolean, DateTime, Text
)
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
from config import DATABASE_URL

Base = declarative_base()


class TrafficEvent(Base):
    """
    Stores a single disruption event extracted by the LLM from one article.

    Maps to Layer 1 output: structured event with severity σ and confidence κ.
    Enhanced with: location inference metadata, impact duration, date formatting,
    multi-factor confidence, and transport relevance flag.
    """
    __tablename__ = "traffic_events"

    id              = Column(Integer, primary_key=True, autoincrement=True)

    # ── Source metadata ───────────────────────────────────────────────────────
    source          = Column(String(60),  nullable=False)
    source_url      = Column(Text,        nullable=True)
    tomtom_url      = Column(Text,        nullable=True)   # TomTom map deep-link
    raw_text        = Column(Text,        nullable=False)
    fetched_at      = Column(DateTime,    default=datetime.utcnow)
    published_date  = Column(String(10),  nullable=True)   # DD/MM/YY

    # ── LLM-extracted fields ──────────────────────────────────────────────────
    event_type      = Column(String(50),  nullable=False, default="unknown")
    transport_relevant = Column(Boolean,  default=True)
    location        = Column(String(255), nullable=True)
    location_inferred = Column(Boolean,   default=False)
    location_source = Column(String(30),  nullable=True)   # direct/road_name/landmark/etc.
    road_name       = Column(String(255), nullable=True)
    reason          = Column(Text,        nullable=True)
    time_mentioned  = Column(String(100), nullable=True)
    is_future_event = Column(Boolean,     default=False)

    # ── Severity σ(t) and confidence κ(t) — core Layer 1 outputs ─────────────
    severity        = Column(String(10),  nullable=False, default="low")
    severity_score  = Column(Integer,     nullable=False, default=1)   # 2/5/10
    confidence      = Column(Float,       nullable=False, default=0.0) # κ ∈ [0,1]
    llm_confidence  = Column(Float,       nullable=True)               # raw LLM κ
    source_reliability = Column(Float,    nullable=True)               # source score

    # ── Impact duration ───────────────────────────────────────────────────────
    start_time_display    = Column(String(20),  nullable=True)   # DD/MM/YY
    estimated_end_time    = Column(String(100), nullable=True)   # natural language or DD/MM/YY HH:MM
    impact_duration_mins  = Column(Integer,     nullable=True)   # minutes
    impact_duration_label = Column(String(50),  nullable=True)   # "2–4 hours"
    duration_source       = Column(String(20),  nullable=True)   # api_official/llm_estimated/rule_based

    def __repr__(self):
        return (
            f"<TrafficEvent id={self.id} type={self.event_type} "
            f"road={self.road_name} severity={self.severity} "
            f"confidence={self.confidence:.2f} "
            f"duration={self.impact_duration_label}>"
        )


# ── Engine & session factory ──────────────────────────────────────────────────

engine = create_engine(DATABASE_URL, echo=False)

SessionLocal = sessionmaker(bind=engine)


def init_db():
    """Create all tables if they don't exist yet."""
    Base.metadata.create_all(engine)


def get_session():
    """Return a new database session."""
    return SessionLocal()
