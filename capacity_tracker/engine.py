from __future__ import annotations

import math
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

import pandas as pd
from dateutil.relativedelta import relativedelta

from .curves import resolve_curve
from .io_utils import MONTH_FMT
from .models import (
    PlanningConfig,
    Project,
    Person,
)

EPSILON = 1e-6
SMALL_PROJECT_EFFORT_THRESHOLD = 2.0


class UnschedulableProjectError(RuntimeError):
    def __init__(self, project: Project, reason: str) -> None:
        super().__init__(f"Project {project.id} unschedulable: {reason}")
        self.project = project
        self.reason = reason


@dataclass
class MonthlyState:
    ktlo_pct: float
    capacity_limit: float
    project_alloc_pct: float = 0.0
    allocations: Dict[str, Dict[str, float]] = field(default_factory=dict)

    def remaining_capacity(self) -> float:
        return self.capacity_limit - self.project_alloc_pct

    def assign(self, project_id: str, role: str, share: float, *, allow_overallocation: bool = False) -> None:
        if share <= 0:
            return
        remaining = self.remaining_capacity()
        if share > remaining + EPSILON and not allow_overallocation:
            raise ValueError("allocation exceeds remaining capacity")
        role_allocations = self.allocations.setdefault(project_id, {})
        role_allocations[role] = role_allocations.get(role, 0.0) + share
        self.project_alloc_pct += share

    def remove(self, project_id: str, role: str, share: float) -> None:
        if share <= 0:
            return
        role_allocations = self.allocations.get(project_id, {})
        current = role_allocations.get(role, 0.0)
        new_value = current - share
        if new_value <= EPSILON:
            role_allocations.pop(role, None)
            if not role_allocations:
                self.allocations.pop(project_id, None)
        else:
            role_allocations[role] = new_value
        self.project_alloc_pct = max(0.0, self.project_alloc_pct - share)

    @property
    def total_pct(self) -> float:
        return self.ktlo_pct + self.project_alloc_pct


def _first_of_month(value: date) -> date:
    return date(value.year, value.month, 1)


def _build_month_sequence(config: PlanningConfig) -> List[date]:
    start = _first_of_month(config.planning_start)
    months: List[date] = []
    if config.planning_end:
        end_month = _first_of_month(config.planning_end)
        current = start
        while current <= end_month:
            months.append(current)
            current += relativedelta(months=1)
    else:
        for offset in range(config.max_months_if_open_ended):
            months.append(start + relativedelta(months=offset))
    return months


def _projects_from_df(df: pd.DataFrame) -> List[Project]:
    projects: List[Project] = []
    for row in df.itertuples(index=False):
        priority_value = getattr(row, "priority", None)
        if isinstance(priority_value, float) and math.isnan(priority_value):
            priority_value = None
        required_skillsets = {
            "BA": tuple(getattr(row, "required_skillsets_ba", ()) or ()),
            "Planner": tuple(getattr(row, "required_skillsets_planner", ()) or ()),
            "Dev": tuple(getattr(row, "required_skillsets_dev", ()) or ()),
        }
        project = Project(
            id=str(row.id),
            name=str(row.name),
            effort_ba_pm=float(row.effort_ba_pm),
            effort_planner_pm=float(row.effort_planner_pm),
            effort_dev_pm=float(row.effort_dev_pm),
            parent_summary="" if pd.isna(row.parent_summary) else str(row.parent_summary),
            priority=str(priority_value) if priority_value is not None else None,
            input_row=int(row.input_row),
            required_skillsets=required_skillsets,
        )
        projects.append(project)
    projects.sort(key=lambda p: p.input_row)
    return projects


def _people_from_df(df: pd.DataFrame) -> List[Person]:
    people: List[Person] = []
    for row in df.itertuples(index=False):
        start_date = row.start_date if isinstance(row.start_date, date) else None
        end_date = row.end_date if isinstance(row.end_date, date) else None
        if not row.active:
            continue
        roles = tuple(row.roles) if isinstance(row.roles, (list, tuple)) else (str(row.roles),)
        skillsets = tuple(row.skillsets) if isinstance(row.skillsets, (list, tuple)) else ()
        preferred = (
            tuple(row.preferred_parent_summaries)
            if isinstance(row.preferred_parent_summaries, (list, tuple))
            else ()
        )
        person = Person(
            name=str(row.person),
            roles=tuple(str(role) for role in roles),
            active=bool(row.active),
            start_date=start_date,
            end_date=end_date,
            skillsets=tuple(str(skill) for skill in skillsets),
            preferred_parent_summaries=tuple(str(pref) for pref in preferred),
            notes="" if pd.isna(row.notes) else str(row.notes),
        )
        people.append(person)
    return people


