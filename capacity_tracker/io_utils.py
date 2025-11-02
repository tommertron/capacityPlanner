from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Dict, Iterable, Optional, Sequence

import pandas as pd
from dateutil import parser as dateparser

from .models import PlanningConfig, ROLE_CONCURRENCY_LIMITS

MONTH_FMT = "%Y-%m"

_PROJECT_REQUIRED_COLUMNS = {
    "id",
    "name",
    "effort_ba_pm",
    "effort_planner_pm",
    "effort_dev_pm",
    "parent_summary",
}


def _require_columns(df: pd.DataFrame, required: Iterable[str], source: str) -> None:
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"{source} missing required columns: {', '.join(missing)}")


def load_projects(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if df.empty:
        raise ValueError("projects file is empty")
    _require_columns(df, _PROJECT_REQUIRED_COLUMNS, "projects.csv")
    for col in ["effort_ba_pm", "effort_planner_pm", "effort_dev_pm"]:
        try:
            df[col] = pd.to_numeric(df[col])
        except ValueError as exc:
            raise ValueError(f"invalid numeric value in column '{col}'") from exc
        if (df[col] < 0).any():
            raise ValueError(f"column '{col}' contains negative values")
    df["priority"] = df.get("priority")
    skillset_columns = [
        ("required_skillsets_ba", "BA"),
        ("required_skillsets_planner", "Planner"),
        ("required_skillsets_dev", "Dev"),
    ]
    for column_name, _ in skillset_columns:
        if column_name not in df.columns:
            df[column_name] = ""
        df[column_name] = df[column_name].map(
            lambda value, field=column_name: _parse_skillset_field(value, field)
        )
    df["input_row"] = df.index + 1
    return df


def _parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or (isinstance(value, float) and pd.isna(value)):
        raise ValueError("active column contains missing values")
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "t", "1", "yes", "y"}:
            return True
        if lowered in {"false", "f", "0", "no", "n"}:
            return False
    raise ValueError(f"cannot interpret boolean value '{value}'")


def _parse_optional_date(value: object, field_name: str) -> Optional[date]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    try:
        return dateparser.isoparse(str(value)).date()
    except (ValueError, TypeError) as exc:
        raise ValueError(f"invalid date in '{field_name}': {value}") from exc


def _parse_skillset_field(value: object, field_name: str) -> Tuple[str, ...]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ()
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return ()
        if stripped.startswith("[") and stripped.endswith("]"):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON array in '{field_name}'") from exc
            if not isinstance(parsed, Sequence):
                raise ValueError(f"expected array for '{field_name}'")
            return tuple(str(item).strip() for item in parsed if str(item).strip())
        return tuple(part.strip() for part in stripped.split(";") if part.strip())
    if isinstance(value, Sequence):
        return tuple(str(item).strip() for item in value if str(item).strip())
    raise ValueError(f"unsupported value for '{field_name}': {value!r}")


def load_people(path: str | Path) -> pd.DataFrame:
    data = json.loads(Path(path).read_text())
    if not isinstance(data, list):
        raise ValueError("people file must be a JSON array")
    rows = []
    valid_roles = {"BA", "Planner", "Dev"}
    for entry in data:
        if not isinstance(entry, dict):
            raise ValueError("people entries must be objects")
        name = entry.get("person")
        if not name or not isinstance(name, str):
            raise ValueError("person name is required")
        roles = entry.get("roles")
        if not roles or not isinstance(roles, list):
            raise ValueError(f"roles must be a non-empty array for {name}")
        cleaned_roles = []
        for role in roles:
            role_str = str(role).strip()
            if role_str not in valid_roles:
                raise ValueError(f"unsupported role '{role_str}' for {name}")
            cleaned_roles.append(role_str)
        active = _parse_bool(entry.get("active", True))
        start_date = _parse_optional_date(entry.get("start_date"), "start_date")
        end_date = _parse_optional_date(entry.get("end_date"), "end_date")
        skillsets = _parse_skillset_field(entry.get("skillsets", ()), "skillsets")
        preferred_streams = _parse_skillset_field(
            entry.get("preferred_parent_summaries", ()), "preferred_parent_summaries"
        )
        rows.append(
            {
                "person": name,
                "roles": tuple(cleaned_roles),
                "active": active,
                "start_date": start_date,
                "end_date": end_date,
                "skillsets": tuple(skillsets),
                "preferred_parent_summaries": tuple(preferred_streams),
                "notes": str(entry.get("notes", "") or ""),
            }
        )
    if not rows:
        raise ValueError("people file is empty")
    return pd.DataFrame(rows)


def _validate_ktlo(ktlo: dict) -> dict:
    required_roles = {"BA", "Planner", "Dev"}
    missing = required_roles - set(ktlo)
    if missing:
        raise ValueError(f"ktlo_pct_by_role missing roles: {', '.join(sorted(missing))}")
    invalid = {role: value for role, value in ktlo.items() if value < 0 or value >= 1}
    if invalid:
        details = ", ".join(f"{role}: {value}" for role, value in invalid.items())
        raise ValueError(f"ktlo_pct_by_role values must be in [0,1): {details}")
    return ktlo


