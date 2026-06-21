# Multimodal Transportation System – Current Status and Planned Bus Integration

## Existing System (After Recent Updates)

The application has evolved from a road-route planner into a multimodal transportation intelligence platform.

### Route Planning Modes Available

* Drive
* Walk
* Bike
* Metro
* Metro + Walk
* Metro + Bike
* Metro + Drive

### Metro Integration Added

A complete metro network layer has been integrated into the system.

Key capabilities include:

* Metro station database with geographic coordinates.
* Metro line representation as a graph network.
* Metro route discovery using graph traversal.
* Metro timetable support.
* Metro overlay visualization on the map.
* Multimodal routing using metro as an intermediate transport mode.

Example:

User: Howrah → Park Street

System can generate:

Walk → Metro → Walk

instead of relying entirely on road transport.

### Existing Intelligence Layers

The system currently incorporates:

#### Traffic Intelligence

* Route disruptions
* News-based transportation events
* Confidence scoring

#### Weather Intelligence

* Route sampling
* Weather collection at sampled route points
* Weather Risk Score (WSI)
* Route-level weather severity estimation

#### Geospatial Intelligence

* OpenStreetMap
* OSRM routing
* Route geometry analysis

---

# Planned Contribution: Bus Transit Integration

The next objective is to extend the multimodal framework beyond metro and road transportation.

## Motivation

Many Kolkata locations are not directly connected by metro.

In real-world travel:

* Users frequently combine buses and metro.
* Buses provide first-mile and last-mile connectivity.
* Bus routes often remain viable when road congestion affects private vehicles.

Therefore, bus transportation should become a first-class routing mode within the system.

---

# Proposed Architecture

## Transit Module

```text
app/
 └── transit/
      ├── data/
      │    ├── bus_stops.json
      │    └── bus_routes.json
      │
      ├── bus_graph.py
      ├── bus_engine.py
      ├── bus_overlay.py
      └── __init__.py
```

---

# Phase 1 – Bus Network Modelling

## Bus Stops Dataset

Create a structured database of major Kolkata bus stops.

For each stop:

* Stop ID
* Stop Name
* Latitude
* Longitude

Example:

Howrah Station
Esplanade
Park Street
Sealdah
Salt Lake Sector V
Airport
Garia

---

## Bus Route Dataset

Create route definitions containing:

* Route Number
* Route Type
* Ordered Stop Sequence

Example:

AC12

Howrah
→ Esplanade
→ Park Street
→ Garia

---

# Phase 2 – Bus Graph Construction

Represent the bus network as a graph.

### Nodes

Bus Stops

### Edges

Connections between consecutive stops

Example:

Howrah → Esplanade

Esplanade → Park Street

Park Street → Garia

This allows graph-based route search similar to the existing metro network.

---

# Phase 3 – Bus Overlay Visualization

Add bus layers to the map.

Capabilities:

* Display bus stops.
* Display major bus corridors.
* Show route information through map interaction.

This provides immediate visual integration with the existing multimodal interface.

---

# Phase 4 – Unified Multimodal Routing

Future goal:

Combine:

* Road Network
* Metro Network
* Bus Network
* Walking Network

into a unified transportation graph.

Example:

User: Howrah → New Town

Possible recommendation:

Walk
→ Bus
→ Metro
→ Walk

or

Bus
→ Metro
→ Bus

depending on:

* Traffic disruptions
* Weather conditions
* Metro availability
* Bus availability
* Estimated travel time

---

# Long-Term Vision

Develop a Contextual Probabilistic AI-Enabled Multimodal Trip Planning System capable of recommending transportation strategies rather than only road routes.

The system should intelligently choose among:

* Car
* Bike
* Walk
* Metro
* Bus
* Hybrid multimodal journeys

based on real-time contextual information and transportation network conditions.
