from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Iterable, Optional, Sequence, Tuple


Role = str


ROLE_CONCURRENCY_LIMITS: Dict[Role, float] = {"BA": 1.0, "Planner": 1.0, "Dev": 2.0}


@dataclass(frozen=True)
class Project:
    """Repository representation of a project row."""

    id: str
    name: str
    effort_ba_pm: float
    effort_planner_pm: float
    effort_dev_pm: float
    parent_summary: str
    priority: Optional[str]
    input_row: int
    required_skillsets: Dict[Role, Tuple[str, ...]]

    def role_efforts(self) -> Dict[Role, float]:
        return {
            "BA": self.effort_ba_pm,
            "Planner": self.effort_planner_pm,
            "Dev": self.effort_dev_pm,
        }

    def has_demand(self) -> bool:
        return any(value > 0 for value in self.role_efforts().values())

    def skillsets_for_role(self, role: Role) -> Tuple[str, ...]:
        return self.required_skillsets.get(role, ())

    def total_effort(self) -> float:
        return sum(self.role_efforts().values())


@dataclass(frozen=True)
class Person:
    """Person roster entry with optional availability window."""

    name: str
    roles: Tuple[Role, ...]
    active: bool
    start_date: Optional[date]
    end_date: Optional[date]
    skillsets: Tuple[str, ...]
    preferred_parent_summaries: Tuple[str, ...] = ()
    notes: str = ""

    def availability_within(
        self, planning_start: date, planning_end: date
    ) -> Optional[Tuple[date, date]]:
        if not self.active:
            return None
        window_start = max(planning_start, self.start_date) if self.start_date else planning_start
        window_end = min(planning_end, self.end_date) if self.end_date else planning_end
        if window_start > window_end:
            return None
        return window_start, window_end


@dataclass(frozen=True)
class PlanningConfig:
    planning_start: date
    planning_end: Optional[date]
    max_months_if_open_ended: int
    ktlo_pct_by_role: Dict[Role, float]
    planner_project_month_cap_pct: float
    curves: Dict[str, object]
    random_seed: Optional[int]
    logging_level: str = "INFO"
    max_concurrent_per_role: Dict[Role, int] = field(
        default_factory=lambda: {role: int(limit) for role, limit in ROLE_CONCURRENCY_LIMITS.items()}
    )
    priority_based_scheduling: bool = True
    high_priority_threshold: int = 10
    overbooking_tolerance_pct: float = 0.20

    def get_curve_spec(self, key: str) -> object:
        if key not in self.curves:
            raise KeyError(f"curve '{key}' missing in configuration")
        return self.curves[key]

    def ktlo_for_role(self, role: Role) -> float:
        return self.ktlo_pct_by_role.get(role, 0.0)

    def iter_roles(self) -> Iterable[Role]:
        return self.max_concurrent_per_role.keys()

    def max_concurrent_for_role(self, role: Role) -> int:
        return int(self.max_concurrent_per_role.get(role, 0))