def load_config(path: str | Path) -> PlanningConfig:
    data = json.loads(Path(path).read_text())
    try:
        planning_start = dateparser.isoparse(data["planning_start"]).date()
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError("planning_start must be a valid ISO date string") from exc
    planning_end_raw = data.get("planning_end")
    planning_end: Optional[date]
    if planning_end_raw is None:
        planning_end = None
    else:
        try:
            planning_end = dateparser.isoparse(planning_end_raw).date()
        except (ValueError, TypeError) as exc:
            raise ValueError("planning_end must be null or an ISO date string") from exc
        if planning_end < planning_start:
            raise ValueError("planning_end must not be earlier than planning_start")
    max_months_raw = data.get("max_months_if_open_ended")
    if planning_end is None:
        if not isinstance(max_months_raw, int) or max_months_raw <= 0:
            raise ValueError("max_months_if_open_ended must be a positive integer when planning_end is null")
        max_months = max_months_raw
    else:
        max_months = int(max_months_raw) if isinstance(max_months_raw, int) and max_months_raw > 0 else 0
    project_month_cap = data.get("planner_project_month_cap_pct", 0.2)
    if not isinstance(project_month_cap, (int, float)):
        raise ValueError("planner_project_month_cap_pct must be a number")
    project_month_cap = float(project_month_cap)
    if not (0 < project_month_cap <= 1):
        raise ValueError("planner_project_month_cap_pct must be in (0, 1]")
    ktlo = _validate_ktlo(data.get("ktlo_pct_by_role", {}))
    curves = data.get("curves") or {}
    if not isinstance(curves, dict):
        raise ValueError("curves must be an object")
    # Backwards compatibility shim
    if "dev_curve" not in curves and "dev_ba_curve" in curves:
        curves["dev_curve"] = curves["dev_ba_curve"]
    if "ba_curve" not in curves and "dev_ba_curve" in curves:
        curves["ba_curve"] = curves["dev_ba_curve"]
    concurrency_cfg = data.get("max_concurrent_per_role")
    if concurrency_cfg is None:
        max_concurrent_per_role = {role: int(limit) for role, limit in ROLE_CONCURRENCY_LIMITS.items()}
    else:
        if not isinstance(concurrency_cfg, dict):
            raise ValueError("max_concurrent_per_role must be an object")
        max_concurrent_per_role: Dict[str, int] = {}
        for role, default_limit in ROLE_CONCURRENCY_LIMITS.items():
            value = concurrency_cfg.get(role, default_limit)
            if not isinstance(value, (int, float)):
                raise ValueError(f"max_concurrent_per_role[{role}] must be a number")
            value_int = int(value)
            if value_int <= 0:
                raise ValueError(f"max_concurrent_per_role[{role}] must be positive")
            max_concurrent_per_role[role] = value_int
        # Allow additional roles in config but ignore them for now
    random_seed = data.get("random_seed")
    if random_seed is not None and not isinstance(random_seed, int):
        raise ValueError("random_seed must be an integer if provided")
    logging_level = data.get("logging_level", "INFO")

    # Priority-based scheduling settings
    priority_based_scheduling = data.get("priority_based_scheduling", True)
    if not isinstance(priority_based_scheduling, bool):
        raise ValueError("priority_based_scheduling must be a boolean")

    high_priority_threshold = data.get("high_priority_threshold", 10)
    if not isinstance(high_priority_threshold, (int, float)):
        raise ValueError("high_priority_threshold must be a number")
    high_priority_threshold = int(high_priority_threshold)

    overbooking_tolerance_pct = data.get("overbooking_tolerance_pct", 0.20)
    if not isinstance(overbooking_tolerance_pct, (int, float)):
        raise ValueError("overbooking_tolerance_pct must be a number")
    overbooking_tolerance_pct = float(overbooking_tolerance_pct)
    if not (0 <= overbooking_tolerance_pct <= 1):
        raise ValueError("overbooking_tolerance_pct must be in [0, 1]")

    return PlanningConfig(
        planning_start=planning_start,
        planning_end=planning_end,
        max_months_if_open_ended=int(max_months),
        ktlo_pct_by_role={str(role): float(value) for role, value in ktlo.items()},
        planner_project_month_cap_pct=project_month_cap,
        curves=curves,
        random_seed=random_seed,
        logging_level=logging_level,
        max_concurrent_per_role=max_concurrent_per_role,
        priority_based_scheduling=priority_based_scheduling,
        high_priority_threshold=high_priority_threshold,
        overbooking_tolerance_pct=overbooking_tolerance_pct,
    )


def ensure_directory(path: str | Path) -> Path:
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    return target


def write_csv(df: pd.DataFrame, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
