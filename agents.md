# PROMPT FOR CODEX — Pure-Python Capacity Planner (CSV↔CSV, no UI)

Build a **pure-Python, no-UI** batch tool that reads project CSV + people JSON + JSON config and writes two output CSVs. It must respect **people availability windows** (start/end dates on each person) and **schedule projects strictly by CSV order (top → bottom)** using available capacity. Long horizons are allowed (e.g., 10 years) if open‑ended; if a finite planning end date is provided, only schedule what can fit within that window.

---

## Deliverables

Create a small, production-quality Python package with these files:

```
/capacity_tracker
- main.py                # CLI entry; argument parsing; calls the engine
- engine.py              # allocation logic
- io_utils.py            # load/save CSV/JSON helpers; validation
- curves.py              # load curve helpers
- models.py              # dataclasses / typed records
- sample/
  - projects.csv
  - people.json
  - config.json
- out/                   # created if missing; outputs written here
- README.md
```

### CLI

```
python main.py \
  --projects sample/projects.csv \
  --people sample/people.json \
  --config sample/config.json \
  --outdir out \
  [--strict] \
  [--seed 123] \
  [--dry-run]
```

- `--strict`: if a project cannot be scheduled within the planning window, **fail**; otherwise **warn and skip**.
- `--seed`: overrides `config.random_seed` (deterministic tie-breakers).
- `--dry-run`: run planning and print a human-friendly summary (do not write CSVs).

---

## Inputs

### 1) projects.csv (headers required)

```
id,name,priority,effort_ba_pm,effort_planner_pm,effort_dev_pm,parent_summary,required_skillsets_ba,required_skillsets_planner,required_skillsets_dev
P1,Billing Platform,1,1.0,1.2,3.0,Digital Transformation,,front-office,front-end;back-end
P2,SSO Rollout,2,0.5,0.3,1.0,Infrastructure Modernization,,infrastructure,security
...
```

- `priority` is **advisory only**. The **actual scheduling order is the row order in the CSV (top → bottom)**. If `priority` exists, include it in outputs for reference.
- Efforts are in **person‑months**.
- Concurrency limits per project-month: **BA ≤ 1**, **Planner ≤ 1**, **Dev ≤ 2**.
- A role can be covered by different people in different months, but prefer role stability (keep the same person once assigned when possible).
- Skillset columns are **semicolon-separated lists**. Every listed skillset must be satisfied across the project. A single person can satisfy multiple skillsets if their profile lists them.

### 2) people.json

```json
[
  {
    "person": "Alice",
    "roles": ["BA"],
    "active": true,
    "start_date": "2025-01-01",
    "skillsets": ["business-analysis"],
    "preferred_parent_summaries": ["Digital Transformation"]
  },
  {
    "person": "Bob",
    "roles": ["Planner", "BA"],
    "active": true,
    "skillsets": ["roadmapping", "process-design"],
    "preferred_parent_summaries": ["Infrastructure Modernization"]
  },
  {
    "person": "Cara",
    "roles": ["Dev"],
    "active": true,
    "start_date": "2025-03-01",
    "end_date": "2026-06-30",
    "skillsets": ["front-end"],
    "notes": "Leaves mid-2026"
  }
]
```

- `roles` ⊆ {`BA`,`Planner`,`Dev`}. Multi-role people can flex into any listed role subject to availability.
- `skillsets` is a free-form list used to satisfy project requirements. Leave empty if the person is generalist.
- `preferred_parent_summaries` optionally biases allocations toward matching `parent_summary` values without overriding capacity rules.
- `active` (bool). Inactive entries are ignored.
- **`start_date` / `end_date`** (ISO dates, optional): availability is **inclusive** and intersects with the global planning window.

### 3) config.json (required)

