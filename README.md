# Portfolio Planner

A capacity planning and resource allocation tool for managing project portfolios. Portfolio Planner helps you visualize team workload, schedule projects based on resource availability, and optimize team capacity across multiple initiatives.

## Overview

Portfolio Planner uses a scheduling algorithm to automatically assign people to projects based on:
- Project priorities and effort estimates
- Team member roles, skills, and availability
- Capacity constraints and concurrent project limits
- Keep-The-Lights-On (KTLO) reservations

The tool provides:
- Interactive web interface for portfolio management
- Visual timeline and resource allocation heatmaps
- Automated project scheduling with constraint satisfaction
- Multi-portfolio support with isolated workspaces

## Key Features

- **Portfolio Management**: Create and manage multiple portfolios with sample data templates
- **Project Planning**: Define projects with effort estimates, priorities, and skill requirements
- **Team Management**: Track people with roles, skills, availability windows, and preferences
- **Automated Scheduling**: Algorithm-driven project scheduling based on capacity and constraints
- **Resource Visualization**: Heatmap view of resource allocation by person and time period
- **Configuration Options**: Extensive planning parameters (KTLO %, effort curves, overbooking tolerance, etc.)
- **Program Organization**: Group related projects into programs with color coding
- **Export Results**: Download planning outputs as CSV and Markdown files

## Important Notes

### Local Development Focus

**This application is designed to run locally on your machine with all portfolio data stored locally.** While it can technically be deployed to a server, this is **not recommended** for the following reasons:

- No user authentication or authorization system
- No data isolation between users
- Direct file system access without access controls
- Development server (Flask built-in) is not production-ready
- No database backend - relies on local file storage
- Concurrent access may cause data conflicts

If you need multi-user access, consider:
- Running separate instances per user
- Implementing proper authentication/authorization
- Migrating to a database backend
- Using a production WSGI server (gunicorn, uWSGI)
- Adding file locking mechanisms

### Algorithm Status

⚠️ **The modeller algorithm is under active development.** While functional, it may produce unexpected results in certain scenarios. The scheduling logic is being continuously refined to handle:

- Complex resource constraints
- Skill matching edge cases
- Concurrent project allocation
- Timeline optimization
- Large portfolio scaling

**Please report any issues with the modeller logic** by opening an issue on the project repository. Include:
- Portfolio configuration (config.json)
- Project and people data
- Expected vs. actual scheduling results
- Any error messages or unexpected behavior

## Requirements

- Python 3.8 or higher
- pip (Python package manager)

## Installation

### Quick Install (Recommended)

The easiest way to install and run Portfolio Planner is using the provided shell script, which handles all dependencies automatically:

1. **Clone or download the repository**

```bash
git clone https://github.com/tommertron/capacityPlanner.git
cd capacityPlanner
```

2. **Run the startup script**

```bash
./run_web.sh
```

The script will automatically:
- Create a virtual environment
- Install all required dependencies
- Start the application on port 5151

That's it! Skip to the "Running the Application" section below.

### Manual Installation (Optional)

If you prefer to set up the environment manually:

1. **Clone or download the repository**

```bash
git clone https://github.com/tommertron/capacityPlanner.git
cd capacityPlanner
```

2. **Create a virtual environment**

```bash
python3 -m venv .venv
```

3. **Activate the virtual environment**

On macOS/Linux:
```bash
source .venv/bin/activate
```

On Windows:
```bash
.venv\Scripts\activate
```

4. **Install dependencies**

For the web interface:
```bash
pip install -r requirements-web.txt
```

For CLI-only usage:
```bash
pip install -r requirements.txt
```

## Running the Application

### Quick Start (Recommended)

The easiest way to get started is to use the provided shell script:

```bash
./run_web.sh
```

This script will:
- Automatically check for Python 3
- Create a virtual environment (`.venv`) if it doesn't exist
- Install all required dependencies from `requirements-web.txt`
- Start the Flask web server on **port 5151** (default)

Once the server starts, open your browser to: `http://127.0.0.1:5151`

**Custom port:** To use a different port, set the `PORT` environment variable:

```bash
PORT=8080 ./run_web.sh
```

### Manual Setup (Alternative)

If you prefer to run the application manually:

1. **Activate the virtual environment** (if not already activated)

```bash
source .venv/bin/activate  # macOS/Linux
# or
.venv\Scripts\activate     # Windows
```

2. **Start the Flask web server**

```bash
python -m flask --app webapp.app run --port 5151
```

3. **Open your web browser**

Navigate to: `http://127.0.0.1:5151` (or the port you specified)

### Start Using the Application

- Create a new portfolio or select an existing one
- Configure projects, people, and settings
- Run the model to generate schedules
- View results in the Timeline and Resource Allocation tabs

### CLI Usage (Batch Processing)

You can also run the planner from the command line without the web interface:

1. **Install core dependencies**

```bash
pip install -r requirements.txt
```

2. **Run the planner**

```bash
python -m capacity_tracker.main \
  --projects portfolios/sample/input/projects.csv \
  --people portfolios/sample/input/people.json \
  --config portfolios/sample/input/config.json \
  --outdir portfolios/sample/output/
```

This will generate the same output files as the web interface:
- `project_timeline.csv` - Project schedules
- `resource_capacity.csv` - Resource allocations
- `unallocated_projects.md` - Projects that couldn't be scheduled
- `resourcing_recommendations.md` - Capacity analysis

