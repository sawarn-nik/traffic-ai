"""
Layer 3 — Generalized Edge Cost Function
=========================================
STATUS: Placeholder — implementation assigned to Layer 3 team member.

Goal:
    Implement Equation 3 from the proposal — a multi-criteria edge cost
    that combines travel time, reliability, disruption risk, emissions,
    and transfer penalties.

Equation 3:

    c_e(t) = c_base(t)
           + λ1 · E[τ̃_e(t)]          ← expected travel time
           + λ2 · Var[τ̃_e(t)]         ← travel time variability (reliability)
           + λ3 · κ_e(t) · σ_e(t)     ← disruption risk (from Layer 1)
           + λ4 · CO2(e)               ← emissions per edge
           + λ5 · Transfers(e)         ← mode-switch penalty

Where:
    c_base(t)   — scheduled travel time / fare from GTFS
    τ̃_e(t)     — random travel time (mixture of nominal + disruption distributions)
    κ_e(t)     — LLM confidence score (Layer 1)
    σ_e(t)     — LLM severity score (Layer 1)
    CO2(e)     — estimated CO2 emissions for this edge/mode
    Transfers  — number of mode switches on this edge

λ weights are user-configurable (risk-averse vs time-optimal vs eco).

See CONTRIBUTING.md §8 for full implementation spec.
"""

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class EdgeCostWeights:
    """User preference weights for the generalized cost function."""
    lambda1: float = 1.0   # expected travel time
    lambda2: float = 0.5   # travel time variance (reliability)
    lambda3: float = 1.0   # disruption risk
    lambda4: float = 0.2   # CO2 emissions
    lambda5: float = 2.0   # transfer penalty (minutes equivalent)


def compute_edge_cost(
    c_base: float,
    expected_travel_time: float,
    travel_time_variance: float,
    disruption_risk: float,       # κ × σ from Layer 1/2
    co2_emissions: float,
    transfer_penalty: float,
    weights: EdgeCostWeights | None = None,
) -> float:
    """
    Placeholder: compute generalized cost for one edge.

    Args:
        c_base:               Base cost (scheduled time or fare)
        expected_travel_time: E[τ̃_e(t)]
        travel_time_variance: Var[τ̃_e(t)]
        disruption_risk:      κ_e(t) × σ_e(t) from Layer 1
        co2_emissions:        CO2(e) in grams
        transfer_penalty:     Transfers(e) count
        weights:              λ preference weights

    Returns:
        Scalar generalized edge cost c_e(t)

    TODO: Implement full cost function with travel time distributions.
    """
    raise NotImplementedError(
        "Layer 3 cost function not yet implemented. "
        "See CONTRIBUTING.md §8 for the spec."
    )