```json
{
  "planning_start": "2025-01-01",
  "planning_end": null,                        // ISO date or null for open-ended
  "max_months_if_open_ended": 120,             // cap if planning_end is null
  "ktlo_pct_by_role": { "BA": 0.10, "Planner": 0.20, "Dev": 0.15 },
  "planner_project_month_cap_pct": 0.20,       // Planner per-project monthly cap
  "max_concurrent_per_role": { "BA": 1, "Planner": 1, "Dev": 2 },
  "curves": {
    "dev_curve": [0.10, 0.20, 0.40, 0.20, 0.10],
    "ba_curve": [0.10, 0.20, 0.40, 0.20, 0.10],
    "planner_curve": "uniform"                 // or [..floats..]; will be normalized
  },
  "random_seed": 42,
  "logging_level": "INFO"
}
```

**Interpretation:**
- **Planning window** is from `planning_start` through `planning_end` (inclusive). If `planning_end` is `null`, extend forward for `max_months_if_open_ended` months.
- **KTLO** is applied per person per month based on `ktlo_pct_by_role[role]`. Remaining capacity = `1.0 - ktlo` that month.
- **Total monthly load** (KTLO + project allocations) may **not exceed 1.0** for any person.
- **max_concurrent_per_role** caps how many people each project can use per role in a given month (defaults: BA=1, Planner=1, Dev=2).
- If a finite `planning_end` is provided, schedule **only** what can **fit** in that window, in CSV order; later unschedulable projects are skipped (or error with `--strict`).

---

## Outputs

### A) `project_timeline.csv` (one row per project actually scheduled)

```
id,name,parent_summary,start_month,end_month,duration_months,ba_persons,planner_persons,dev_persons,effort_ba_pm,effort_planner_pm,effort_dev_pm,priority,input_row
```

- `start_month`/`end_month`: `YYYY-MM`.
- `duration_months = months_between(start,end)+1`.
- `*_persons`: semicolon‑separated unique names actually used for that role.
- `priority`: copied from input if present; `input_row`: the 1‑based row index from the source CSV (used for tie‑break clarity).

### B) `resource_capacity.csv` (row per person/project/month where work occurs)

```
person,role,project_id,project_name,month,project_alloc_pct,total_pct
```

- `month`: `YYYY-MM` within both the **planning window** and the **person’s availability window**.
- `project_id` / `project_name`: the project receiving capacity; blank / `KTLO` rows capture the monthly KTLO load.
- `project_alloc_pct`: share (0.00–1.00) of the person’s month devoted to that project.
- `total_pct`: KTLO plus the sum of project allocations for that month.

---

## Scheduling Rules (Allocation Engine)

1) **Month index**
   - Build `YYYY-MM` index from `planning_start` to `planning_end` inclusive (or `max_months_if_open_ended` months if open-ended).
   - For each **active** person, compute **availability window** = intersection of (person.start_date..person.end_date) with the planning window. Prefill each available month with KTLO and remaining capacity = `1.0 - ktlo`.

2) **Ordering**
   - **Schedule strictly by CSV row order (top → bottom)**. Use `input_row` as the authoritative sort key. (You may still read/keep the `priority` column; it does not control ordering.)

3) **Duration & curves**
   - Dev + BA use the bell curve from config (normalize; length = project duration in “buckets”). Planner is uniform (or its curve from config) across the same number of buckets.
- Determine the **minimum duration** that can satisfy each role’s person‑month totals under concurrency limits (from `max_concurrent_per_role`) and per-project caps (Planner cap via `planner_project_month_cap_pct`). The **project duration** is the **max** across roles.

4) **Placement**
   - Attempt to place the project **as early as possible** starting at the first month of the planning window.
   - For each month of the candidate window:
    - For each role, compute required FTE that month = `curve_share * role_total_pm`. Split across up to the config-defined role limit (e.g., Devs ≤ 2 by default).
     - Choose specific people who:
       1) Are of the correct role,
       2) Are **available in that month** (per availability window),
       3) Satisfy the required skillset for that role (if any),
       4) Have remaining capacity (KTLO + allocations ≤ 1.0),
      5) Obey planner’s per-project monthly cap (`planner_project_month_cap_pct`).
     - **Person selection preferences**:
       1) Individuals that help cover still-unmet skillsets for that role,
       2) Already assigned to this project in prior months (stability),
       3) People who list the project’s `parent_summary` in their preferences,
       4) Lowest `total_pct` that month,
       5) Deterministic tiebreakers: alphabetical by `person`, then seeded random (`config.random_seed`).

   - If any role cannot fit in any month of the candidate window, **shift the entire project start by one month** and retry.
   - If open-ended, continue shifting until it fits or you hit `max_months_if_open_ended`. If finite `planning_end`, **do not** schedule beyond that; if it cannot fit fully, mark **unschedulable** (warn/skip or error with `--strict`).

