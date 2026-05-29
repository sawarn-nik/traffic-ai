"""
LangChain-based event extractor with retry + empty-response handling.

Fixes applied vs v1:
  1. Exponential backoff retry on 429 rate-limit errors (up to MAX_RETRIES).
  2. Empty structured-output guard — if the model returns a parsed=None
     response (a known quirk of some free OpenRouter models), the extractor
     falls back to the PydanticOutputParser chain instead of crashing.
  3. Chain is reset after a 429 so the next call gets a fresh connection.
"""

import time
import re

from langchain_core.output_parsers import PydanticOutputParser

from llm.prompts import TRAFFIC_PROMPT
from llm.schema import TrafficEventSchema
from config import (
    OPENROUTER_API_KEY, OPENROUTER_BASE_URL, OPENROUTER_MODEL,
    GEMINI_API_KEY, GEMINI_MODEL,
)

# ── Retry config ──────────────────────────────────────────────────────────────
MAX_RETRIES    = 4       # total attempts per article
BASE_DELAY     = 5.0     # seconds before first retry
BACKOFF_FACTOR = 2.0     # delay doubles each retry: 5s, 10s, 20s, 40s

# ── Shared parser (for format_instructions injection into the prompt) ─────────
_parser = PydanticOutputParser(pydantic_object=TrafficEventSchema)


# ── Model builders ────────────────────────────────────────────────────────────

def _build_openrouter_model():
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=OPENROUTER_MODEL,
        openai_api_key=OPENROUTER_API_KEY,
        openai_api_base=OPENROUTER_BASE_URL,
        temperature=0.1,
        max_tokens=512,
        default_headers={"X-Title": "traffic-ai-layer1"},
    )


def _build_gemini_model():
    from langchain_google_genai import ChatGoogleGenerativeAI
    return ChatGoogleGenerativeAI(
        model=GEMINI_MODEL,
        google_api_key=GEMINI_API_KEY,
        temperature=0.1,
    )


def _get_model():
    if OPENROUTER_API_KEY:
        try:
            return _build_openrouter_model()
        except Exception as e:
            print(f"[Extractor] OpenRouter init failed: {e}")
    if GEMINI_API_KEY:
        try:
            return _build_gemini_model()
        except Exception as e:
            print(f"[Extractor] Gemini init failed: {e}")
    raise RuntimeError(
        "No LLM backend available. "
        "Set OPENROUTER_API_KEY or GEMINI_API_KEY in your .env file."
    )


# ── Chain builder ─────────────────────────────────────────────────────────────

def _build_chain():
    """
    Build the primary LCEL chain:
        prompt | model.with_structured_output(TrafficEventSchema)

    Also builds a fallback chain using PydanticOutputParser for models
    that don't support native structured output.
    """
    model = _get_model()

    try:
        structured_model = model.with_structured_output(TrafficEventSchema)
        primary  = TRAFFIC_PROMPT | structured_model
        fallback = TRAFFIC_PROMPT | model | _parser
        print("[Extractor] Using structured output mode (with parser fallback)")
        return primary, fallback
    except Exception:
        fallback = TRAFFIC_PROMPT | model | _parser
        print("[Extractor] Using parser-only mode")
        return fallback, fallback


# Lazy-init — chains built once on first call, reset after hard failures
_primary_chain  = None
_fallback_chain = None


def _get_chains():
    global _primary_chain, _fallback_chain
    if _primary_chain is None:
        _primary_chain, _fallback_chain = _build_chain()
    return _primary_chain, _fallback_chain


def _reset_chains():
    """Force chain rebuild on next call (used after connection errors)."""
    global _primary_chain, _fallback_chain
    _primary_chain  = None
    _fallback_chain = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_rate_limit_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "429" in msg or "rate" in msg or "rate-limited" in msg


def _is_empty_response(exc: Exception) -> bool:
    """
    Detect the 'parsed=None / no parsed field' quirk from some free models
    that return an empty tool-call response instead of a proper refusal.
    """
    msg = str(exc)
    return "parsed" in msg and ("NoneType" in msg or "'parsed' field" in msg)


def _invoke_with_format(chain) -> TrafficEventSchema:
    return chain.invoke({
        "text": _current_text,
        "format_instructions": _parser.get_format_instructions(),
    })


# Module-level text holder so helpers can access it without passing args
_current_text: str = ""


# ── Public API ────────────────────────────────────────────────────────────────

def extract_event(text: str) -> TrafficEventSchema | None:
    """
    Extract a structured traffic disruption event from article text.

    Retries up to MAX_RETRIES times with exponential backoff on 429 errors.
    Falls back to the PydanticOutputParser chain on empty structured-output
    responses.

    Args:
        text: Raw article title + description combined.

    Returns:
        A validated TrafficEventSchema object, or None on failure.
    """
    global _current_text
    if not text.strip():
        return None

    _current_text = text
    primary, fallback = _get_chains()
    payload = {
        "text": text,
        "format_instructions": _parser.get_format_instructions(),
    }

    delay = BASE_DELAY

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = primary.invoke(payload)

            # Guard: some free models return a non-None object with parsed=None
            if result is None:
                raise ValueError("Primary chain returned None — trying fallback")

            return result

        except Exception as e:
            err_str = str(e)

            # ── Empty structured-output response → try fallback chain ─────────
            if _is_empty_response(e):
                print(f"[Extractor] Empty structured output — trying parser fallback")
                try:
                    result = fallback.invoke(payload)
                    if result is not None:
                        return result
                except Exception as fe:
                    print(f"[Extractor] Fallback also failed: {fe}")
                return None

            # ── Rate limit → wait and retry ───────────────────────────────────
            if _is_rate_limit_error(e):
                if attempt < MAX_RETRIES:
                    print(f"[Extractor] Rate limited (429) — "
                          f"waiting {delay:.0f}s before retry "
                          f"({attempt}/{MAX_RETRIES - 1}) ...")
                    time.sleep(delay)
                    delay *= BACKOFF_FACTOR
                    continue
                else:
                    print(f"[Extractor] Rate limit persists after "
                          f"{MAX_RETRIES} attempts — skipping article")
                    return None

            # ── Connection error → reset chain and retry once ─────────────────
            if "connection" in err_str.lower() and attempt == 1:
                print(f"[Extractor] Connection error — resetting chain and retrying")
                _reset_chains()
                primary, fallback = _get_chains()
                time.sleep(2.0)
                continue

            # ── Any other error → log and give up ────────────────────────────
            print(f"[Extractor] Extraction failed: {e}")
            return None

    return None
