"""
trainer.py — Training loop for Temporal TrafficHGNN (V2)
=========================================================
Three training objectives:
  1. Road disruption regression   (MSE) — predicts P(disruption) per road
  2. Event confidence regression  (MSE) — replicates + improves rule-based conf
  3. Event severity classification (CrossEntropy) — predicts low/medium/high
                                                     from graph context

Loss = MSE_road + MSE_conf + 0.5 × CE_severity

HOW TO RUN:
  cd app
  python -m hgnn.trainer
  python -m hgnn.trainer --epochs 120 --lr 0.0005
"""

from __future__ import annotations

import os
import time
from typing import Optional

DEFAULT_WEIGHTS_DIR  = os.path.join(os.path.dirname(__file__), "weights")
DEFAULT_WEIGHTS_PATH = os.path.join(DEFAULT_WEIGHTS_DIR, "model.pt")

DEFAULT_EPOCHS = 100
DEFAULT_LR     = 1e-3
DEFAULT_WD     = 1e-4
PATIENCE       = 20

# Loss weights
W_ROAD  = 1.0   # road disruption regression
W_CONF  = 1.0   # event confidence regression
W_SEV   = 0.5   # severity classification


def _to_tensors(graph_data: dict) -> dict:
    import torch, numpy as np
    out = {}
    for k, v in graph_data.items():
        if isinstance(v, np.ndarray):
            out[k] = torch.from_numpy(v).long() if v.dtype == np.int64 else torch.from_numpy(v).float()
        else:
            out[k] = v
    return out


def _build_targets(graph_data: dict):
    import torch
    road_target  = torch.from_numpy(graph_data["road_x"][:, 0]).float()   # avg_sev proxy
    event_target = torch.from_numpy(graph_data["event_x"][:, 1]).float()  # confidence
    sev_target   = torch.from_numpy(graph_data["event_sev_labels"]).long() # 0/1/2
    return road_target, event_target, sev_target


def train(
    epochs:    int   = DEFAULT_EPOCHS,
    lr:        float = DEFAULT_LR,
    wd:        float = DEFAULT_WD,
    save_path: str   = DEFAULT_WEIGHTS_PATH,
    db_url:    Optional[str] = None,
    verbose:   bool  = True,
) -> dict:
    try:
        import torch
        import torch.nn as nn
    except ImportError:
        raise ImportError("PyTorch required. pip install torch")

    from hgnn.graph_builder import build_graph_from_db
    from hgnn.model import build_model

    if verbose:
        print("  [HGNN] Building graph from DB ...")

    graph_data, meta = build_graph_from_db(route_road_names=[], db_url=db_url)
    n_events = graph_data["n_events"]
    n_roads  = graph_data["n_roads"]

    if n_events < 10:
        print(f"  [HGNN] WARNING: only {n_events} events. Train after ≥200.")

    if verbose:
        print(f"  [HGNN] Graph: {n_roads} roads, {n_events} events, "
              f"{graph_data['n_sources']} sources, {graph_data['n_locations']} locations")
        print(f"  [HGNN] Event features: {graph_data['event_x'].shape[1]} dims "
              f"(+temporal encoding vs V1)")

    tensors = _to_tensors(graph_data)
    road_target, event_target, sev_target = _build_targets(graph_data)

    model     = build_model()
    optimiser = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=wd)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimiser, patience=8, factor=0.5, min_lr=1e-5
    )

    mse_fn = nn.MSELoss()
    ce_fn  = nn.CrossEntropyLoss()

    best_loss   = float("inf")
    patience_ct = 0
    history     = {}

    os.makedirs(os.path.dirname(save_path), exist_ok=True)

    if verbose:
        print(f"  [HGNN] Training for up to {epochs} epochs "
              f"(3 objectives: road_MSE + conf_MSE + sev_CE) ...")

    model.train()
    t0 = time.time()

    for epoch in range(1, epochs + 1):
        optimiser.zero_grad()

        road_prob, event_conf, sev_logits = model(
            road_x     = tensors["road_x"],
            event_x    = tensors["event_x"],
            source_x   = tensors["source_x"],
            location_x = tensors["location_x"],
            edge_ev_affects_road    = tensors["edge_ev_affects_road"],
            edge_ev_reported_by_src = tensors["edge_ev_reported_by_src"],
            edge_ev_located_at_loc  = tensors["edge_ev_located_at_loc"],
            edge_road_near_road     = tensors["edge_road_near_road"],
        )

        loss_road = mse_fn(road_prob,   road_target)  if road_target.numel()  > 0 else torch.tensor(0.0)
        loss_conf = mse_fn(event_conf,  event_target) if event_target.numel() > 0 else torch.tensor(0.0)
        loss_sev  = ce_fn(sev_logits,   sev_target)   if sev_target.numel()   > 0 else torch.tensor(0.0)

        loss = W_ROAD * loss_road + W_CONF * loss_conf + W_SEV * loss_sev
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
        optimiser.step()
        scheduler.step(loss)

        epoch_loss = loss.item()
        history[epoch] = {
            "total": epoch_loss,
            "road":  loss_road.item(),
            "conf":  loss_conf.item(),
            "sev":   loss_sev.item(),
        }

        if epoch_loss < best_loss - 1e-5:
            best_loss   = epoch_loss
            patience_ct = 0
            torch.save(model.state_dict(), save_path)
        else:
            patience_ct += 1

        if verbose and (epoch % 10 == 0 or epoch == 1):
            elapsed = time.time() - t0
            print(f"  [HGNN] Epoch {epoch:4d}/{epochs}  "
                  f"loss={epoch_loss:.5f}  "
                  f"(road={loss_road.item():.4f} conf={loss_conf.item():.4f} "
                  f"sev={loss_sev.item():.4f})  best={best_loss:.5f}  "
                  f"({elapsed:.1f}s)")

        if patience_ct >= PATIENCE:
            if verbose:
                print(f"  [HGNN] Early stop at epoch {epoch}.")
            break

    if verbose:
        print(f"  [HGNN] Done. Best loss={best_loss:.5f}  "
              f"Saved → {save_path}  ({time.time()-t0:.1f}s)")

    return history


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--epochs",    type=int,   default=DEFAULT_EPOCHS)
    p.add_argument("--lr",        type=float, default=DEFAULT_LR)
    p.add_argument("--save-path", type=str,   default=DEFAULT_WEIGHTS_PATH)
    p.add_argument("--db-url",    type=str,   default=None)
    args = p.parse_args()
    train(epochs=args.epochs, lr=args.lr,
          save_path=args.save_path, db_url=args.db_url)
