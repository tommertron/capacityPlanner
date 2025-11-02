# Capacity Tracker

Batch capacity planning tool that schedules project demands onto available people. Inputs are CSV and JSON files; outputs are CSV summaries for projects and monthly resource utilisation.

## Features

- Respects planning windows, people availability, and KTLO load.
- Configurable per-role concurrency limits with deterministic tie-breaking.
- Bell-curve demand shaping for Dev/BA roles with uniform (or user-defined) planner curve.
- Deterministic allocations with seed override for reproducible planning.
- CLI supports project-directory workflows, dry-run summaries, and strict failure mode.
- Handles multi-role resources, skillsets, and preferred parent streams when assigning work.
- Generates `unallocated_projects.md` highlighting skipped work and the constraining resources.

## Requirements

- Python 3.11+
- Dependencies: `pandas`, `python-dateutil`

Install locally:

```bash
python -m venv .venv
source .venv/bin/activate
pip install pandas python-dateutil
```

For the optional web runner:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-web.txt
export FLASK_APP=webapp.app:create_app
flask run --host=127.0.0.1 --port=5000
```

## Usage

### Project directory layout

Each planning run lives in `projects/<run-name>/`:

```
projects/
  sample/
    input/
      projects.csv
      people.json
      config.json
    output/
      (generated files)
```

### Run the planner

From the repository root:

```bash
python -m capacity_tracker.main --project-dir projects/sample
```

The CLI automatically reads inputs from `<project-dir>/input/` and writes outputs to `<project-dir>/output/`.
`projects.csv` must include the `required_skillsets_*` columns (semicolon separated lists), and
`people.json` describes each person’s roles, availability, skillsets, and optional parent stream preferences.

Optional flags:

- `--strict` — fail if any project cannot be placed within the planning window.
- `--seed 123` — override the configuration seed for deterministic tie-breaking.
- `--dry-run` — compute the plan and print a summary instead of writing outputs.
- `--projects/--people/--config/--outdir` — override individual paths when needed.

Adjust per-role headcount caps via `max_concurrent_per_role` in `config.json` (defaults: BA=1, Planner=1, Dev=2).

Outputs are written to the resolved output directory:

- `project_timeline.csv` — scheduled projects with dates, duration, participants, and effort totals.
- `resource_capacity.csv` — one row per person/project/month showing role, project ID, project name, and monthly percentages (KTLO is emitted as its own row).
- `unallocated_projects.md` — Markdown summary of skipped projects and bottleneck resources.

## Glossary

- **PM (person-month)** — effort units for project work; concurrency limits bound how many PMs can land in a single month per role.
- **KTLO** — keep-the-lights-on load. Applied per person per month, reducing project capacity.
- **Availability window** — intersection of a person’s start/end dates with the global planning window; outside this span the person cannot be scheduled.
- **Planning window** — range of months examined when placing projects. Defined by `planning_start`/`planning_end` or capped via `max_months_if_open_ended`.
- **Skillset** — domain expertise labels (e.g., `front-end`, `security`) used to ensure projects receive appropriately skilled resources.

## Sample Data

Reference inputs live in `projects/sample/input/`. Run the sample command above to generate example outputs in `projects/sample/output/`.
