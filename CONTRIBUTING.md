# Contributing to traffic-ai

This document is for the 4-person team working on this project.  
Read it once before you write a single line of code.

---

## 1. Branch strategy

```
main
 └── dev                              ← everyone merges into here
      ├── feature/layer2-bayesian-fusion
      ├── feature/layer3-routing
      ├── feature/ui-dashboard
      └── fix/some-bug-description
```

**Rules:**
- `main` is protected. No direct pushes. Only merges from `dev` after review.
- `dev` is the shared integration branch. All feature branches branch off `dev`.
- Never work directly on `main` or `dev`.
- Branch names: `feature/short-description` or `fix/short-description`.

---

## 2. Daily workflow

```bash
# Start of day — sync your branch with latest dev
git checkout dev
git pull origin dev
git checkout your-feature-branch
git rebase dev                  # keeps history clean

# Work, commit often with clear messages
git add app/llm/extractor.py
git commit -m "feat(extractor): add exponential backoff on 429 errors"

# Push and open a PR into dev (not main)
git push origin your-feature-branch
```

---

## 3. Commit message format

Use this format — it makes the git log readable for everyone:

```
type(scope): short description

Optional longer explanation if needed.
```

| Type | When to use |
|------|-------------|
| `feat` | New feature or capability |
| `fix` | Bug fix |
| `refactor` | Code restructure, no behaviour change |
| `docs` | README, comments, docstrings |
| `test` | Adding or fixing tests |
| `chore` | Dependency updates, config changes |

**Examples:**
```
feat(rss_fetcher): add Kolkata Police feed and age-label parsing
fix(extractor): handle empty structured-output response from gpt-oss-20b
docs(readme): add quickstart section
refactor(route_engine): extract geocoding into _geocode_with_context()
```

---

## 4. Pull request checklist

Before opening a PR into `dev`:

- [ ] Code runs without errors (`python3 app/main.py`)
- [ ] No API keys or secrets in any file
- [ ] `.env` is NOT committed (check `git status`)
- [ ] New functions have docstrings
- [ ] PR description explains *what* changed and *why*
- [ ] At least one other team member reviews before merge

---

## 5. Who owns what

| Layer | Branch | Owner | Description |
|-------|--------|-------|-------------|
| Layer 1 | `main` / `dev` | Nikhil | LLM disruption extraction — **done** |
| Layer 2 | `feature/layer2-bayesian-fusion` | TBD | Bayesian fusion of structured + LLM signals |
| Layer 3 | `feature/layer3-routing` | TBD | CVaR routing, generalized edge cost |
| UI | `feature/ui-dashboard` | TBD | Browser dashboard, map visualization |

---

## 6. Setting up your local environment

```bash
git clone https://github.com/YOUR_ORG/traffic-ai.git
cd traffic-ai

python3 -m venv venv
source venv/bin/activate

pip install -r req.txt

cp .env.example .env
# Edit .env — add your own API keys (ask Nikhil for the shared dev keys)
```

**Never share API keys over WhatsApp/email. Use the shared .env in the team password manager or ask directly.**

---

## 7. What NOT to commit

These are already in `.gitignore` but worth knowing:

| File/folder | Why |
|-------------|-----|
| `.env` | Contains API keys |
| `venv/` | 200MB+ of packages, everyone installs their own |
| `*.db` | Generated at runtime, different on each machine |
| `app/cache/graph.graphml` | 50MB+ OSM graph, downloads automatically |
| `app/cache/*.json` | OSMnx request cache, machine-specific |
| `__pycache__/` | Python bytecode, auto-generated |
| `.DS_Store` | macOS metadata, useless to others |

---

## 8. Layer 2 and 3 — what to build next

### Layer 2: Bayesian Fusion (`feature/layer2-bayesian-fusion`)

The goal is to implement Equation 1 from the proposal:

```
π_e^post(t) = p(S | Z_e=1) × π_e^prior(t)
              ─────────────────────────────
              Σ p(S | Z_e=z) × π_e^prior(t)
```

**Inputs available from Layer 1 (already in `traffic_events.db`):**
- `severity_score` → σ(t)
- `confidence` → κ(t)  
- `road_name`, `event_type`, `is_future_event`, `fetched_at`

**What to build:**
- `app/fusion/bayesian_fusion.py` — reads Layer 1 DB, computes posterior per road segment
- Prior π_prior from GTFS-RT or a simple time-of-day baseline
- Output: per-edge disruption probability for the routing layer

### Layer 3: Risk-Aware Routing (`feature/layer3-routing`)

Implement Equation 3 (generalized edge cost):

```
c_e(t) = c_base(t) + λ1·E[τ̃] + λ2·Var[τ̃] + λ3·κ·σ + λ4·CO2 + λ5·Transfers
```

**What to build:**
- `app/routing/cost_function.py` — generalized edge cost
- `app/routing/cvar_router.py` — CVaR-based path optimization
- Integrate with Layer 2 posterior probabilities

### UI Dashboard (`feature/ui-dashboard`)

- FastAPI backend serving route + disruption data as JSON
- Simple HTML/JS frontend with Leaflet.js map
- Color-coded route legs by disruption severity
- Explanation panel: "Why this route?"

---

## 9. Questions?

Open a GitHub Issue with the label `question`. Don't use WhatsApp for code discussions — keep everything on GitHub so it's searchable.
