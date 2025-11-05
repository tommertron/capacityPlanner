#!/usr/bin/env python3
"""
Quick test script for OR-Tools solver.

Usage:
    python test_ortools_solver.py
"""

import sys
from pathlib import Path
from dataclasses import replace

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from capacity_tracker.io_utils import load_config, load_people, load_projects
from capacity_tracker.solver_ortools import solve_with_ortools
import json


def main():
    # Use sample portfolio
    portfolio_dir = Path("portfolios/sample")
    input_dir = portfolio_dir / "input"

    print("Loading sample portfolio...")
    print(f"  Projects: {input_dir / 'projects.csv'}")
    print(f"  People: {input_dir / 'people.json'}")
    print(f"  Config: {input_dir / 'config.json'}")
    print()

    # Load data
    projects_df = load_projects(input_dir / "projects.csv")
    people_df = load_people(input_dir / "people.json")
    config = load_config(input_dir / "config.json")

    # Override config to use OR-Tools
    config = replace(config,
        solver="ortools",
        solver_time_limit_seconds=60,  # Quick test, only 60s
    )

    # Run solver
    result = solve_with_ortools(projects_df, people_df, config)

    # Display results
    print()
    print("=" * 60)
    print("RESULTS")
    print("=" * 60)
    print()

    print(f"Success: {result.success}")
    print(f"Solution Type: {result.solution_type}")
    print(f"Scheduled Projects: {len(result.scheduled_projects)}")
    print(f"Unscheduled Projects: {len(result.unscheduled_projects)}")
    print(f"Violations: {len(result.violations)}")
    print()

    if result.scheduled_projects:
        print("Scheduled Projects:")
        print("-" * 60)
        for proj in result.scheduled_projects[:10]:  # Show first 10
            print(f"  {proj['id']}: {proj['name']}")
            print(f"    Timeline: {proj['start_month']} → {proj['end_month']} ({proj['duration_months']} months)")
            print(f"    Assigned: {proj['assigned_people']}")
        if len(result.scheduled_projects) > 10:
            print(f"  ... and {len(result.scheduled_projects) - 10} more")
        print()

    if result.unscheduled_projects:
        print("Unscheduled Projects:")
        print("-" * 60)
        for proj in result.unscheduled_projects:
            print(f"  {proj['id']}: {proj['name']} - {proj.get('reason', 'Unknown')}")
        print()

    if result.violations:
        print(f"Violations ({len(result.violations)}):")
        print("-" * 60)
        for v in result.violations[:10]:  # Show first 10
            print(f"  [{v.violation_type}] {v.description}")
        if len(result.violations) > 10:
            print(f"  ... and {len(result.violations) - 10} more")
        print()

    if result.recommendations:
        print("Recommendations:")
        print("-" * 60)
        recs = result.recommendations

        if isinstance(recs, dict):
            if "hiring" in recs and recs["hiring"]:
                print(f"\n  Hiring ({len(recs['hiring'])}):")
                for h in recs['hiring'][:5]:
                    print(f"    - {h['role']} with skills {h['required_skills']} by {h['by_month']}")
                    print(f"      Severity: {h['severity']}, Reason: {h['reason']}")

            if "training" in recs and recs["training"]:
                print(f"\n  Training ({len(recs['training'])}):")
                for t in recs['training'][:5]:
                    print(f"    - {t['person']}: add skills {t['recommended_skills']}")
                    print(f"      Priority: {t['priority']}, Reason: {t['reason']}")

            if "summary" in recs:
                print(f"\n  Summary: {recs['summary']}")

            if "error" in recs:
                print(f"\n  Error: {recs['error']}")
        print()

    if not result.resource_timeline.empty:
        print("Resource Timeline (sample):")
        print("-" * 60)
        print(result.resource_timeline.head(20).to_string(index=False))
        print(f"\n  Total rows: {len(result.resource_timeline)}")
        print()

    print("=" * 60)
    print("Test complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
