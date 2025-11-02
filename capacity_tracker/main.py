from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from . import engine
from .engine import UnschedulableProjectError
from .io_utils import ensure_directory, load_config, load_people, load_projects, write_csv


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capacity planning batch tool (CSV in/out, no UI)."
    )
    parser.add_argument(
        "--project-dir",
        help="Project directory containing input/ and output/ subfolders",
    )
    parser.add_argument("--projects", help="Path to projects CSV input (overrides project-dir default)")
    parser.add_argument("--people", help="Path to people CSV input (overrides project-dir default)")
    parser.add_argument("--config", help="Path to configuration JSON file (overrides project-dir default)")
    parser.add_argument(
        "--outdir",
        default=None,
        help="Output directory for generated CSV files (default: <project-dir>/output or ./out)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail if any project cannot be scheduled within the planning window",
    )
    parser.add_argument(
        "--seed",
        type=int,
        help="Override config.random_seed for deterministic tie-breaking",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan and print summary without writing output CSV files",
    )
    return parser.parse_args()


def _resolve_io_paths(args: argparse.Namespace) -> Tuple[Path, Path, Path, Path]:
    project_dir = Path(args.project_dir).resolve() if args.project_dir else None
    if project_dir and not project_dir.exists():
        raise ValueError(f"project directory not found: {project_dir}")
    input_dir = project_dir / "input" if project_dir else None

    def _pick(path_value: Optional[str], default_name: str) -> Optional[Path]:
        if path_value:
            return Path(path_value)
        if input_dir:
            return input_dir / default_name
        return None

    projects_path = _pick(args.projects, "projects.csv")
    people_path = _pick(args.people, "people.json")
    config_path = _pick(args.config, "config.json")

    missing = [
        name
        for name, value in (("projects", projects_path), ("people", people_path), ("config", config_path))
        if value is None
    ]
    if missing:
        joined = ", ".join(f"--{name}" for name in missing)
        raise ValueError(f"missing required input paths: {joined} (or provide --project-dir)")

    for label, path in (("projects", projects_path), ("people", people_path), ("config", config_path)):
        if not path.exists():
            raise ValueError(f"{label} file not found at {path}")

    if args.outdir:
        outdir = Path(args.outdir)
    elif project_dir:
        outdir = project_dir / "output"
    else:
        outdir = Path("out")

    return projects_path, people_path, config_path, outdir


def _configure_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(levelname)s %(message)s")


def _print_dry_run_summary(projects: pd.DataFrame, skipped: List[Dict[str, object]]) -> None:
    if projects.empty:
        print("No projects scheduled.")
    else:
        print("Scheduled projects:")
        for row in projects.itertuples(index=False):
            arrow = "→"
            months_label = "month" if row.duration_months == 1 else "months"
            print(
                f"- {row.id} {row.name}: {row.start_month} {arrow} {row.end_month} "
                f"({row.duration_months} {months_label})"
            )
    if skipped:
        print("\nSkipped projects:")
        for item in skipped:
            print(f"- {item['id']} {item['name']}: {item['reason']}")
    else:
        print("\nSkipped projects: none")


def _format_available(detail: Dict[str, object]) -> Optional[str]:
    available = detail.get("available") if isinstance(detail, dict) else None
    if not available:
        return None
    entries = []
    for entry in available:
        name = entry.get("name", "")
        capacity = float(entry.get("capacity", 0.0))
        skills = entry.get("skills")
        if isinstance(skills, (list, tuple)) and skills:
            skills_label = ", ".join(str(skill) for skill in skills)
            entries.append(f"{name} ({capacity:.2f} free; skills: {skills_label})")
        else:
            entries.append(f"{name} ({capacity:.2f} free)")
    return ", ".join(entries)


def _write_skipped_markdown(skipped: List[Dict[str, object]], outdir: Path) -> None:
    path = outdir / "unallocated_projects.md"
    lines: List[str] = ["# Unallocated Projects", ""]
    if not skipped:
        lines.append("All projects were scheduled.")
    else:
        for item in skipped:
            lines.append(f"- **{item['id']} – {item['name']}**")
            lines.append(f"  - Reason: {item['reason']}")
            detail = item.get("detail") if isinstance(item.get("detail"), dict) else {}
            month_label = detail.get("month_label")
            if month_label:
                lines.append(f"  - Month: {month_label}")
            shortfall = detail.get("shortfall")
            if isinstance(shortfall, (int, float)) and shortfall > 0:
                lines.append(f"  - Shortfall: {shortfall:.2f} PM")
            needed_skillsets = detail.get("needed_skillsets")
            if isinstance(needed_skillsets, (list, tuple)) and needed_skillsets:
                lines.append(
                    f"  - Needed Skillsets: {', '.join(str(skill) for skill in needed_skillsets)}"
                )
            missing_skillsets = detail.get("missing_skillsets")
            if isinstance(missing_skillsets, dict) and missing_skillsets:
                for role_key, skills in missing_skillsets.items():
                    skill_label = ", ".join(skills) if skills else "unspecified"
                    lines.append(f"  - Missing for {role_key}: {skill_label}")
            bottlenecks = _format_available(detail) if detail else None
            if bottlenecks:
                lines.append(f"  - Bottlenecks: {bottlenecks}")
            elif detail.get("role"):
                lines.append(f"  - Bottleneck Role: {detail['role']}")
            lines.append("")
    path.write_text("\n".join(lines).strip() + "\n")


def main() -> None:
    args = _parse_args()
    try:
        projects_path, people_path, config_path, outdir = _resolve_io_paths(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)

    projects_df = load_projects(projects_path)
    people_df = load_people(people_path)
    cfg = load_config(config_path)
    if args.seed is not None:
        cfg = replace(cfg, random_seed=args.seed)
    _configure_logging(cfg.logging_level)
    try:
        project_timeline_df, resource_capacity_df = engine.plan(
            projects_df, people_df, cfg, strict=args.strict
        )
    except UnschedulableProjectError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    skipped = resource_capacity_df.attrs.get("skipped_projects", [])

    if args.dry_run:
        _print_dry_run_summary(project_timeline_df, skipped)
        return

    outdir_path = ensure_directory(outdir)
    timeline_path = Path(outdir_path) / "project_timeline.csv"
    capacity_path = Path(outdir_path) / "resource_capacity.csv"
    write_csv(project_timeline_df, timeline_path)
    write_csv(resource_capacity_df, capacity_path)
    _write_skipped_markdown(skipped, outdir_path)
    print(f"Wrote {timeline_path}")
    print(f"Wrote {capacity_path}")
    print(f"Wrote {outdir_path / 'unallocated_projects.md'}")
    if skipped:
        print("Skipped projects:")
        for item in skipped:
            print(f"- {item['id']} {item['name']}: {item['reason']}")


if __name__ == "__main__":
    main()
