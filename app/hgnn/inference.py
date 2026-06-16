"""
inference.py — Online HGNN inference for live traffic scoring
=============================================================
Called during /api/disruptions after LLM extraction is complete.

Returns:
  - per-road disruption probability       → improves route scoring
  - per-event adjusted confidence score   → improves event confidence

Graceful degradation:
  If torch is not installed, or the model weights file doesn't exist yet,
  inference returns None and the caller falls back to rule-based scoring.
  This means the system ALWAYS works, even without a trained model.

Usage:
  from hgnn.inference import HGNNInference

  # Create once (loads model into memory)
  hgnn = HGNNInference()

  # Call per request
  result = hgnn.predict(events, route_road_names)
  if result:
      road_probs  = result["road_disruption_probs"]   # dict: road_name → prob
      event_confs = result["event_confidence_adj"]     # list of floats, same order as events
"""

from __future__ import annotations

import os
from typing import Optional

DEFAULT_WEIGHTS_PATH = os.path.join(os.path.dirname(__file__), "weights", "model.pt")


class HGNNInference:
    """
    Stateful HGNN inference wrapper. Instantiate once per server process.

    The model is loaded lazily on first call to predict() to avoid slowing
    down server startup.
    """

    def __init__(self, weights_path: str = DEFAULT_WEIGHTS_PATH):
        self.weights_path = weights_path
        self._model       = None
        self._ready       = False
        self._torch_ok    = False

        # Check torch availability once at init time
        try:
            import torch  # noqa: F401
            self._torch_ok = True
        except ImportError:
            pass

    def _load_model(self) -> bool:
        """
        Lazy model load. Returns True if model loaded successfully.
        Called on first predict() invocation.
        """
        if not self._torch_ok:
            return False

        if not os.path.exists(self.weights_path):
            print(f"  [HGNN] No weights file at {self.weights_path}. "
                  f"Run 'python -m hgnn.trainer' to train first. "
                  f"Using rule-based scoring fallback.")
            return False

        try:
            import torch
            from hgnn.model import build_model

            model = build_model()
            state = torch.load(self.weights_path, map_location="cpu",
                               weights_only=True)
            model.load_state_dict(state)
            model.eval()

            self._model  = model
            self._ready  = True
            print(f"  [HGNN] Model loaded from {self.weights_path}")
            return True

        except Exception as e:
            print(f"  [HGNN] WARNING: Failed to load model weights: {e}. "
                  f"Using rule-based scoring fallback.")
            return False

    def is_ready(self) -> bool:
        """True if the model is loaded and ready for inference."""
        return self._ready

    def predict(
        self,
        events:           list[dict],
        route_road_names: list[str],
    ) -> Optional[dict]:
        """
        Run HGNN inference on a set of extracted traffic events.

        Args:
            events:           List of event dicts from _process_articles()
            route_road_names: Road names on the current route

        Returns:
            dict with keys:
              road_disruption_probs  : dict[road_name, float]  ∈ [0, 1]
              event_confidence_adj   : list[float]  (same order as input events)
              n_road_nodes           : int
              n_event_nodes          : int
            or None if model is unavailable / inference failed.
        """
        # Lazy load on first call
        if not self._ready:
            if not self._load_model():
                return None

        if not events:
            return None

        try:
            import torch
            from hgnn.graph_builder import build_graph_from_events
            import numpy as np

            graph_data, meta = build_graph_from_events(events, route_road_names)

            # Convert to tensors
            def _t(arr: "np.ndarray", dtype=torch.float32):
                return torch.from_numpy(arr).to(dtype)

            road_x     = _t(graph_data["road_x"])
            event_x    = _t(graph_data["event_x"])
            source_x   = _t(graph_data["source_x"])
            location_x = _t(graph_data["location_x"])

            def _ei(arr: "np.ndarray"):
                if arr.shape[1] == 0:
                    return torch.zeros((2, 0), dtype=torch.long)
                return torch.from_numpy(arr).long()

            edge_ev_road = _ei(graph_data["edge_ev_affects_road"])
            edge_ev_src  = _ei(graph_data["edge_ev_reported_by_src"])
            edge_ev_loc  = _ei(graph_data["edge_ev_located_at_loc"])
            edge_rr      = _ei(graph_data["edge_road_near_road"])

            with torch.no_grad():
                road_prob, event_conf, sev_logits = self._model(
                    road_x     = road_x,
                    event_x    = event_x,
                    source_x   = source_x,
                    location_x = location_x,
                    edge_ev_affects_road    = edge_ev_road,
                    edge_ev_reported_by_src = edge_ev_src,
                    edge_ev_located_at_loc  = edge_ev_loc,
                    edge_road_near_road     = edge_rr,
                )

            # Severity probabilities from logits
            sev_probs = torch.softmax(sev_logits, dim=-1)   # (N_event, 3)
            sev_preds = sev_probs.argmax(dim=-1).tolist()   # 0=low,1=med,2=high
            SEV_LABELS = ["low", "medium", "high"]

            # Map road index → road name
            road_ids   = meta["road_ids"]
            idx_to_road = {v: k for k, v in road_ids.items()}

            road_probs_dict = {
                idx_to_road[i]: float(road_prob[i])
                for i in range(len(road_prob))
                if i in idx_to_road
            }

            event_conf_list = event_conf.tolist()
            sev_probs_list  = sev_probs.tolist()   # list of [p_low, p_med, p_high]

            return {
                "road_disruption_probs":  road_probs_dict,
                "event_confidence_adj":   event_conf_list,
                "event_severity_probs":   sev_probs_list,
                "event_severity_preds":   [SEV_LABELS[s] for s in sev_preds],
                "n_road_nodes":           graph_data["n_roads"],
                "n_event_nodes":          graph_data["n_events"],
            }

        except Exception as e:
            print(f"  [HGNN] Inference error: {e}. Falling back to rule-based scoring.")
            return None


# ── Module-level singleton (shared across requests) ───────────────────────────

_default_inference: Optional[HGNNInference] = None


def get_inference(weights_path: str = DEFAULT_WEIGHTS_PATH) -> HGNNInference:
    """
    Return the module-level HGNNInference singleton.
    Safe to call from multiple API requests — the model is loaded once.
    """
    global _default_inference
    if _default_inference is None:
        _default_inference = HGNNInference(weights_path=weights_path)
    return _default_inference