def _is_person_available(person: Person, month_start: date) -> bool:
    if person.start_date and month_start < _first_of_month(person.start_date):
        return False
    if person.end_date and month_start > _first_of_month(person.end_date):
        return False
    return True


def _build_person_states(
    people: Sequence[Person],
    month_starts: Sequence[date],
    config: PlanningConfig,
) -> Tuple[
    Dict[str, Dict[int, MonthlyState]],
    Dict[str, Dict[int, List[str]]],
    Dict[str, List[float]],
    Dict[str, Set[str]],
    Dict[str, Set[str]],
    Dict[str, Set[str]],
    Dict[str, List[float]],
]:
    person_states: Dict[str, Dict[int, MonthlyState]] = {}
    available_by_role_month: Dict[str, Dict[int, List[str]]] = defaultdict(dict)
    role_month_capacity: Dict[str, List[float]] = {}
    person_skillsets: Dict[str, Set[str]] = {}
    person_preferences: Dict[str, Set[str]] = {}
    person_roles_map: Dict[str, Set[str]] = {}
    role_capacity_samples: Dict[str, List[float]] = defaultdict(list)
    for person in people:
        states: Dict[int, MonthlyState] = {}
        ktlo_pct = max(config.ktlo_for_role(role) for role in person.roles)
        base_capacity = max(0.0, 1.0 - ktlo_pct)
        per_role_capacity = base_capacity
        for idx, month_start in enumerate(month_starts):
            if not _is_person_available(person, month_start):
                continue
            project_capacity = per_role_capacity
            if project_capacity <= EPSILON:
                continue
            state = MonthlyState(ktlo_pct=ktlo_pct, capacity_limit=project_capacity)
            states[idx] = state
            for role in person.roles:
                available_by_role_month.setdefault(role, {}).setdefault(idx, []).append(person.name)
                if role not in role_month_capacity:
                    role_month_capacity[role] = [0.0] * len(month_starts)
                role_month_capacity[role][idx] += project_capacity
        if states:
            person_states[person.name] = states
            person_skillsets[person.name] = set(person.skillsets)
            person_preferences[person.name] = set(person.preferred_parent_summaries)
            person_roles_map[person.name] = set(person.roles)
            for role in person.roles:
                role_capacity_samples.setdefault(role, []).append(per_role_capacity)
    return (
        person_states,
        available_by_role_month,
        role_month_capacity,
        person_skillsets,
        person_preferences,
        person_roles_map,
        role_capacity_samples,
    )


def _effective_role_limits(
    role_month_capacity: Dict[str, List[float]],
    role_capacity_samples: Dict[str, List[float]],
    config: PlanningConfig,
) -> Dict[str, float]:
    limits: Dict[str, float] = {}
    for role in config.iter_roles():
        concurrency_limit = max(config.max_concurrent_for_role(role), 0)
        if concurrency_limit <= 0:
            limits[role] = 0.0
            continue
        aggregate_capacity = max(role_month_capacity.get(role, []) or [0.0])
        per_person_caps = sorted(role_capacity_samples.get(role, []), reverse=True)
        if concurrency_limit >= len(per_person_caps):
            per_person_sum = sum(per_person_caps)
        else:
            per_person_sum = sum(per_person_caps[:concurrency_limit])
        limit = min(float(concurrency_limit), aggregate_capacity, per_person_sum)
        if role == "Planner":
            limit = min(limit, config.planner_project_month_cap_pct)
        limits[role] = limit
    return limits


def _resolve_curve_for_role(config: PlanningConfig, role: str, duration: int) -> List[float]:
    if duration <= 0:
        return []
    curve_keys = {
        "Planner": ["planner_curve"],
        "BA": ["ba_curve", "dev_curve"],
        "Dev": ["dev_curve", "ba_curve"],
    }
    spec: object = "uniform"
    for key in curve_keys.get(role, []):
        try:
            spec = config.get_curve_spec(key)
            break
        except KeyError:
            continue
    return resolve_curve(spec, duration)


def _compute_monthly_demands(
    project: Project,
    duration: int,
    config: PlanningConfig,
    *,
    force_uniform: bool = False,
) -> Dict[str, List[float]]:
    demands: Dict[str, List[float]] = {}
    for role, effort in project.role_efforts().items():
        if effort <= EPSILON or duration <= 0:
            demands[role] = [0.0] * max(duration, 0)
            continue
        curve = resolve_curve("uniform", duration) if force_uniform else _resolve_curve_for_role(config, role, duration)
        demands[role] = [share * effort for share in curve]
    return demands


def _monthly_demands_within_limits(
    demands: Dict[str, List[float]],
    limits: Dict[str, float],
) -> bool:
    for role, monthly_values in demands.items():
        limit = limits.get(role, 0.0)
        for value in monthly_values:
            if value > limit + EPSILON:
                return False
    return True


