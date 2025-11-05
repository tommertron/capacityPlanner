# Portfolio Planner - Developer Guide for Claude Code

## Project Overview

Portfolio Planner is a **capacity planning and resource allocation tool** for managing project portfolios. It automatically schedules projects based on team availability, skills, and capacity constraints.

**Core Function:** Reads project requirements + people availability → outputs optimized project timeline + resource allocation.

**Deployment:** Designed for **local development only** (no auth, file-based storage, Flask dev server).

## Architecture

```
capacity_tracker/     # Core scheduling algorithm (Python)
├── engine.py         # Main allocation logic
├── models.py         # Data models (Project, Person, PlanningConfig)
├── io_utils.py       # CSV/JSON loading & validation
├── curves.py         # Effort curve utilities
└── main.py           # CLI entry point

webapp/               # Flask web interface
├── app.py            # Flask routes & REST API
├── jobs.py           # Background job management
├── static/app.js     # Frontend JavaScript
└── templates/index.html

portfolios/           # Local file-based storage
└── [portfolio-name]/
    ├── input/        # projects.csv, people.json, config.json, programs.csv
    └── output/       # project_timeline.csv, resource_capacity.csv, unallocated_projects.md
```

## Key Domain Concepts

### Scheduling Rules (CRITICAL)
- **Projects scheduled STRICTLY by CSV row order (top → bottom)**
- The `priority` field is **advisory only**, NOT used for ordering
- Use `input_row` as the authoritative sort key
- Attempts to place projects **as early as possible** in planning window
- If constraints not met, shifts project start by 1 month and retries

### Capacity Constraints
- **KTLO** (Keep The Lights On) - % reserved per role per person per month (e.g., BA: 10%, Planner: 20%, Dev: 15%)
- **Max concurrent per role** - limits people per project-role (default: BA=1, Planner=1, Dev=2)
- **Planner cap** - per-project monthly cap at 20% (`planner_project_month_cap_pct`)
- **Total monthly load** = KTLO + project allocations ≤ 100% (or overbooking tolerance)
- **Allocation modes**:
  - `"strict"` - respects 100% capacity limit
  - `"aggressive"` - allows overbooking, provides hiring recommendations

### Person Availability Windows
- People have optional `start_date` and `end_date` (ISO format)
- Availability = intersection of (person window) ∩ (planning window)
- **NEVER allocate people outside their availability window**

### Skill Matching
- Projects specify `required_skillsets_[role]` (semicolon-separated)
- People have `skillsets` array
- All required skillsets must be covered by assigned people
- Empty skillsets = generalist (can match anything)

### Effort Curves
- **Dev/BA** - bell-shaped distribution (e.g., [0.10, 0.20, 0.40, 0.20, 0.10])
- **Planner** - typically uniform distribution
- Curves normalized to sum ≈ 1.0
- Determines how effort is distributed across project duration

### Person Selection Preferences (in order)
1. Covers still-unmet skillsets for that role
2. Already assigned to this project (stability)
3. Lists project's `parent_summary` in `preferred_parent_summaries`
4. Lowest `total_pct` that month (most available)
5. Alphabetical by name, then seeded random (`random_seed`)

## Data Models

### Projects (projects.csv)
```csv
id,name,priority,effort_ba_pm,effort_planner_pm,effort_dev_pm,parent_summary,required_skillsets_ba,required_skillsets_planner,required_skillsets_dev
```
- Effort in **person-months**
- Skillsets are **semicolon-separated** (e.g., "front-end;back-end")
- `priority` is advisory only (NOT used for scheduling order)

### People (people.json)
```json
{
  "person": "Alice",
  "roles": ["BA", "Planner"],
  "active": true,
  "start_date": "2025-01-01",  // optional, ISO format
  "end_date": "2026-12-31",    // optional, ISO format
  "skillsets": ["business-analysis", "roadmapping"],
  "preferred_parent_summaries": ["Digital Transformation"],
  "notes": ""
}
```

### Config (config.json)
```json
{
  "planning_start": "2025-01-01",
  "planning_end": null,  // null = open-ended
  "max_months_if_open_ended": 120,
  "ktlo_pct_by_role": {"BA": 0.10, "Planner": 0.20, "Dev": 0.15},
  "planner_project_month_cap_pct": 0.20,
  "max_concurrent_per_role": {"BA": 1, "Planner": 1, "Dev": 2},
  "curves": {
    "dev_curve": [0.10, 0.20, 0.40, 0.20, 0.10],
    "ba_curve": [0.10, 0.20, 0.40, 0.20, 0.10],
    "planner_curve": "uniform"
  },
  "priority_based_scheduling": true,
  "overbooking_tolerance_pct": 0.20,
  "allocation_mode": "strict",  // "strict" or "aggressive"
  "random_seed": 42,
  "logging_level": "INFO"
}
```

