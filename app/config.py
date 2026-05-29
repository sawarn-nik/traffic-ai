import os
from dotenv import load_dotenv

load_dotenv()

# ── LLM ──────────────────────────────────────────────────────────────────────
# Backends: "openrouter" (default) | "gemini" | "ollama"
LLM_BACKEND = os.getenv("LLM_BACKEND", "openrouter")

# OpenRouter — free tier, OpenAI-compatible, 300+ models
# Get key at: https://openrouter.ai/keys  (free, no credit card)
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Free models — availability varies by time of day, swap via .env:
#   openai/gpt-oss-20b:free                  ← reliable, good JSON (current default)
#   nvidia/nemotron-3-super-120b-a12b:free   ← 120B, high quality
#   meta-llama/llama-3.3-70b-instruct:free   ← best when not rate-limited
#   deepseek/deepseek-v4-flash:free          ← fastest, 1M context
OPENROUTER_MODEL = os.getenv(
    "OPENROUTER_MODEL",
    "openai/gpt-oss-20b:free"
)

# Gemini — fallback if OpenRouter key not set
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

# Ollama — local offline fallback
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "phi3")

# ── News / RSS ────────────────────────────────────────────────────────────────
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")
NEWS_PAGE_SIZE = int(os.getenv("NEWS_PAGE_SIZE", "3"))

# ── Twitter / X ───────────────────────────────────────────────────────────────
TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN", "")

# ── Routing ───────────────────────────────────────────────────────────────────
DEFAULT_CITY = os.getenv("DEFAULT_CITY", "Kolkata, India")
GRAPH_CACHE_PATH = os.getenv("GRAPH_CACHE_PATH", "cache/graph.graphml")

# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///traffic_events.db")

# ── Scoring ───────────────────────────────────────────────────────────────────
SEVERITY_SCORES = {"low": 2, "medium": 5, "high": 10}
DEFAULT_SCORE = 1