## Project Structure

```
capacityPlanner/
├── capacity_tracker/       # Core scheduling algorithm
│   ├── main.py            # CLI entry point
│   ├── engine.py          # Planning engine
│   ├── models.py          # Data models
│   └── io_utils.py        # File I/O utilities
├── webapp/                 # Web interface
│   ├── app.py             # Flask application
│   ├── jobs.py            # Background job management
│   ├── templates/         # HTML templates
│   │   └── index.html     # Main UI
│   └── static/            # Static assets
│       └── app.js         # Frontend JavaScript
├── portfolios/            # Portfolio data storage
│   ├── sample/            # Sample portfolio
│   │   ├── input/         # Input files
│   │   │   ├── projects.csv
│   │   │   ├── people.json
│   │   │   ├── config.json
│   │   │   └── programs.csv
│   │   └── output/        # Generated results
│   │       ├── project_timeline.csv
│   │       ├── resource_capacity.csv
│   │       └── unallocated_projects.md
│   └── [your portfolios]/
└── README.md              # This file
```

## Usage

### Creating a Portfolio

1. Click the "+ New Portfolio" button
2. Enter a unique name (letters, numbers, dashes, underscores only)
3. The new portfolio will be created with sample data that you can customize

### Configuring Projects

1. Select a portfolio from the dropdown
2. Go to the **Projects** tab
3. Add, edit, or delete projects
4. Set effort estimates (in person-months), priorities, and required skills
5. Organize projects into programs (optional)
6. Click "Save Changes" to persist edits

### Managing People

1. Go to the **People** tab → **Staff** subtab
2. Add team members with their roles (BA, Planner, Dev)
3. Specify skillsets to match project requirements
4. Set availability windows with start/end dates
5. Add preferred programs (optional)

### Adjusting Settings

1. Go to the **Portfolio Settings** tab
2. Configure planning parameters:
   - Planning time window
   - KTLO percentages by role
   - Maximum concurrent projects
   - Effort distribution curves
   - Priority-based scheduling
   - Overbooking tolerance

### Running the Model

1. Go to the **Modeller** tab
2. Ensure portfolio, projects, people, and settings are configured
3. Click "Run Model"
4. Monitor job status in the Recent Jobs table
5. When complete, view results in:
   - **Projects → Timeline**: Project schedule with start/end dates
   - **Projects → Unallocated**: Projects that couldn't be scheduled
   - **People → Resource Allocation**: Resource utilization heatmap

### Interpreting Results

- **Timeline**: Shows when each project runs and who is assigned
- **Resource Allocation Heatmap**: Color-coded view of person allocation by month
  - Light blue = low allocation
  - Dark blue = high allocation (approaching 100%)
  - Red = overallocation (>100%)
- **Unallocated Projects**: Projects that failed to schedule with explanations of constraints

## Data Format

### projects.csv
```csv
id,name,priority,effort_ba_pm,effort_planner_pm,effort_dev_pm,parent_summary,required_skillsets_ba,required_skillsets_planner,required_skillsets_dev
P1,Project Name,1,1.0,2.0,3.0,Program Name,,,front-end;back-end
```

### people.json
```json
[
  {
    "person": "Alice",
    "roles": ["BA", "Planner"],
    "active": true,
    "start_date": "2025-01-01",
    "end_date": null,
    "skillsets": ["business-analysis"],
    "preferred_parent_summaries": ["Digital Transformation"],
    "notes": ""
  }
]
```

### config.json
```json
{
  "planning_start": "2025-01-01",
  "planning_end": null,
  "max_months_if_open_ended": 120,
  "ktlo_pct_by_role": {
    "BA": 0.1,
    "Dev": 0.15,
    "Planner": 0.2
  },
  "max_concurrent_per_role": {
    "BA": 1,
    "Dev": 2,
    "Planner": 1
  },
  "curves": {
    "ba_curve": [0.1, 0.2, 0.4, 0.2, 0.1],
    "dev_curve": [0.1, 0.2, 0.4, 0.2, 0.1],
    "planner_curve": "uniform"
  },
  "priority_based_scheduling": true,
  "overbooking_tolerance_pct": 0.20
}
```

## Troubleshooting

### Model fails to run
- Verify all required input files exist: `projects.csv`, `people.json`, `config.json`
- Check for data format errors (dates in YYYY-MM-DD format, numeric values valid)
- Review the Recent Jobs table for error messages

### Projects not scheduling
- Ensure you have enough people with required skills and roles
- Check people availability windows overlap with planning period
- Reduce project effort estimates or increase team size
- Review KTLO percentages (may be too high)

### Performance issues
- Large portfolios (>100 projects) may take longer to schedule
- Consider breaking into smaller portfolios or phases
- Reduce the planning time window if open-ended

### Port already in use
If port 5151 is already in use, specify a different port:
```bash
PORT=8080 ./run_web.sh
```

Or if running manually:
```bash
python -m flask --app webapp.app run --port 8080
```

## Contributing

This is an active development project. Contributions, bug reports, and feature requests are welcome!

### Reporting Issues

When reporting issues with the modeller algorithm, please include:
- Portfolio configuration files (config.json, projects.csv, people.json)
- Steps to reproduce the issue
- Expected behavior vs. actual behavior
- Any error messages or logs

## Acknowledgments

Built with:
- Flask (web framework)
- Pandas (data processing)
- NumPy (numerical computations)
- Vanilla JavaScript (frontend)