### Programs (programs.csv)
```csv
id,name,color
Digital Transformation,Digital Transformation,#4A90E2
```

## Output Files

### project_timeline.csv
- Scheduled projects with `start_month`, `end_month`, `duration_months` (YYYY-MM format)
- Lists assigned people per role (semicolon-separated in `ba_persons`, `planner_persons`, `dev_persons`)
- Includes `priority` and `input_row` for reference

### resource_capacity.csv
- Row per person/project/month with allocations
- `project_alloc_pct` - % devoted to that project
- `total_pct` - KTLO + all project allocations (must be ≤ 1.0 or tolerance)
- Months only within person's availability window

### unallocated_projects.md
- Projects that couldn't be scheduled
- Includes reasons (insufficient capacity, missing skills, outside planning window, etc.)

## Development Guidelines

### CRITICAL Validations
- ✅ All `total_pct ≤ 1.0` (or overbooking tolerance in aggressive mode)
- ✅ Planner never exceeds `planner_project_month_cap_pct` on any project-month
- ✅ Curves normalize to ~1.0 (tolerance: 1e-6)
- ✅ Persons never allocated outside availability windows
- ✅ `duration_months` correct, start/end within planning window
- ✅ Deterministic outputs for same inputs + seed

### Month Representation
- **External format:** `YYYY-MM` (strings in CSVs, JSON)
- **Internal iteration:** Use `dateutil.relativedelta` for month arithmetic
- **Date parsing:** ISO format `YYYY-MM-DD`

### Algorithm Status
⚠️ **The modeller algorithm is under active development.** It may produce unexpected results in edge cases. Handle constraint violations gracefully and provide clear error messages.

### Code Style
- Use type hints (already present in models.py)
- Dataclasses for models (frozen=True for immutability)
- Pandas for CSV processing
- Clear validation errors with actionable messages

## Common Commands

### Start Web Interface
```bash
./run_web.sh
# or
python -m flask --app webapp.app run --port 5151
```
Then open: http://127.0.0.1:5151

### Run CLI Modeller
```bash
python -m capacity_tracker.main \
  --projects portfolios/sample/input/projects.csv \
  --people portfolios/sample/input/people.json \
  --config portfolios/sample/input/config.json \
  --outdir portfolios/sample/output
```

### Flags
- `--strict` - fail if any project can't be scheduled
- `--seed 123` - override config random_seed
- `--dry-run` - print summary without writing CSVs

### Install Dependencies
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-web.txt
```

## Key File Locations

- **Data models:** `capacity_tracker/models.py` (Project, Person, PlanningConfig)
- **Scheduling engine:** `capacity_tracker/engine.py` (plan() function)
- **I/O & validation:** `capacity_tracker/io_utils.py`
- **Curve utilities:** `capacity_tracker/curves.py`
- **Web API:** `webapp/app.py` (Flask routes)
- **Frontend:** `webapp/static/app.js` (vanilla JS)
- **Background jobs:** `webapp/jobs.py`

## Testing Approach

1. **Use sample portfolios:** Test with `portfolios/sample/` or create test portfolios
2. **Verify determinism:** Same inputs + seed → identical outputs (byte-for-byte)
3. **Check constraints:** Run validation checks on outputs
4. **Edge cases to test:**
   - Availability gaps (person unavailable during planning window)
   - Skill mismatches (no one has required skill)
   - Capacity exhaustion (not enough people)
   - Long planning horizons (120+ months)
   - Open-ended vs finite planning windows

## Common Workflows

### Adding a New Feature
1. Update data models in `models.py` if needed
2. Update I/O in `io_utils.py` for loading/validation
3. Implement logic in `engine.py`
4. Update web API in `webapp/app.py`
5. Update frontend in `webapp/static/app.js`
6. Test with sample portfolios

### Debugging Scheduling Issues
1. Check `portfolios/[name]/output/unallocated_projects.md` for reasons
2. Verify person availability windows overlap with planning window
3. Check skill requirements vs available skillsets
4. Review KTLO percentages (may be too high)
5. Inspect `resource_capacity.csv` for allocation patterns

### Modifying the Algorithm
- **Main entry point:** `engine.py` → `plan()` function
- **Person selection logic:** Look for candidate selection with preference ordering
- **Constraint checking:** Validate capacity, skills, concurrency limits
- **Update tests:** Ensure deterministic outputs still hold

## Important Notes

- **Local only:** No multi-user support, no auth, no database
- **File-based storage:** All data in `portfolios/` directory
- **Flask dev server:** Not production-ready
- **Active development:** Algorithm may have edge cases
- **Report issues:** Include config.json, projects.csv, people.json when reporting bugs

## References

- **User docs:** `README.md`
- **Original spec:** `agents.md` (detailed algorithm specification)
- **Claude settings:** `.claude/settings.local.json` (permissions)