def _format_available(detail_available: List[Dict[str, object]]) -> str:
    if not detail_available:
        return "none"
    formatted = []
    for entry in detail_available:
        name = entry.get("name", "")
        capacity = float(entry.get("capacity", 0.0))
        skills = entry.get("skills")
        if isinstance(skills, (list, tuple)) and skills:
            skills_label = ", ".join(str(skill) for skill in skills)
            formatted.append(f"{name} ({capacity:.2f} free; skills: {skills_label})")
        else:
            formatted.append(f"{name} ({capacity:.2f} free)")
    return ", ".join(formatted)


def _describe_failure(
    contexts: List[Dict[str, object]],
    month_keys: Sequence[str],
) -> Tuple[str, Optional[Dict[str, object]]]:
    if not contexts:
        return "insufficient capacity within planning window", None
    selected = max(
        contexts,
        key=lambda ctx: (
            float(ctx.get("shortfall") or ctx.get("demand") or 0.0),
            -ctx.get("month_idx", 0),
        ),
    )
    selected = dict(selected)
    month_idx = selected.get("month_idx")
    if isinstance(month_idx, int) and 0 <= month_idx < len(month_keys):
        month_label = month_keys[month_idx]
    else:
        month_label = selected.get("month_label", "n/a")
    role = selected.get("role", "Unknown")
    reason_code = selected.get("reason", "insufficient_capacity")
    available = selected.get("available", [])
    shortfall = float(selected.get("shortfall") or selected.get("demand") or 0.0)
    if reason_code == "no_available_people":
        reason = f"{role} unavailable in {month_label} (no active resources)"
    elif reason_code == "no_capacity_remaining":
        reason = f"{role} has no remaining capacity in {month_label}; available roster: {_format_available(available)}"
    elif reason_code == "skillset_unavailable":
        needed = selected.get("needed_skillsets", [])
        needed_label = ", ".join(needed) if needed else "unspecified"
        reason = f"{role} lacks required skillsets ({needed_label}) in {month_label}"
    elif reason_code == "skillset_uncovered":
        missing = selected.get("missing_skillsets", {})
        if isinstance(missing, dict) and missing:
            parts = []
            for key, value in missing.items():
                part = f"{key}: {', '.join(value)}" if value else key
                parts.append(part)
            missing_label = "; ".join(parts)
        else:
            missing_label = "unspecified"
        reason = f"{role} skillset coverage incomplete ({missing_label})"
    elif reason_code == "concurrency_limit":
        reason = (
            f"{role} concurrency limit reached in {month_label}; "
            f"available roster: {_format_available(available)}"
        )
    elif reason_code == "concurrency_limit_zero":
        reason = f"{role} concurrency limit is zero; adjust configuration or roster"
    else:
        reason = (
            f"{role} shortfall {shortfall:.2f} PM in {month_label}; "
            f"available capacity: {_format_available(available)}"
        )
    selected["reason_code"] = reason_code
    selected["month_label"] = month_label
    selected["shortfall"] = shortfall
    return reason, selected


def _role_set(roles: Iterable[str]) -> Dict[str, Set[str]]:
    return {role: set() for role in roles}


def _role_totals(roles: Iterable[str]) -> Dict[str, float]:
    return {role: 0.0 for role in roles}


def _candidate_sort_key(
    name: str,
    role: str,
    state: MonthlyState,
    role_people: Dict[str, set],
    random_order: Dict[str, float],
    covers_needed: bool,
    pref_match: bool,
) -> Tuple[int, int, int, float, str, float]:
    return (
        0 if covers_needed else 1,
        0 if name in role_people[role] else 1,
        0 if pref_match else 1,
        state.total_pct,
        name,
        random_order.get(name, 0.0),
    )