5) **Accounting**
   - Record monthly allocations per (person, project, month), update remaining capacity, and collect assigned person names per role for the project’s final summary.
   - Persist both output CSVs.

---

## Implementation Details

- Use **standard library + `pandas` + `python-dateutil`** only.
- Represent months externally as `YYYY-MM`; internally iterate with `dateutil.relativedelta`.
- `io_utils.py`: centralize schema validation and give clear messages (missing columns, invalid dates/booleans).
- `curves.py`:
  - `normalize_curve(seq: list[float]) -> list[float]` (sum≈1.0 tolerance 1e‑6)
  - `uniform_curve(n: int) -> list[float]`
- `models.py`: `@dataclass` types for `Project`, `Person` (with parsed dates & availability helpers).
- `engine.py` exposes: 
  - `plan(projects_df, people_df, cfg) -> (pd.DataFrame, pd.DataFrame)` returning `(project_timeline_df, resource_capacity_df)`.
- `main.py`:
  - Wire CLI → load inputs → call `plan()` → write CSVs (ensure `out/` exists).
  - `--dry-run` prints a compact table: project id/name, planned start→end, or “unschedulable (reason)”.

### Validation & Tests

- Deterministic outputs for the same inputs + seed.
- Assert all `total_pct <= 1.0`.
- Planner never exceeds `planner_project_month_cap_pct` on any project-month.
- Curves normalize to ~1.0.
- Persons are never allocated outside their availability window.
- `duration_months` is correct and `start_month`/`end_month` lie within the planning window.

---

## Sample Files (put in `/sample`)

**people.json**
```json
[
  { "person": "Alice", "roles": ["BA"], "active": true, "start_date": "2025-01-01", "skillsets": ["business-analysis"] },
  { "person": "Bob", "roles": ["Planner"], "active": true, "skillsets": ["roadmapping"] },
  { "person": "Cara", "roles": ["Dev"], "active": true, "start_date": "2025-03-01", "end_date": "2026-06-30", "skillsets": ["front-end"], "notes": "Leaves mid-2026" },
  { "person": "Dan", "roles": ["Dev"], "active": false, "skillsets": ["back-end"] }
]
```

**projects.csv**
```
id,name,priority,effort_ba_pm,effort_planner_pm,effort_dev_pm,parent_summary,required_skillsets_ba,required_skillsets_planner,required_skillsets_dev
P1,Billing Platform,1,1.0,1.2,3.0,Digital Transformation,,,front-end
P2,SSO Rollout,2,0.5,0.3,1.0,Infrastructure Modernization,,,security
```

**config.json**
```json
{
  "planning_start": "2025-01-01",
  "planning_end": null,
  "max_months_if_open_ended": 120,
  "ktlo_pct_by_role": { "BA": 0.10, "Planner": 0.20, "Dev": 0.15 },
  "planner_project_month_cap_pct": 0.20,
  "curves": { "dev_curve": [0.10, 0.20, 0.40, 0.20, 0.10], "ba_curve": [0.10, 0.20, 0.40, 0.20, 0.10], "planner_curve": "uniform" },
  "random_seed": 42,
  "logging_level": "INFO"
}
```

---

## Acceptance

- With `planning_end = null`, the tool may schedule across long horizons (e.g., 10+ years) up to `max_months_if_open_ended`.
- With a finite `planning_end`, only projects that can fully fit within the window (given people availability + capacity constraints) are scheduled; later rows may be skipped with warnings (or error under `--strict`).
- Outputs are byte-identical for the same seed and inputs.
- Skillset requirements are enforced per role; preferred parent streams act as soft ties.
- README includes brief usage and glossary (PM, KTLO, availability window, planning window).
