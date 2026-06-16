"""
Layer 2 — Bayesian Probabilistic Data Fusion
=============================================
Combines Layer 1 LLM-derived disruption signals (σ, κ) with the HGNN-learned
road disruption probabilities to compute a posterior disruption probability
per road edge.

Equation 1 from the proposal:

    π_e^post(t) = p(S | Z_e=1) × π_e^prior(t)
                  ─────────────────────────────
                  Σ_{z=0}^{1} p(S | Z_e=z) × π_e^prior(t)

Implementation:
  - Prior  π_e^prior  : time-of-day baseline + historical average from DB
  - Signal p(S|Z=1)   : Layer 1 confidence κ × severity σ (normalised)
                        + HGNN road disruption probability (if available)
  - Output π_e^post   : posterior disruption probability ∈ [0, 1]

This module is used by route_engine and cost_function (Layer 3).
"""

from __future__ import annotations

from typing import Optional


# ── Time-of-day prior baselines (Kolkata empirical estimates) ─────────────────
# Higher during rush hours, lower at night
# Keys: hour of day (0–23), values: baseline disruption probability

_TIME_OF_DAY_PRIOR: dict[int, float] = {
    0: 0.02,  1: 0.02,  2: 0.01,  3: 0.01,
    4: 0.02,  5: 0.03,  6: 0.06,  7: 0.12,
    8: 0.18,  9: 0.20,  10: 0.15, 11: 0.12,
    12: 0.12, 13: 0.13, 14: 0.12, 15: 0.13,
    16: 0.15, 17: 0.20, 18: 0.22, 19: 0.18,
    20: 0.14, 21: 0.10, 22: 0.06, 23: 0.03,
}

# Severity σ normalised to likelihood ratio p(S|Z=1) / p(S|Z=0)
# Interpretation: how much more likely is this signal given disruption vs no disruption
_SEVERITY_LIKELIHOOD_RATIO: dict[str, float] = {
    "high":   8.0,
    "medium": 4.0,
    "low":    2.0,
}

# HGNN probability blend weight in the posterior update
# 0.0 = ignore HGNN, 1.0 = use only HGNN
_W_HGNN = 0.30


def _get_time_prior(hour: Optional[int] = None) -> float:
    """Return the baseline prior disruption probability for the given hour."""
    if hour is None:
        from datetime import datetime
        hour = datetime.now().hour
    return _TIME_OF_DAY_PRIOR.get(hour % 24, 0.10)


def compute_posterior(
    road_name:      str,
    severity_score: int,
    confidence:     float,
    prior:          float = 0.1,
    hgnn_prob:      Optional[float] = None,
    hour:           Optional[int] = None,
) -> float:
    """
    Compute posterior disruption probability for one road edge.

    Implements Equation 1 from the proposal using a simplified Bayesian update:

        likelihood_ratio = severity_likelihood × confidence
        prior = time_of_day_prior (if prior not overridden)
        posterior = (lr × prior) / (lr × prior + (1 - prior))

    Then optionally blended with HGNN road probability.

    Args:
        road_name:      Road segment identifier (used for logging)
        severity_score: σ ∈ {2, 5, 10} from Layer 1
        confidence:     κ ∈ [0, 1] from Layer 1
        prior:          π_prior — override baseline; 0.0 = use time-of-day baseline
        hgnn_prob:      HGNN-learned road disruption probability (optional)
        hour:           Hour of day 0–23 for time-of-day prior (None = current hour)

    Returns:
        Posterior probability π_post ∈ [0, 1]
    """
    # Map severity score to label for likelihood lookup
    if severity_score >= 10:
        sev_label = "high"
    elif severity_score >= 5:
        sev_label = "medium"
    else:
        sev_label = "low"

    # Use time-of-day baseline if prior not explicitly provided
    if prior <= 0.0:
        prior = _get_time_prior(hour)

    prior = max(0.001, min(0.999, prior))   # avoid divide by zero

    # Likelihood ratio: how much does this signal increase disruption probability
    base_lr = _SEVERITY_LIKELIHOOD_RATIO.get(sev_label, 2.0)
    # Scale by confidence κ — high confidence amplifies the signal
    likelihood_ratio = base_lr * max(0.1, confidence)

    # Bayesian update (log-odds form for numerical stability)
    # posterior = lr * prior / (lr * prior + (1 - prior))
    numerator   = likelihood_ratio * prior
    denominator = numerator + (1.0 - prior)
    posterior   = numerator / denominator if denominator > 0 else prior

    # Blend with HGNN probability if available
    if hgnn_prob is not None:
        hgnn_prob = max(0.0, min(1.0, float(hgnn_prob)))
        posterior = (1.0 - _W_HGNN) * posterior + _W_HGNN * hgnn_prob

    return round(max(0.0, min(1.0, posterior)), 4)