def _allocate_month(
    project_id: str,
    role: str,
    month_idx: int,
    demand: float,
    role_people: Dict[str, set],
    available_by_role_month: Dict[str, Dict[int, List[str]]],
    person_states: Dict[str, Dict[int, MonthlyState]],
    random_order: Dict[str, float],
    required_skillsets: Set[str],
    needed_skillsets: Set[str],
    person_skillsets: Dict[str, Set[str]],
    person_preferences: Dict[str, Set[str]],
    parent_summary: str,
    max_assignments: int,
    planner_month_cap: float,
    is_high_priority: bool = False,
    overbooking_tolerance: float = 0.0,
    aggressive_mode: bool = False,
) -> Tuple[bool, List[Tuple[str, int, str, float]], Optional[Dict[str, object]]]:
    assignments: List[Tuple[str, int, str, float]] = []
    if max_assignments <= 0:
        detail = {
            "role": role,
            "month_idx": month_idx,
            "demand": demand,
            "available": [],
            "allocations": [],
            "reason": "concurrency_limit_zero",
            "needed_skillsets": sorted(needed_skillsets),
        }
        # In aggressive mode, track the issue but don't fail
        if aggressive_mode:
            detail["aggressive_override"] = True
            return True, assignments, detail
        return False, assignments, detail
    candidates = available_by_role_month.get(role, {}).get(month_idx, [])
    if not candidates:
        detail = {
            "role": role,
            "month_idx": month_idx,
            "demand": demand,
            "available": [],
            "allocations": [],
            "reason": "no_available_people",
            "needed_skillsets": sorted(needed_skillsets),
        }
        # In aggressive mode, track the issue but don't fail
        if aggressive_mode:
            detail["aggressive_override"] = True
            return True, assignments, detail
        return False, assignments, detail
    candidate_entries: List[Dict[str, object]] = []
    detail_available: List[Dict[str, object]] = []
    for name in candidates:
        state = person_states.get(name, {}).get(month_idx)
        if state is None:
            continue
        remaining_capacity = state.remaining_capacity()
        skills = person_skillsets.get(name, set())
        matches_required = not required_skillsets or bool(skills & required_skillsets)
        covers_needed = bool(needed_skillsets and (skills & needed_skillsets))
        pref_match = parent_summary and parent_summary in person_preferences.get(name, set())
        detail_available.append(
            {
                "name": name,
                "capacity": round(remaining_capacity, 4),
                "skills": sorted(skills),
                "matches_required": matches_required,
            }
        )
        # In aggressive mode, include candidates even without skill match or capacity
        if aggressive_mode:
            if remaining_capacity > EPSILON or not matches_required:
                candidate_entries.append(
                    {
                        "name": name,
                        "state": state,
                        "covers_needed": covers_needed or not needed_skillsets,
                        "pref_match": pref_match,
                        "skills": skills,
                        "skill_mismatch": not matches_required,
                    }
                )
        else:
            if remaining_capacity <= EPSILON or not matches_required:
                continue
            candidate_entries.append(
                {
                    "name": name,
                    "state": state,
                    "covers_needed": covers_needed or not needed_skillsets,
                    "pref_match": pref_match,
                    "skills": skills,
                }
            )
    if not candidate_entries:
        # In aggressive mode, if we have no candidates with capacity/skills, add everyone anyway
        if aggressive_mode and candidates:
            for name in candidates:
                state = person_states.get(name, {}).get(month_idx)
                if state is None:
                    continue
                skills = person_skillsets.get(name, set())
                matches_required = not required_skillsets or bool(skills & required_skillsets)
                covers_needed = bool(needed_skillsets and (skills & needed_skillsets))
                pref_match = parent_summary and parent_summary in person_preferences.get(name, set())
                candidate_entries.append(
                    {
                        "name": name,
                        "state": state,
                        "covers_needed": covers_needed or not needed_skillsets,
                        "pref_match": pref_match,
                        "skills": skills,
                        "skill_mismatch": not matches_required,
                    }
                )

        if not candidate_entries:
            if required_skillsets and not any(item.get("matches_required") for item in detail_available):
                reason_code = "skillset_unavailable"
            else:
                reason_code = "no_capacity_remaining"
            detail = {
                "role": role,
                "month_idx": month_idx,
                "demand": demand,
                "available": detail_available,
                "allocations": [],
                "reason": reason_code,
                "needed_skillsets": sorted(needed_skillsets),
            }
            # In aggressive mode, don't fail - just track the issue
            if aggressive_mode:
                detail["aggressive_override"] = True
            else:
                return False, assignments, detail
    candidate_entries.sort(
        key=lambda item: _candidate_sort_key(
            item["name"],
            role,
            item["state"],
            role_people,
            random_order,
            bool(item["covers_needed"]),
            bool(item["pref_match"]),
        )
    )
    remaining = demand
    allocation_details: List[Dict[str, object]] = []
    assigned_names: Set[str] = set()
    limit_blocked = False
    for item in candidate_entries:
        name = item["name"]
        state = item["state"]
        if remaining <= EPSILON:
            break
        already_assigned = name in assigned_names
        if not already_assigned and len(assigned_names) >= max_assignments:
            limit_blocked = True
            continue
        available = state.remaining_capacity()
        # In aggressive mode, assign even if no capacity, use demand instead
        if aggressive_mode and available <= EPSILON:
            share = min(remaining, 0.1)  # Assign at least 10% or remaining demand
            if role == "Planner":
                share = min(share, planner_month_cap)
        else:
            if available <= EPSILON:
                continue
            share = min(available, remaining)
            if role == "Planner":
                share = min(share, planner_month_cap)
            if share <= EPSILON:
                continue
        state.assign(project_id, role, share, allow_overallocation=aggressive_mode)
        assignments.append((name, month_idx, role, share))
        role_people[role].add(name)
        if not already_assigned and share > EPSILON:
            assigned_names.add(name)
        allocation_details.append(
            {
                "name": name,
                "share": round(share, 4),
                "capacity_used": round(available, 4),
                "skills": sorted(person_skillsets.get(name, set())),
            }
        )
        remaining -= share

    # Check if remaining shortfall is acceptable
    # For high-priority projects, allow overbooking up to tolerance threshold
    acceptable_shortfall = demand * overbooking_tolerance if is_high_priority else EPSILON

    if remaining > acceptable_shortfall:
        detail = {
            "role": role,
            "month_idx": month_idx,
            "demand": demand,
            "available": detail_available,
            "allocations": allocation_details,
            "reason": "concurrency_limit" if limit_blocked else "insufficient_capacity",
            "shortfall": remaining,
            "needed_skillsets": sorted(needed_skillsets),
        }
        # In aggressive mode, always succeed but track the issue
        if aggressive_mode:
            detail["aggressive_override"] = True
            return True, assignments, detail
        return False, assignments, detail
    return True, assignments, None


