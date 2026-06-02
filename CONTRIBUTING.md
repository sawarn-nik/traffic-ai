# Contributing to traffic-ai

Read this before writing any code. It covers setup, branching, commits, and what each layer needs to build.

---

## 1. First-time setup

```bash
git clone https://github.com/sawarn-nik/traffic-ai.git
cd traffic-ai

python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r req.txt

cp .env.example .env
# Fill in your API keys — ask Nikhil for the shared dev set
```

**Never commit `.env`.** It's in `.gitignore`. Keys go in `.env` only.

---

## 2. Running the project

```bash
cd app
uvicorn api:app --port 8000 --reload
# Open http://localhost:8000
```

`main.py` is the old CLI version — use it only for quick debugging without the browser.

---

## 3. Branch strategy

```
main   ← stable, protected — no direct pushes
 └── dev  ← everyone merges here
      ├── feature/layer2-bayesian-fusion   (Teammate A)
      ├── feature/layer3-routing           (Teammate B)
      ├── feature/ui-extensions            (Teammate C)
      └── fix/short-description
```

**Rules:**
- Branch off `dev`, merge back into `dev` via PR
- Never push directly to `main` or `dev`
- `main` only updated by merging `dev` after team review

---

## 4. Daily workflow

```bash
# Sync with latest dev
git checkout dev
git pull origin dev
git checkout your-feature-branch
git rebase dev

# Work and commit
git add app/your_file.py
git commit -m "feat(scope): what you did"

# Push to both repos at once
git push
```

---

## 5. Commit message format

```
feat(extractor): add JSON repair for malformed LLM output
fix(rss_fetcher): scope queries to when:2d for recency
refactor(route_engine): extract bounds check into helper
docs(readme): update quickstart for uvicorn
chore(deps): add fastapi and uvicorn to req.txt
```

| Prefix | When to use |
|--------|-------------|
| `feat` | New feature |
| `fix` | Bug fix |
| `refactor` | Restructure without behaviour change |
| `docs` | Docs, comments, docstrings |
| `chore` | Dependencies, config, tooling |

---

## 6. PR checklist

- [ ] `uvicorn api:app --port 8000` starts without errors
- [ ] No `.env` file in the diff (`git status` should not show it)
- [ ] No API keys anywhere in the code
- [ ] New functions have docstrings
- [ ] PR description explains what changed and why

---

## 7. What NOT to commit

| File/folder | Reason |
|-------------|--------|
| `.env` | API keys |
| `venv/` | ~200MB, everyone installs their own |
| `*.db` | Generated at runtime |
| `app/cache/graph.graphml` | ~50MB OSM graph, auto-downloaded |
| `app/cache/*.json` | OSMnx cache, machine-specific |
| `__pycache__/` | Python bytecode |
| `.DS_Store` | macOS metadata |

---

## 8. Two remotes — one push

Your local repo pushes to both the personal repo and the team repo simultaneously:

```bash
git remote -v
# origin  https://github.com/sawarn-nik/traffic-ai.git (fetch)
# origin  https://github.com/sawarn-nik/traffic-ai.git (push)
# origin  https://github.com/lakshya1729git/IIT_kgp_internship.git (push)
```

One `git push` → both repos updated. No extra steps.

---

## 9. Layer 2 — Bayesian Fusion

**File:** `app/fusion/bayesian_fusion.py` (placeholder with spec)  
**Branch:** `feature/layer2-bayesian-fusion`

Implement Eq. 1 from the proposal:

```
π_e^post(t) = p(S | Z_e=1) × π_e^prior(t)
              ─────────────────────────────
              Σ p(S | Z_e=z) × π_e^prior(t)
```

**Inputs** already in `traffic_events.db`:
- `severity_score` → σ(t)
- `confidence` → κ(t)
- `road_name`, `event_type`, `is_future_event`, `fetched_at`

**Output:** `dict[road_name → posterior_probability ∈ [0,1]]`  
This feeds into Layer 3's edge cost function.

**Prior:** start with a simple time-of-day baseline (peak hours = 0.2, off-peak = 0.05), refine with historical DB rates later.

---

## 10. Layer 3 — Risk-Aware Routing

**File:** `app/routing/cost_function.py` (placeholder with spec)  
**Branch:** `feature/layer3-routing`

Implement Eq. 3:

```
c_e(t) = c_base(t)
       + λ1·E[τ̃_e(t)]     ← expected travel time
       + λ2·Var[τ̃_e(t)]    ← reliability
       + λ3·κ·σ             ← disruption risk
       + λ4·CO2(e)          ← emissions
       + λ5·Transfers(e)    ← mode-switch penalty
```

Files to build:
- `app/routing/cost_function.py` — generalized edge cost
- `app/routing/cvar_router.py` — CVaR path optimization
- `app/routing/travel_time.py` — travel time distributions

---

## 11. Questions

Open a GitHub Issue with label `question`. Keep code discussions on GitHub, not WhatsApp — it's searchable and archived.
