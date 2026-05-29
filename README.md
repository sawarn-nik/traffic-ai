# traffic-ai 🚦

**A Probabilistic and Explainable Tool for Context-Aware Multimodal Trip Planning Using Generative AI**

Research prototype for the ANRF ARG grant proposal — IIT Kharagpur.  
Pilot city: **Kolkata, India** | Collaboration with Kolkata Traffic Police.

---

## What this does

Current trip planners are reactive — they only know about disruptions after they happen.  
This system is **anticipatory**: it reads unstructured sources (news, social media, public advisories) in real time, extracts structured disruption events using an LLM, and scores your route before you travel.

```
You enter: Howrah Station → Salt Lake Sector V

System:
  1. Computes driving route on Kolkata OSM graph
  2. Fetches news articles for each road segment + city-wide Kolkata feeds
  3. LLM extracts: event type, location, severity (σ), confidence (κ), future flag
  4. Scores route risk = Σ(σ × κ) across all recent events
  5. Prints disruption summary with HIGH / MODERATE / LOW risk verdict
```

This is **Layer 1** of a 3-layer system described in the proposal:

| Layer | Description | Status |
|-------|-------------|--------|
| **1** | LLM-based disruption intelligence (this repo) | ✅ Working |
| **2** | Bayesian probabilistic data fusion | 🔲 Planned |
| **3** | Risk-aware multimodal routing (CVaR) + explainability UI | 🔲 Planned |

---

## Project structure

```
traffic-ai/
├── app/
│   ├── main.py                  # Entry point — run this
│   ├── config.py                # All settings, reads from .env
│   ├── ingestion/
│   │   ├── rss_fetcher.py       # Google News RSS + Kolkata-specific feeds
│   │   ├── news_fetcher.py      # NewsAPI integration
│   │   └── twitter_fetcher.py   # Twitter/X (requires paid API)
│   ├── llm/
│   │   ├── extractor.py         # LangChain chain + retry logic
│   │   ├── prompts.py           # Kolkata-tuned system prompt
│   │   ├── schema.py            # Pydantic output schema (σ, κ, event fields)
│   │   └── parser.py            # Compatibility shim
│   ├── routing/
│   │   ├── route_engine.py      # OSMnx routing, Kolkata graph cache
│   │   └── geocoder.py          # Nominatim geocoding
│   ├── scoring/
│   │   └── congestion_score.py  # σ × κ weighted score
│   ├── database/
│   │   └── models.py            # SQLAlchemy — traffic_events.db
│   └── utils/
│       └── helpers.py           # Text cleaning, dedup, timestamps
├── data/                        # Datasets (add yours here, not committed)
├── notebooks/                   # Jupyter notebooks for analysis
├── .env.example                 # Copy to .env and fill in your keys
├── req.txt                      # Python dependencies
└── README.md
```

---

## Quickstart

### 1. Clone and set up environment

```bash
git clone https://github.com/YOUR_ORG/traffic-ai.git
cd traffic-ai

python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

pip install -r req.txt
```

### 2. Configure API keys

```bash
cp .env.example .env
# Edit .env and add your keys (see comments inside for where to get them)
```

Minimum required: one of `OPENROUTER_API_KEY` or `GEMINI_API_KEY`.  
`NEWS_API_KEY` is optional but improves article coverage.

### 3. Run

```bash
cd app
python3 main.py
```

You'll be prompted:
```
  Source      : Howrah Station
  Destination : Salt Lake Sector V
```

The Kolkata OSM graph downloads once (~30s) and is cached for all future runs.

---

## Configuration

All settings live in `.env`. Key options:

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENROUTER_API_KEY` | — | Primary LLM backend (free tier available) |
| `GEMINI_API_KEY` | — | Fallback LLM backend |
| `NEWS_API_KEY` | — | NewsAPI for supplementary articles |
| `OPENROUTER_MODEL` | `openai/gpt-oss-20b:free` | Swap model without code changes |
| `DEFAULT_CITY` | `Kolkata, India` | City for OSM graph + geocoding |
| `DATABASE_URL` | `sqlite:///traffic_events.db` | Where events are stored |

---

## Branches and contribution workflow

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full workflow.

| Branch | Purpose |
|--------|---------|
| `main` | Stable, always runnable |
| `dev` | Integration branch — PRs merge here first |
| `feature/layer2-bayesian-fusion` | Layer 2 work |
| `feature/layer3-routing` | Layer 3 CVaR routing |
| `feature/ui-dashboard` | Browser dashboard |

---

## Team

| Member | Area |
|--------|------|
| Nikhil | Layer 1 (LLM pipeline) — repo owner |
| TBD | Layer 2 (Bayesian fusion) |
| TBD | Layer 3 (routing + CVaR) |
| TBD | UI / dashboard |

---

## Research context

This prototype implements the proof-of-concept described in:

> *A Probabilistic and Explainable Tool for Context-Aware Multimodal Trip Planning Using Generative Artificial Intelligence (GenAI)*  
> ANRF ARG Pre-Proposal, IIT Kharagpur, 2026

Key equations implemented:
- **Eq. 1** — Bayesian posterior disruption probability π_e^post(t) *(Layer 2, planned)*
- **Eq. 3** — Generalized edge cost c_e(t) with σ, κ, CO₂, transfer penalties *(Layer 3, planned)*
- **σ × κ weighted score** — current Layer 1 proxy for disruption signal strength

---

## License

MIT