def _rollback_assignments(
    project_id: str,
    assignments: Iterable[Tuple[str, int, str, float]],
    person_states: Dict[str, Dict[int, MonthlyState]],
) -> None:
    for name, month_idx, role, share in reversed(list(assignments)):
        state = person_states[name][month_idx]
        state.remove(project_id, role, share)


def _format_people(names: Iterable[str]) -> str:
    unique = sorted(set(names))
    return ";".join(unique)


def analyze_hiring_needs(
    allocation_issues: List[Dict[str, object]],
    role_month_capacity: Dict[str, List[float]],
    person_states: Dict[str, Dict[int, MonthlyState]],
    month_keys: Sequence[str],
    cfg: PlanningConfig,
) -> Dict[str, object]:
    """
    Analyze allocation issues to generate hiring recommendations.
    Returns a structured report with:
    - Summary statistics
    - Over-allocation by role and time period
    - Specific hiring recommendations
    - Capacity vs demand data for charts
    """
    from collections import defaultdict

    # Aggregate over-allocations by role and month
    overalloc_by_role_month: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    skill_bottlenecks: List[Dict[str, object]] = []

    for issue in allocation_issues:
        issue_type = issue.get("type", "unknown")

        if issue_type == "overallocation":
            role = issue.get("role", "Unknown")
            month_label = issue.get("month_label", "")
            overalloc_pct = float(issue.get("overallocation_pct", 0.0))
            overalloc_by_role_month[role][month_label] += overalloc_pct

        elif issue.get("aggressive_override"):
            # Track skill/capacity bottlenecks
            skill_bottlenecks.append({
                "project_id": issue.get("project_id"),
                "project_name": issue.get("project_name"),
                "role": issue.get("role"),
                "month_label": issue.get("month_label"),
                "reason": issue.get("reason"),
                "shortfall": issue.get("shortfall", 0.0),
                "needed_skillsets": issue.get("needed_skillsets", []),
            })

    # Calculate capacity vs demand by role over time
    capacity_vs_demand: Dict[str, List[Dict[str, object]]] = {}
    for role in cfg.iter_roles():
        role_data: List[Dict[str, object]] = []
        capacities = role_month_capacity.get(role, [])

        for month_idx, month_label in enumerate(month_keys):
            capacity = capacities[month_idx] if month_idx < len(capacities) else 0.0
            # Calculate role-specific demand from person_states
            demand = 0.0
            for person_name, states in person_states.items():
                state = states.get(month_idx)
                if state:
                    # Sum allocations for this specific role across all projects
                    for project_id, role_shares in state.allocations.items():
                        demand += role_shares.get(role, 0.0)

            overalloc = overalloc_by_role_month[role].get(month_label, 0.0)

            role_data.append({
                "month": month_label,
                "capacity": round(capacity, 2),
                "demand": round(demand, 2),
                "gap": round(demand - capacity, 2),
                "overallocation": round(overalloc, 2),
            })

        capacity_vs_demand[role] = role_data

    # Generate hiring recommendations
    recommendations: List[Dict[str, object]] = []
    for role, month_data in overalloc_by_role_month.items():
        if not month_data:
            continue

        # Find peak over-allocation
        peak_month = max(month_data.items(), key=lambda x: x[1])
        peak_month_label = peak_month[0]
        peak_overalloc = peak_month[1]

        # Calculate total shortfall
        total_shortfall = sum(month_data.values())
        avg_shortfall = total_shortfall / len(month_data) if month_data else 0.0

        # Determine number of hires needed (rough estimate)
        ktlo = cfg.ktlo_for_role(role)
        effective_capacity_per_person = 1.0 - ktlo
        hires_needed = max(1, math.ceil(avg_shortfall / effective_capacity_per_person))

        # Find skills needed for this role from bottlenecks
        needed_skills: Set[str] = set()
        for bottleneck in skill_bottlenecks:
            if bottleneck.get("role") == role:
                skills = bottleneck.get("needed_skillsets", [])
                needed_skills.update(skills)

        recommendations.append({
            "role": role,
            "hires_needed": hires_needed,
            "peak_month": peak_month_label,
            "peak_overallocation_pct": round(peak_overalloc * 100, 1),
            "avg_shortfall_pm": round(avg_shortfall, 2),
            "total_shortfall_pm": round(total_shortfall, 2),
            "needed_skills": sorted(needed_skills),
            "affected_months": sorted(month_data.keys()),
        })

    # Sort recommendations by severity (total shortfall)
    recommendations.sort(key=lambda x: x["total_shortfall_pm"], reverse=True)

    return {
        "summary": {
            "total_roles_affected": len(overalloc_by_role_month),
            "total_bottlenecks": len(skill_bottlenecks),
            "total_recommendations": len(recommendations),
        },
        "recommendations": recommendations,
        "capacity_vs_demand": capacity_vs_demand,
        "skill_bottlenecks": skill_bottlenecks,
    }


