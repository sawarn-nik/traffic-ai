"""
hgnn/ — Heterogeneous Graph Neural Network for traffic disruption scoring
=========================================================================
Provides:
  graph_builder.py  — builds a HeteroData graph from DB events + OSM road network
  model.py          — HAN-based HGNN model definition
  trainer.py        — offline training / fine-tuning loop
  inference.py      — online inference: returns per-edge disruption scores
  integration.py    — drop-in helpers that plug into existing scoring pipeline
"""
