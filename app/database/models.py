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
    """
    __tablename__ = "traffic_events"

    id             = Column(Integer, primary_key=True, autoincrement=True)

    # Source metadata
    source         = Column(String(50),  nullable=False)   # "newsapi" | "rss" | "twitter"
    source_url     = Column(Text,        nullable=True)
    raw_text       = Column(Text,        nullable=False)
    fetched_at     = Column(DateTime,    default=datetime.utcnow)

    # LLM-extracted fields
    event_type     = Column(String(50),  nullable=False, default="unknown")
    location       = Column(String(255), nullable=True)
    road_name      = Column(String(255), nullable=True)
    reason         = Column(Text,        nullable=True)
    time_mentioned = Column(String(100), nullable=True)
    is_future_event = Column(Boolean,   default=False)

    # Severity σ(t) and confidence κ(t) — core Layer 1 outputs per the paper
    severity       = Column(String(10),  nullable=False, default="low")
    severity_score = Column(Integer,     nullable=False, default=1)   # numeric: 2/5/10
    confidence     = Column(Float,       nullable=False, default=0.0) # κ ∈ [0, 1]

    def __repr__(self):
        return (
            f"<TrafficEvent id={self.id} type={self.event_type} "
            f"road={self.road_name} severity={self.severity} "
            f"confidence={self.confidence:.2f}>"
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