def plan(
    projects_df: pd.DataFrame,
    people_df: pd.DataFrame,
    cfg: PlanningConfig,
    *,
    strict: bool = False,
) -> Tuple[pd.DataFrame, pd.DataFrame, Optional[Dict[str, object]]]:
    roles = tuple(cfg.iter_roles())
    projects = _projects_from_df(projects_df)
    people = _people_from_df(people_df)
    month_starts = _build_month_sequence(cfg)
    if not month_starts:
        raise ValueError("planning window does not span any months")
    (
        person_states,
        available_by_role_month,
        role_month_capacity,
        person_skillsets,
        person_preferences,
        person_roles_map,
        role_capacity_samples,
    ) = _build_person_states(people, month_starts, cfg)
    effective_limits = _effective_role_limits(role_month_capacity, role_capacity_samples, cfg)
    month_keys = [month.strftime(MONTH_FMT) for month in month_starts]
    rng_seed = cfg.random_seed if cfg.random_seed is not None else 0
    rng = random.Random(rng_seed)
    random_order = {name: rng.random() for name in sorted(person_states)}

    scheduled_records: List[Dict[str, object]] = []
    skipped_projects: List[Dict[str, object]] = []
    allocation_issues: List[Dict[str, object]] = []  # Track issues for aggressive mode

    aggressive_mode = cfg.allocation_mode == "aggressive"

    # Sort projects by priority if enabled (lower priority number = higher priority)
    if cfg.priority_based_scheduling:
        def priority_key(p):
            if p.priority is None:
                return (float('inf'), p.input_row)
            try:
                priority_val = int(p.priority) if isinstance(p.priority, str) else p.priority
                return (priority_val, p.input_row)
            except (ValueError, TypeError):
                return (float('inf'), p.input_row)
        projects = sorted(projects, key=priority_key)

    for project in projects:
        efforts = project.role_efforts()
        total_effort = project.total_effort()
        use_uniform_curve = total_effort <= SMALL_PROJECT_EFFORT_THRESHOLD + EPSILON
        required_skillsets_map = {
            role: set(project.skillsets_for_role(role)) for role in roles
        }
        # Determine if this is a high-priority project eligible for overbooking
        is_high_priority = False
        if project.priority is not None:
            try:
                priority_val = int(project.priority) if isinstance(project.priority, str) else project.priority
                is_high_priority = priority_val <= cfg.high_priority_threshold
            except (ValueError, TypeError):
                pass
        if not project.has_demand():
            scheduled_records.append(
                {
                    "project": project,
                    "start_idx": 0,
                    "duration": 1,
                    "role_people": _role_set(roles),
                    "role_totals": _role_totals(roles),
                }
            )
            continue
        role_min_durations: Dict[str, int] = {}
        failure_contexts: List[Dict[str, object]] = []
        for role, effort in efforts.items():
            if effort <= EPSILON:
                role_min_durations[role] = 0
                continue
            effective_limit = effective_limits.get(role, 0.0)
            if effective_limit <= EPSILON:
                reason = f"no available capacity for role {role}"
                if strict:
                    raise UnschedulableProjectError(project, reason)
                skipped_projects.append(
                    {
                        "id": project.id,
                        "name": project.name,
                        "reason": reason,
                        "detail": {
                            "reason_code": "no_role_capacity",
                            "role": role,
                            "required_skillsets": sorted(required_skillsets_map.get(role, set())),
                        },
                    }
                )
                break
            min_duration = max(1, math.ceil(effort / max(effective_limit, EPSILON)))
            role_min_durations[role] = min_duration
        else:
            base_duration = max(role_min_durations.values(), default=1)
            duration = max(1, base_duration)
            while True:
                if duration > len(month_starts):
                    reason = "duration exceeds planning window"
                    if strict:
                        raise UnschedulableProjectError(project, reason)
                    skipped_projects.append(
                        {
                            "id": project.id,
                            "name": project.name,
                            "reason": reason,
                            "detail": {"reason_code": "duration_too_long", "duration": duration},
                        }
                    )
                    break
                monthly_demands = _compute_monthly_demands(
                    project,
                    duration,
                    cfg,
                    force_uniform=use_uniform_curve,
                )
                if _monthly_demands_within_limits(monthly_demands, effective_limits):
                    break
                duration += 1
            else:
                continue
            if skipped_projects and skipped_projects[-1].get("id") == project.id:
                continue
            latest_start_idx = len(month_starts) - duration
            if latest_start_idx < 0:
                reason = "project does not fit within planning horizon"
                if strict:
                    raise UnschedulableProjectError(project, reason)
                skipped_projects.append(
                    {
                        "id": project.id,
                        "name": project.name,
                        "reason": reason,
                        "detail": {"reason_code": "window_exhausted"},
                    }
                )
                continue
            placed = False
            for start_idx in range(latest_start_idx + 1):
                assignments_record: List[Tuple[str, int, str, float]] = []
                role_people = _role_set(roles)
                role_totals = _role_totals(roles)
                role_skillset_coverage = {role_key: set() for role_key in roles}
                for offset in range(duration):
                    month_idx = start_idx + offset
                    for role, monthly_values in monthly_demands.items():
                        demand = monthly_values[offset] if offset < len(monthly_values) else 0.0
                        if demand <= EPSILON:
                            continue
                        required_skillsets = required_skillsets_map.get(role, set())
                        needed_skillsets = required_skillsets - role_skillset_coverage[role]
                        # For high-priority projects, increase concurrency limit to be more aggressive
                        max_concurrent = cfg.max_concurrent_for_role(role)
                        if is_high_priority:
                            max_concurrent = max(max_concurrent * 2, max_concurrent + 1)
                        success, assignments, failure_detail = _allocate_month(
                            project.id,
                            role,
                            month_idx,
                            demand,
                            role_people,
                            available_by_role_month,
                            person_states,
                            random_order,
                            required_skillsets,
                            needed_skillsets,
                            person_skillsets,
                            person_preferences,
                            project.parent_summary,
                            max_concurrent,
                            cfg.planner_project_month_cap_pct,
                            is_high_priority,
                            cfg.overbooking_tolerance_pct,
                            aggressive_mode,
                        )
                        # Track issues in aggressive mode
                        if aggressive_mode and failure_detail and failure_detail.get("aggressive_override"):
                            allocation_issues.append({
                                "project_id": project.id,
                                "project_name": project.name,
                                "role": role,
                                "month_idx": month_idx,
                                "month_label": month_keys[month_idx],
                                **failure_detail,
                            })
                        assignments_record.extend(assignments)
                        if not success:
                            _rollback_assignments(project.id, assignments_record, person_states)
                            assignments_record.clear()
                            role_people = _role_set(roles)
                            role_totals = _role_totals(roles)
                            role_skillset_coverage = {role_key: set() for role_key in roles}
                            if failure_detail:
                                failure_contexts.append(
                                    {
                                        **failure_detail,
                                        "project_id": project.id,
                                        "start_idx": start_idx,
                                    }
                                )
                            break
                        for name, _, assignment_role, share in assignments:
                            role_totals[assignment_role] += share
                            if required_skillsets and assignment_role == role:
                                role_skillset_coverage[role].update(
                                    person_skillsets.get(name, set()) & required_skillsets
                                )
                    else:
                        continue
                    break
                else:
                    totals_ok = True
                    for role, effort in efforts.items():
                        if effort <= EPSILON:
                            continue
                        if abs(role_totals[role] - effort) > 1e-3:
                            totals_ok = False
                            break
                    if not totals_ok:
                        _rollback_assignments(project.id, assignments_record, person_states)
                        assignments_record.clear()
                        continue
                    missing_coverage = {
                        role_key: sorted(
                            required_skillsets_map[role_key] - role_skillset_coverage[role_key]
                        )
                        for role_key in roles
                        if required_skillsets_map[role_key]
                        and not required_skillsets_map[role_key].issubset(
                            role_skillset_coverage[role_key]
                        )
                    }
                    if missing_coverage:
                        _rollback_assignments(project.id, assignments_record, person_states)
                        assignments_record.clear()
                        failure_contexts.append(
                            {
                                "project_id": project.id,
                                "role": ";".join(sorted(missing_coverage)),
                                "reason": "skillset_uncovered",
                                "missing_skillsets": missing_coverage,
                            }
                        )
                        continue
                    scheduled_records.append(
                        {
                            "project": project,
                            "start_idx": start_idx,
                            "duration": duration,
                            "role_people": role_people,
                            "role_totals": role_totals,
                        }
                    )
                    placed = True
                    break
                if placed:
                    break
            if not placed:
                detail_reason, detail = _describe_failure(failure_contexts, month_keys)
                if strict:
                    raise UnschedulableProjectError(project, detail_reason)
                skipped_projects.append(
                    {
                        "id": project.id,
                        "name": project.name,
                        "reason": detail_reason,
                        "detail": detail,
                    }
                )

    timeline_rows: List[Dict[str, object]] = []
    for record in scheduled_records:
        project: Project = record["project"]  # type: ignore[assignment]
        start_idx: int = record["start_idx"]  # type: ignore[assignment]
        duration: int = record["duration"]  # type: ignore[assignment]
        role_people: Dict[str, set] = record["role_people"]  # type: ignore[assignment]
        role_totals: Dict[str, float] = record["role_totals"]  # type: ignore[assignment]
        end_idx = start_idx + duration - 1
        end_idx = min(end_idx, len(month_starts) - 1)
        timeline_rows.append(
            {
                "id": project.id,
                "name": project.name,
                "parent_summary": project.parent_summary,
                "start_month": month_keys[start_idx],
                "end_month": month_keys[end_idx],
                "duration_months": duration,
                "ba_persons": _format_people(role_people.get("BA", [])),
                "planner_persons": _format_people(role_people.get("Planner", [])),
                "dev_persons": _format_people(role_people.get("Dev", [])),
                "effort_ba_pm": round(role_totals.get("BA", 0.0), 4),
                "effort_planner_pm": round(role_totals.get("Planner", 0.0), 4),
                "effort_dev_pm": round(role_totals.get("Dev", 0.0), 4),
                "priority": project.priority,
                "input_row": project.input_row,
            }
        )

    project_timeline_df = pd.DataFrame(timeline_rows, columns=[
        "id",
        "name",
        "parent_summary",
        "start_month",
        "end_month",
        "duration_months",
        "ba_persons",
        "planner_persons",
        "dev_persons",
        "effort_ba_pm",
        "effort_planner_pm",
        "effort_dev_pm",
        "priority",
        "input_row",
    ])

    project_name_lookup: Dict[str, str] = {}
    for record in scheduled_records:
        project: Project = record["project"]  # type: ignore[assignment]
        project_name_lookup[project.id] = project.name

    capacity_rows: List[Dict[str, object]] = []
    for name in sorted(person_states):
        states = person_states[name]
        for month_idx, state in sorted(states.items()):
            total_pct = state.total_pct
            # In aggressive mode, allow over-allocation and track it
            if total_pct > 1.0 + EPSILON:
                if aggressive_mode:
                    person_roles = person_roles_map.get(name, set())
                    for role_name in person_roles:
                        allocation_issues.append({
                            "type": "overallocation",
                            "person": name,
                            "role": role_name,
                            "month_idx": month_idx,
                            "month_label": month_keys[month_idx],
                            "allocated_pct": total_pct,
                            "overallocation_pct": total_pct - 1.0,
                        })
                else:
                    raise ValueError(f"allocation exceeds capacity for {name} in {month_keys[month_idx]}")
            allocations_map = state.allocations
            month_label = month_keys[month_idx]
            ktlo_value = round(state.ktlo_pct, 4)
            total_value = round(total_pct, 4)
            # Record KTLO load as a dedicated row.
            capacity_rows.append(
                {
                    "person": name,
                    "role": "",
                    "project_id": "",
                    "project_name": "KTLO",
                    "month": month_label,
                    "project_alloc_pct": ktlo_value,
                    "total_pct": total_value,
                }
            )
            if allocations_map:
                for project_id in sorted(allocations_map):
                    role_shares = allocations_map[project_id]
                    for assignment_role, alloc in sorted(role_shares.items()):
                        capacity_rows.append(
                            {
                                "person": name,
                                "role": assignment_role,
                                "project_id": project_id,
                                "project_name": project_name_lookup.get(project_id, project_id),
                                "month": month_label,
                                "project_alloc_pct": round(alloc, 4),
                                "total_pct": total_value,
                            }
                        )

    resource_capacity_df = pd.DataFrame(
        capacity_rows,
        columns=[
            "person",
            "role",
            "project_id",
            "project_name",
            "month",
            "project_alloc_pct",
            "total_pct",
        ],
    )
    resource_capacity_df.attrs["skipped_projects"] = skipped_projects
    resource_capacity_df.attrs["allocation_issues"] = allocation_issues

    # Analyze hiring needs if in aggressive mode
    hiring_analysis: Optional[Dict[str, object]] = None
    if aggressive_mode and allocation_issues:
        hiring_analysis = analyze_hiring_needs(
            allocation_issues,
            role_month_capacity,
            person_states,
            month_keys,
            cfg,
        )

    return project_timeline_df, resource_capacity_df, hiring_analysis
