from config import SEVERITY_SCORES, DEFAULT_SCORE


def compute_score(severity: str) -> int:
    """
    Map a severity label to a numeric congestion score.

    low    → 2
    medium → 5
    high   → 10
    """
    return SEVERITY_SCORES.get(severity.lower().strip(), DEFAULT_SCORE)


def compute_weighted_score(severity: str, confidence: float) -> float:
    """
    Weighted score = severity_score × confidence (κ).

    This gives a single scalar that reflects both how bad the disruption is
    and how much we trust the LLM's extraction — directly usable as an
    input signal for the Bayesian fusion layer (Layer 2).

    Example:
        severity="high", confidence=0.9  →  10 × 0.9 = 9.0
        severity="medium", confidence=0.4 →  5 × 0.4 = 2.0
    """
    base = compute_score(severity)
    return round(base * max(0.0, min(1.0, confidence)), 4)
