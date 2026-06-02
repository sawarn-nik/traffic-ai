# 🚦 Traffic-AI — Project Handoff Document

> **Author:** Nikhil Kumar  
> **Institute:** IIT Kharagpur  
> **Last Updated:** June 2026  
> **Personal repo:** [github.com/sawarn-nik/traffic-ai](https://github.com/sawarn-nik/traffic-ai)  
> **Team repo:** [github.com/lakshya1729git/IIT_kgp_internship](https://github.com/lakshya1729git/IIT_kgp_internship)

---

## Table of Contents

1. [What This Project Is](#1-what-this-project-is)
2. [Research Proposal Summary](#2-research-proposal-summary)
3. [System Architecture](#3-system-architecture)
4. [Layer 1 — Complete](#4-layer-1--complete)
5. [File-by-File Breakdown](#5-file-by-file-breakdown)
6. [How to Run](#6-how-to-run)
7. [Two-Step API Design](#7-two-step-api-design)
8. [Bugs Fixed](#8-bugs-fixed)
9. [Layer 2 — What to Build Next](#9-layer-2--what-to-build-next)
10. [Layer 3 — What to Build Next](#10-layer-3--what-to-build-next)
11. [GitHub Setup](#11-github-setup)
12. [Design Decisions](#12-design-decisions)

---

## 1. What This Project Is

Current trip planners (Google Maps, Apple Maps) are **reactive** — they update routes only after disruptions are already detected by sensors.

This project builds an **anticipatory** system for Kolkata. It reads unstructured sources (news, public advisories, TomTom live incidents) *before* you travel, extracts structured disruption events using an LLM, and scores your route in real time.

**Core question:** *"I want to travel from Howrah Station to Salt Lake Sector V right now. What disruptions are on my route?"*

**Pilot city:** Kolkata, India  
**Research grant:** ANRF ARG, IIT Kharagpur  
**Industry collaboration:** Kolkata Traffic Police

---

## 2. Research Proposal Summary

**Title:** *A Probabilistic and Explainable Tool for Context-Aware Multimodal Trip Planning Using Generative Artificial Intelligence (GenAI)*

### The problem

```
Current systems:                    This system:
─────────────────                   ────────────────────────────────
Structured data only          →     Structured + Unstructured data
Reactive (after disruption)   →     Anticipatory (before disruption)
Travel time minimization      →     Reliability + Risk + Emissions
Black-box decisions           →     Explainable recommendations
```

### Three hypotheses

| # | Hypothesis |
|---|-----------|
| H1 | LLM-derived contextual info improves disruption detection accuracy |
| H2 | Probabilistic + risk-aware routing improves travel reliability |
| H3 | Explainable routing outputs enhance user trust |

---

## 3. System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 1 — LLM Disruption Intelligence          ✅ COMPLETE     │
│  News/TomTom → LLM → TrafficEventSchema → DB                   │
│  Outputs: event_type, location, severity σ, confidence κ        │
└───────────────────────────┬─────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 2 — Bayesian Probabilistic Fusion         🔲 TODO        │
│  Layer 1 signals + GTFS-RT + weather                           │
│  → Bayesian update → π_post per road edge                      │
└───────────────────────────┬─────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 3 — Risk-Aware Routing + Explainability   🔲 TODO        │
│  Generalized edge cost (CVaR) → optimal route                  │
│  + Natural language route justification                        │
└─────────────────────────────────────────────────────────────────┘
```

### Data sources

| Source | Type | Recency | Used for |
|--------|------|---------|----------|
| Google News RSS `when:2d` | Unstructured | Last 2 days | City-wide disruption news |
| NewsAPI | Unstructured | Last 24h | Per-road articles |
| TomTom Traffic API | Structured | Live (minutes) | Real-time incidents with coordinates |
| OpenWeatherMap | Structured | Live | Monsoon / waterlogging conditions |
| OSMnx Kolkata graph | Structured | Cached | Route computation |

---

## 4. Layer 1 — Complete

### Pipeline overview

```
Step 1  User picks source + destination from menu of 15 Kolkata localities

Step 2  /api/route called (fast, ~2s)
        OSMnx computes 2–3 alternative routes on cached Kolkata graph
        GeoJSON returned → map draws immediately

Step 3  /api/disruptions called (background, ~30–60s)
        a. Fetch TomTom incidents (live, Kolkata bounding box)
        b. Fetch Google News RSS per road (when:2d)
        c. Fetch city-wide Kolkata feeds
        d. Pre-LLM filter: age, geography, traffic relevance
        e. LLM chain extracts TrafficEventSchema per article
        f. Location resolver: enriches/recovers missing locations
        g. Enhanced confidence scoring (multi-factor)
        h. Impact duration estimation
        i. Semantic deduplication of near-identical events
        j. Spatial route matching (corridor-based)
        k. Risk scoring per route: Σ(σ × κ) for recent events
        l. Map updated with colour-coded routes + markers
```

### LLM extraction schema

```python
class TrafficEventSchema(BaseModel):
    event_type:      EventType   # accident | congestion | road_closure |
                                 # construction | protest | weather |
                                 # waterlogging | vip_movement | unknown
    location:        str         # mandatory — events without location are discarded
    road_name:       str | None
    severity:        Severity    # low | medium | high
    confidence:      float       # κ ∈ [0.0, 1.0]
    reason:          str
    time_mentioned:  str | None
    is_future_event: bool
```

**Location is mandatory.** If the LLM returns no location:
- confidence ≥ 0.6 → second LLM pass (location-only retry)
- confidence < 0.6 → event discarded

### Scoring

```
σ (severity_score):  low=2  medium=5  high=10
κ (confidence):      LLM score adjusted by source reliability, age, location quality
weighted_score:      σ × κ

route_risk:  Σ weighted_score (recent, non-future events matched to route)

Risk levels:   CRITICAL ≥ 25 | HIGH ≥ 12 | MODERATE ≥ 5 | LOW > 0 | CLEAR = 0
Best route:    lowest  travel_time_min × (1 + risk_score / 10)
```

### JSON repair

The LLM occasionally returns malformed JSON. The extractor repairs it in three stages:
1. Strip markdown fences, extract JSON object
2. Fix missing colons: `{"key","val"}` → `{"key":"val"}`
3. Regex field extraction as last resort

---

## 5. File-by-File Breakdown

```
app/
├── api.py                     FastAPI server. Two endpoints:
│                                POST /api/route       → fast routes (no LLM)
│                                POST /api/disruptions → LLM extraction + scoring
├── main.py                    CLI version (debugging use only)
├── config.py                  All env var reads. Feature flags: ENABLE_TOMTOM etc.
│
├── static/
│   └── index.html             Single-file Leaflet.js frontend.
│                                Step 1: draws routes immediately
│                                Step 2: fills disruptions in background
│
├── ingestion/
│   ├── rss_fetcher.py         Google News RSS. All queries use when:Nd for recency.
│   │                            7 Kolkata-specific feeds (traffic, police, accident,
│   │                            flood, protest, storm, bridge closure)
│   ├── news_fetcher.py        NewsAPI with date parsing + age labels
│   ├── tomtom_fetcher.py      TomTom Traffic Incidents API v5
│   │                            Kolkata bbox: 88.24,22.45,88.46,22.63
│   │                            Free tier: 2500 req/day
│   └── weather_fetcher.py     OpenWeatherMap (optional)
│
├── llm/
│   ├── extractor.py           LangChain LCEL chain
│   │                            Primary: with_structured_output(TrafficEventSchema)
│   │                            Fallback: PydanticOutputParser
│   │                            Repair: _repair_json() for malformed output
│   │                            Retry: exponential backoff on 429
│   ├── prompts.py             Two prompts:
│   │                            TRAFFIC_PROMPT — main extraction (Kolkata-tuned)
│   │                            LOCATION_RETRY_PROMPT — focused location recovery
│   ├── schema.py              TrafficEventSchema (Pydantic). Single source of truth.
│   ├── filter.py              Pre-LLM: age/geo/relevance filtering
│   │                            Post-LLM: semantic deduplication
│   └── location_resolver.py   Enriches/infers missing locations
│
├── routing/
│   ├── route_engine.py        OSMnx routing for Kolkata
│   │                            get_route() — single shortest path
│   │                            get_multiple_routes() — 2–3 alternatives with GeoJSON
│   │                            Cached graph: cache/graph.graphml
│   │                            Bounds check: rejects out-of-city inputs
│   └── cost_function.py       Layer 3 placeholder (Eq. 3 documented)
│
├── scoring/
│   ├── congestion_score.py    σ × κ base computation
│   ├── confidence.py          Enhanced confidence: source reliability + age + location
│   └── impact_duration.py     Estimates how long an event will last
│
├── fusion/
│   └── bayesian_fusion.py     Layer 2 placeholder (Eq. 1 documented)
│
├── database/
│   └── models.py              SQLAlchemy TrafficEvent model
│                                Auto-migration on startup (ALTER TABLE)
│                                19 columns including TomTom-specific fields
│
└── utils/
    └── helpers.py             clean_html, deduplicate, now_iso, build_article_text
```

---

## 6. How to Run

```bash
# Clone
git clone https://github.com/sawarn-nik/traffic-ai.git
cd traffic-ai

# Environment
python3 -m venv venv
source venv/bin/activate
pip install -r req.txt

# Keys
cp .env.example .env
# Edit .env — minimum: OPENROUTER_API_KEY or GEMINI_API_KEY

# Start server
cd app
uvicorn api:app --port 8000 --reload

# Open browser
# http://localhost:8000
```

**First run:** Kolkata OSM graph downloads once (~30s) and caches to `cache/graph.graphml`. All subsequent runs load from disk in ~2s.

**Recommended LLM model** (set in `.env`):
```
OPENROUTER_MODEL=meta-llama/llama-3.3-70b-instruct:free   # best quality
OPENROUTER_MODEL=deepseek/deepseek-v4-flash:free           # fastest
```

---

## 7. Two-Step API Design

The key UX improvement over a naive single-request design:

```
User clicks "Get Routes"
        │
        ▼
POST /api/route  (~2 seconds)
  - OSMnx computes 2–3 routes
  - Returns GeoJSON immediately
  - All routes shown as GREEN (no risk data yet)
        │
        ▼  (map renders — user sees routes immediately)
        │
POST /api/disruptions  (~30–60 seconds, runs in background)
  - Fetches TomTom + RSS + NewsAPI
  - Runs LLM extraction on all articles
  - Scores each route
  - Returns updated risk colors + event markers
        │
        ▼  (map updates with real colors, panel fills with events)
```

This means the user is never staring at a blank screen for a minute.

---

## 8. Bugs Fixed

| # | File | Bug | Fix |
|---|------|-----|-----|
| 1 | `extractor.py` | Dead `_invoke_with_format` + `_current_text` global | Removed |
| 2 | `extractor.py` | Malformed JSON from LLM crashes parser | Added `_repair_json()` + regex fallback |
| 3 | `news_fetcher.py` | No date parsing → all articles `is_recent=True` | Added `_parse_newsapi_date()` |
| 4 | `rss_fetcher.py` | `_is_recent` hardcoded `max_days=30` vs main's `RECENT_DAYS=7` | Made `recent_days` a parameter |
| 5 | `database/models.py` | `article_published_at` column missing → DB crash | Added column + auto-migration |
| 6 | `route_engine.py` | `os.path.dirname("")` crash on relative cache path | Changed to `os.path.abspath()` |
| 7 | `helpers.py` | `deduplicate` treats `None` URL as dedup key | Items with no key always kept |
| 8 | `route_engine.py` | IIT Kharagpur (100km away) silently produced wrong Kolkata route | Added `_check_within_kolkata()` bounds check |
| 9 | `rss_fetcher.py` | No time-scoping → articles from months ago inflate risk score | Added `when:Nd` operator to all RSS URLs |
| 10 | `extractor.py` | No location → events kept with null location | Location now mandatory; retry pass at κ ≥ 0.6; discard otherwise |

---

## 9. Layer 2 — What to Build Next

**File:** `app/fusion/bayesian_fusion.py` (placeholder with full spec)  
**Branch:** `feature/layer2-bayesian-fusion`

### Goal

Layer 1 gives `weighted_score = σ × κ` per article. Layer 2 converts this into a proper posterior disruption probability per road edge using Bayes' rule.

### Equation (Eq. 1 from proposal)

```
π_e^post(t) = p(S | Z_e=1) × π_e^prior(t)
              ─────────────────────────────
              Σ_{z=0}^{1} p(S | Z_e=z) × π_e^prior(t)

Z_e(t)       = binary disruption state for edge e
π_e^prior(t) = baseline probability (time-of-day + historical rate)
S            = Layer 1 signals (σ, κ)
π_e^post(t)  = output → used by Layer 3 cost function
```

### What to build

```python
# app/fusion/bayesian_fusion.py

def compute_prior(road_name: str, hour: int) -> float:
    """Time-of-day baseline. Peak: 0.20, off-peak: 0.05."""

def compute_posterior(road_name: str, sigma: float, kappa: float, prior: float) -> float:
    """Bayesian update given Layer 1 signals."""

def fuse_route_disruptions(road_names: list[str]) -> dict[str, float]:
    """
    Query traffic_events.db for recent signals per road,
    apply Bayesian update, return posterior probabilities.
    """
```

### Output format Layer 3 needs

```python
{
    "Rabindra Sarani":  0.82,
    "Brabourne Road":   0.34,
    "College Street":   0.12,
}
```

---

## 10. Layer 3 — What to Build Next

**File:** `app/routing/cost_function.py` (placeholder with full spec)  
**Branch:** `feature/layer3-routing`

### Goal

Replace the current `Σ(σ × κ)` risk score with a proper stochastic optimization that finds the most *reliable* route, not just the shortest.

### Equation (Eq. 3 from proposal)

```
c_e(t) = c_base(t)
       + λ1·E[τ̃_e(t)]     ← expected travel time
       + λ2·Var[τ̃_e(t)]    ← reliability (penalise variance)
       + λ3·κ·σ             ← disruption risk
       + λ4·CO2(e)          ← emissions
       + λ5·Transfers(e)    ← mode-switch penalty

λ weights: user-configurable (risk-averse vs time-optimal vs eco)
```

### Optimization objectives

```python
# Objective 1: expected cost
min E[C(P)]

# Objective 2: CVaR — penalises worst-case delays
min CVaR_α(C(P))

# Objective 3: on-time guarantee
min E[C(P)]  subject to  P(T(P) ≤ T*) ≥ 1 − ε

# Objective 4: multi-objective
min ω1·E[T] + ω2·Var[T] + ω3·CO2 + ω4·Transfers
```

### Files to build

```
app/routing/
├── cost_function.py     Generalized edge cost
├── cvar_router.py       CVaR path optimization
└── travel_time.py       Travel time distributions per edge
```

---

## 11. GitHub Setup

### Remotes (already configured)

```bash
git remote -v
# origin  https://github.com/sawarn-nik/traffic-ai.git (fetch)
# origin  https://github.com/sawarn-nik/traffic-ai.git (push)
# origin  https://github.com/lakshya1729git/IIT_kgp_internship.git (push)
# team    https://github.com/lakshya1729git/IIT_kgp_internship.git (fetch)
```

`git push` → updates both repos.  
`git pull` → pulls from personal repo only.  
`git pull team main` → pull from team repo.

### Branch workflow

```bash
git checkout dev
git pull origin dev
git checkout -b feature/your-work
# ... work ...
git push origin feature/your-work
# Open PR into dev on GitHub
```

---

## 12. Design Decisions

**Why two-step API?**  
Route computation is fast (2s). LLM extraction is slow (30–60s). Separating them means the user sees the map immediately and waits only for the risk overlay — dramatically better UX.

**Why Leaflet.js + OSM instead of Google Maps?**  
No API key, no billing, no usage limits. OSM tile servers are free. Leaflet is 42KB. The research prototype stays dependency-free for the frontend.

**Why `when:Nd` in Google News RSS?**  
Without it, Google News returns articles from any time period. A Durga Puja article from 8 months ago would score as a current disruption and inflate the risk score. `when:2d` restricts to the last 2 days — the single biggest quality improvement.

**Why TomTom over Twitter?**  
Twitter's free API doesn't support reading tweets (2025). TomTom Traffic Incidents API is free (2500 req/day), gives real coordinates, and has data from minutes ago — not hours.

**Why location is mandatory?**  
An event with no location cannot be matched to a road segment. Keeping it would add noise to the risk score. The location retry pass (κ ≥ 0.6) recovers most high-value events before discarding.

**Why SQLite?**  
Zero configuration. Runs on any machine. Schema supports easy migration to PostgreSQL — just change `DATABASE_URL` in `.env`. Auto-migration on startup means teammates with old DB files are handled automatically.

---

*Built for the ANRF ARG research proposal — IIT Kharagpur, 2026.*  
*Questions → GitHub Issues. Code discussions → GitHub, not WhatsApp.*