def fuse_route_disruptions(
    road_names:  list[str],
    events:      Optional[list[dict]] = None,
    hour:        Optional[int] = None,
) -> dict[str, float]:
    """
    Compute posterior disruption probabilities for all edges on a route.

    Args:
        road_names: List of road segment names from the route engine
        events:     Extracted event dicts (from Layer 1). If None, queries DB.
        hour:       Hour of day for time-of-day prior (None = current hour)

    Returns:
        Dict mapping road_name → posterior π_post ∈ [0, 1]
    """
    if not road_names:
        return {}

    # ── Gather Layer 1 signals per road ──────────────────────────────────────
    road_signals: dict[str, list[tuple[int, float]]] = {r: [] for r in road_names}

    if events:
        # Use live events from the current extraction run
        for ev in events:
            road = ev.get("road_name") or ev.get("location") or ""
            for route_road in road_names:
                if (route_road.lower() in road.lower()
                        or road.lower() in route_road.lower()):
                    sev_score = ev.get("severity_score", 2)
                    conf      = ev.get("confidence", 0.5)
                    road_signals[route_road].append((sev_score, conf))
    else:
        # Fall back to DB query
        try:
            from config import DATABASE_URL
            from sqlalchemy import create_engine, text

            engine = create_engine(DATABASE_URL, echo=False)
            with engine.connect() as conn:
                for road in road_names:
                    like_pattern = f"%{road.lower()}%"
                    rows = conn.execute(text("""
                        SELECT severity_score, confidence
                        FROM traffic_events
                        WHERE (LOWER(road_name) LIKE :pat OR LOWER(location) LIKE :pat)
                          AND fetched_at > datetime('now', '-2 days')
                        ORDER BY fetched_at DESC
                        LIMIT 10
                    """), {"pat": like_pattern}).fetchall()

                    for row in rows:
                        road_signals[road].append((int(row[0] or 2), float(row[1] or 0.5)))
        except Exception as e:
            print(f"  [BayesianFusion] DB query failed: {e}. Using priors only.")

    # ── Try to get HGNN road probabilities ────────────────────────────────────
    hgnn_probs: dict[str, float] = {}
    if events:
        try:
            from hgnn.inference import get_inference
            hgnn = get_inference()
            result = hgnn.predict(events or [], road_names)
            if result:
                hgnn_probs = result.get("road_disruption_probs", {})
        except Exception:
            pass  # HGNN unavailable — proceed with rule-based only

    # ── Compute posterior per road ────────────────────────────────────────────
    posteriors: dict[str, float] = {}

    for road in road_names:
        signals = road_signals.get(road, [])
        hgnn_p  = hgnn_probs.get(road.lower())

        if not signals:
            # No events for this road — use time-of-day prior only
            prior_only = _get_time_prior(hour)
            if hgnn_p is not None:
                prior_only = (1.0 - _W_HGNN) * prior_only + _W_HGNN * hgnn_p
            posteriors[road] = round(prior_only, 4)
            continue

        # Combine multiple signals: take the max posterior across events
        # (conservative: if any signal says disrupted, treat road as disrupted)
        road_posterior = max(
            compute_posterior(
                road_name      = road,
                severity_score = sev,
                confidence     = conf,
                prior          = 0.0,   # use time-of-day baseline
                hgnn_prob      = hgnn_p,
                hour           = hour,
            )
            for sev, conf in signals
        )
        posteriors[road] = road_posterior

    return posteriors


def get_route_disruption_summary(
    road_names: list[str],
    events:     Optional[list[dict]] = None,
    hour:       Optional[int] = None,
) -> dict:
    """
    High-level summary of route disruption from Bayesian fusion.

    Returns:
        {
          posteriors:       dict road_name → π_post
          avg_posterior:    float — mean disruption probability across route
          max_posterior:    float — highest single-road probability
          high_risk_roads:  list of road names with π_post > 0.5
          fusion_score:     float ∈ [0, 10] — same scale as disruption_score
        }
    """
    posteriors = fuse_route_disruptions(road_names, events=events, hour=hour)

    if not posteriors:
        return {
            "posteriors":      {},
            "avg_posterior":   0.0,
            "max_posterior":   0.0,
            "high_risk_roads": [],
            "fusion_score":    0.0,
        }

    values         = list(posteriors.values())
    avg_posterior  = sum(values) / len(values)
    max_posterior  = max(values)
    high_risk      = [r for r, p in posteriors.items() if p >= 0.5]

    # Scale avg posterior to risk score (0–10)
    fusion_score = round(avg_posterior * 10.0, 3)

    return {
        "posteriors":      posteriors,
        "avg_posterior":   round(avg_posterior, 4),
        "max_posterior":   round(max_posterior, 4),
        "high_risk_roads": high_risk,
        "fusion_score":    fusion_score,
    }
