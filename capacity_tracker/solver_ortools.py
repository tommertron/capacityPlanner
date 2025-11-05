"""
OR-Tools based constraint programming solver for capacity planning.

This module implements a multi-pass optimization approach:
1. Pass 1 (Strict): Try to schedule all projects within constraints
2. Pass 2 (Relaxed): Allow constraint violations but track them for recommendations

Violations tracked:
- Over-allocation (people scheduled beyond 100% capacity)
- Skill mismatches (people assigned to tasks outside their skillsets)
- Timeline extensions (projects scheduled beyond planning window)
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Set, Tuple

from ortools.sat.python import cp_model
import pandas as pd
from dateutil.relativedelta import relativedelta

from .models import PlanningConfig, Project, Person
from .io_utils import MONTH_FMT


@dataclass
class Violation:
    """Represents a constraint violation in the relaxed solution."""
    violation_type: str  # "over_allocation", "skill_mismatch", "timeline_extension"
    person: Optional[str] = None
    project_id: Optional[str] = None
    month: Optional[str] = None
    role: Optional[str] = None
    severity: float = 0.0  # How severe (e.g., 1.2 = 120% allocated)
    required_skills: List[str] = field(default_factory=list)
    actual_skills: List[str] = field(default_factory=list)
    description: str = ""


@dataclass
class SolverResult:
    """Result from OR-Tools solver including violations and recommendations."""
    success: bool
    solution_type: str  # "strict", "relaxed", "failed"
    scheduled_projects: List[Dict]
    unscheduled_projects: List[Dict]
    violations: List[Violation]
    resource_timeline: pd.DataFrame
    recommendations: Dict[str, object]


class CapacityPlannerModel:
    """OR-Tools CP-SAT model for capacity planning."""

    def __init__(
        self,
        projects: List[Project],
        people: List[Person],
        config: PlanningConfig,
        month_starts: List[date],
    ):
        self.projects = projects
        self.people = people
        self.config = config
        self.month_starts = month_starts
        self.horizon = len(month_starts)

        # Build person metadata
        self.person_by_name = {p.name: p for p in people}
        self.person_roles = {p.name: set(p.roles) for p in people}
        self.person_skills = {p.name: set(p.skillsets) for p in people}
        self.person_availability = self._build_availability_map()

        # Model and variables
        self.model = cp_model.CpModel()
        self.task_vars = {}  # (project_id, role, person) -> task variables
        self.assignment_vars = {}  # (project_id, role, person) -> BoolVar
        self.project_start_vars = {}  # project_id -> IntVar
        self.project_end_vars = {}  # project_id -> IntVar

        # Violation tracking variables (for relaxed mode)
        self.over_allocation_vars = {}  # (person, month) -> IntVar (excess %)
        self.skill_mismatch_vars = {}  # (project_id, role, person) -> BoolVar

    def _build_availability_map(self) -> Dict[str, Set[int]]:
        """Build map of person -> set of available month indices."""
        availability = {}
        for person in self.people:
            available_months = set()
            for month_idx, month_start in enumerate(self.month_starts):
                if person.start_date and month_start < self._first_of_month(person.start_date):
                    continue
                if person.end_date and month_start > self._first_of_month(person.end_date):
                    continue
                available_months.add(month_idx)
            availability[person.name] = available_months
        return availability

    @staticmethod
    def _first_of_month(d: date) -> date:
        return date(d.year, d.month, 1)

    def build_strict_model(self):
        """Build model with strict constraints (no violations allowed)."""
        self._create_task_variables()
        self._add_assignment_constraints()
        self._add_capacity_constraints(allow_violations=False)
        self._add_skill_constraints(allow_violations=False)
        self._add_precedence_constraints()
        self._set_objective()

    def build_relaxed_model(self):
        """Build model allowing violations (with penalties)."""
        self._create_task_variables()
        self._add_assignment_constraints()
        self._add_capacity_constraints(allow_violations=True)
        self._add_skill_constraints(allow_violations=True)
        self._add_precedence_constraints()
        self._set_objective_with_penalties()

    def _create_task_variables(self):
        """Create decision variables for task assignments."""
        for project in self.projects:
            project_efforts = project.role_efforts()

            # Project-level start/end time
            self.project_start_vars[project.id] = self.model.NewIntVar(
                0, self.horizon - 1, f'project_start_{project.id}'
            )
            self.project_end_vars[project.id] = self.model.NewIntVar(
                0, self.horizon, f'project_end_{project.id}'
            )

            for role, effort_pm in project_efforts.items():
                if effort_pm < 0.01:
                    continue

                # Calculate minimum duration for this role
                # Assuming max 1.0 person-month per month per person
                min_duration = max(1, math.ceil(effort_pm))
                max_duration = min(self.horizon, min_duration * 3)  # Allow up to 3x spreading

                required_skills = set(project.skillsets_for_role(role))

                for person in self.people:
                    # Check if person has this role
                    if role not in person.roles:
                        continue

                    person_name = person.name

                    # Assignment boolean: Is this person assigned to this project-role?
                    assignment_var = self.model.NewBoolVar(
                        f'assign_{project.id}_{role}_{person_name}'
                    )
                    self.assignment_vars[(project.id, role, person_name)] = assignment_var

                    # If assigned, create interval variable for the task
                    start_var = self.model.NewIntVar(
                        0, self.horizon - 1,
                        f'start_{project.id}_{role}_{person_name}'
                    )
                    duration_var = self.model.NewIntVar(
                        min_duration, max_duration,
                        f'duration_{project.id}_{role}_{person_name}'
                    )
                    end_var = self.model.NewIntVar(
                        min_duration, self.horizon,
                        f'end_{project.id}_{role}_{person_name}'
                    )

                    # Create optional interval (only exists if assigned)
                    interval_var = self.model.NewOptionalIntervalVar(
                        start_var, duration_var, end_var,
                        assignment_var,
                        f'interval_{project.id}_{role}_{person_name}'
                    )

                    self.task_vars[(project.id, role, person_name)] = {
                        'assignment': assignment_var,
                        'start': start_var,
                        'duration': duration_var,
                        'end': end_var,
                        'interval': interval_var,
                        'effort_pm': effort_pm,
                        'required_skills': required_skills,
                    }

    def _add_assignment_constraints(self):
        """Ensure each project-role is assigned to at least one person."""
        for project in self.projects:
            for role, effort_pm in project.role_efforts().items():
                if effort_pm < 0.01:
                    continue

                # Collect all possible assignments for this project-role
                candidates = []
                for person_name in self.person_by_name:
                    key = (project.id, role, person_name)
                    if key in self.assignment_vars:
                        candidates.append(self.assignment_vars[key])

                if candidates:
                    # At least one person must be assigned
                    # (Could be multiple for pair programming, etc.)
                    self.model.Add(sum(candidates) >= 1)

    def _add_capacity_constraints(self, allow_violations: bool):
        """Add constraints to prevent over-allocation of people."""
        # For each person, for each month, ensure total allocation <= 100%
        # (minus KTLO reservation)

        for person in self.people:
            person_name = person.name

            for role in person.roles:
                ktlo_pct = self.config.ktlo_pct_by_role.get(role, 0.0)
                max_capacity_pct = 1.0 - ktlo_pct

                for month_idx in range(self.horizon):
                    # Skip months where person is unavailable
                    if month_idx not in self.person_availability.get(person_name, set()):
                        continue

                    # Collect all tasks that could run in this month
                    monthly_allocations = []

                    for project in self.projects:
                        key = (project.id, role, person_name)
                        if key not in self.task_vars:
                            continue

                        task = self.task_vars[key]

                        # Simplified: Just track if assignment is possible
                        # The assignment variable itself controls if this counts
                        # We'll multiply effort by assignment to get contribution

                        # Simplified: Use a fixed capacity estimate
                        # Assume each task uses about 30% of a person when active
                        # This is a placeholder - proper implementation would track actual durations
                        #
                        # Scale to integer (1000 = 100%)
                        estimated_effort_per_month = 300  # 30%

                        # Contribution to this month = assignment * effort
                        monthly_allocations.append((task['assignment'], estimated_effort_per_month))

                    if not monthly_allocations:
                        continue

                    # Sum of all allocations in this month
                    total_allocation = sum(
                        is_active * effort for is_active, effort in monthly_allocations
                    )

                    max_capacity_scaled = int(max_capacity_pct * 1000)

                    if allow_violations:
                        # Track over-allocation
                        over_alloc_var = self.model.NewIntVar(
                            0, 2000,  # Up to 200% over-allocation
                            f'over_alloc_{person_name}_{month_idx}'
                        )
                        self.model.Add(over_alloc_var >= total_allocation - max_capacity_scaled)
                        self.over_allocation_vars[(person_name, month_idx)] = over_alloc_var
                    else:
                        # Strict constraint
                        self.model.Add(total_allocation <= max_capacity_scaled)

    def _add_skill_constraints(self, allow_violations: bool):
        """Add constraints for skill matching."""
        for key, task in self.task_vars.items():
            project_id, role, person_name = key
            required_skills = task['required_skills']

            if not required_skills:
                continue

            person_skills = self.person_skills.get(person_name, set())
            has_required_skills = bool(required_skills & person_skills)

            if allow_violations:
                # Track skill mismatches
                if not has_required_skills:
                    mismatch_var = self.model.NewBoolVar(
                        f'skill_mismatch_{project_id}_{role}_{person_name}'
                    )
                    # mismatch = 1 if assigned
                    self.model.Add(mismatch_var == task['assignment'])
                    self.skill_mismatch_vars[key] = mismatch_var
            else:
                # Strict constraint: can't assign if no skills
                if not has_required_skills:
                    self.model.Add(task['assignment'] == 0)

    def _add_precedence_constraints(self):
        """Add constraints for project dependencies (if any)."""
        # TODO: Implement project dependencies
        # For now, just ensure project start/end align with task start/end

        for project in self.projects:
            project_tasks = [
                task for key, task in self.task_vars.items()
                if key[0] == project.id
            ]

            if not project_tasks:
                continue

            # Project starts at earliest task start
            for task in project_tasks:
                self.model.Add(
                    self.project_start_vars[project.id] <= task['start']
                ).OnlyEnforceIf(task['assignment'])

            # Project ends at latest task end
            for task in project_tasks:
                self.model.Add(
                    self.project_end_vars[project.id] >= task['end']
                ).OnlyEnforceIf(task['assignment'])

    def _set_objective(self):
        """Set objective: minimize total project completion time + prioritize high-priority."""
        objective_terms = []

        for project in self.projects:
            # Minimize project end time
            end_var = self.project_end_vars[project.id]

            # Weight by inverse priority (lower priority number = higher importance)
            if project.priority is not None:
                try:
                    priority_val = int(project.priority)
                    # Higher priority (lower number) gets higher weight
                    weight = 100 // max(1, priority_val)
                except (ValueError, TypeError):
                    weight = 1
            else:
                weight = 1

            objective_terms.append(end_var * weight)

        self.model.Minimize(sum(objective_terms))

    def _set_objective_with_penalties(self):
        """Set objective with penalties for violations."""
        objective_terms = []

        # Primary objective: minimize project completion time
        for project in self.projects:
            end_var = self.project_end_vars[project.id]
            if project.priority is not None:
                try:
                    priority_val = int(project.priority)
                    weight = 100 // max(1, priority_val)
                except (ValueError, TypeError):
                    weight = 1
            else:
                weight = 1
            objective_terms.append(end_var * weight)

        # Penalty for over-allocations (heavy penalty)
        for over_alloc_var in self.over_allocation_vars.values():
            objective_terms.append(over_alloc_var * 1000)  # Very high penalty

        # Penalty for skill mismatches (moderate penalty)
        for mismatch_var in self.skill_mismatch_vars.values():
            objective_terms.append(mismatch_var * 500)

        self.model.Minimize(sum(objective_terms))

    def solve(self, time_limit_seconds: int = 300) -> Optional[cp_model.CpSolver]:
        """Solve the model and return solver if successful."""
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit_seconds
        solver.parameters.log_search_progress = True  # Enable logging

        print(f"    Model has {len(self.task_vars)} task variables")
        print(f"    Model has {len(self.assignment_vars)} assignment variables")
        print(f"    Solving...")

        status = solver.Solve(self.model)

        status_names = {
            cp_model.OPTIMAL: "OPTIMAL",
            cp_model.FEASIBLE: "FEASIBLE",
            cp_model.INFEASIBLE: "INFEASIBLE",
            cp_model.MODEL_INVALID: "MODEL_INVALID",
            cp_model.UNKNOWN: "UNKNOWN",
        }

        print(f"    Solver status: {status_names.get(status, 'UNKNOWN')}")
        print(f"    Wall time: {solver.WallTime():.2f}s")

        if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
            print(f"    ✓ Found solution!")
            return solver
        elif status == cp_model.INFEASIBLE:
            print(f"    ✗ Problem is INFEASIBLE (no solution exists)")
        elif status == cp_model.MODEL_INVALID:
            print(f"    ✗ MODEL is INVALID (check constraints)")
        else:
            print(f"    ✗ Solver could not find solution in time limit")

        return None

    def extract_violations(self, solver: cp_model.CpSolver) -> List[Violation]:
        """Extract violations from the relaxed solution."""
        violations = []

        # Extract over-allocation violations
        for (person_name, month_idx), over_alloc_var in self.over_allocation_vars.items():
            over_alloc_value = solver.Value(over_alloc_var)
            if over_alloc_value > 0:
                # Convert back to percentage
                over_alloc_pct = over_alloc_value / 1000.0
                severity = 1.0 + over_alloc_pct

                month_str = self.month_starts[month_idx].strftime(MONTH_FMT)
                violations.append(Violation(
                    violation_type="over_allocation",
                    person=person_name,
                    month=month_str,
                    severity=severity,
                    description=f"{person_name} over-allocated to {severity*100:.0f}% in {month_str}"
                ))

        # Extract skill mismatch violations
        for (project_id, role, person_name), mismatch_var in self.skill_mismatch_vars.items():
            if solver.Value(mismatch_var):
                task = self.task_vars[(project_id, role, person_name)]
                required_skills = list(task['required_skills'])
                actual_skills = list(self.person_skills.get(person_name, set()))

                violations.append(Violation(
                    violation_type="skill_mismatch",
                    person=person_name,
                    project_id=project_id,
                    role=role,
                    severity=1.0,
                    required_skills=required_skills,
                    actual_skills=actual_skills,
                    description=f"{person_name} assigned to {project_id} ({role}) "
                                f"without required skills: {', '.join(required_skills)}"
                ))

        return violations


def solve_with_ortools(
    projects_df: pd.DataFrame,
    people_df: pd.DataFrame,
    config: PlanningConfig,
) -> SolverResult:
    """
    Main entry point for OR-Tools solver with multi-pass optimization.

    Pass 1: Try strict constraints
    Pass 2: If failed, allow violations but track them
    """
    from .engine import _projects_from_df, _people_from_df, _build_month_sequence
    from .recommendations import RecommendationEngine

    # Parse input data
    projects = _projects_from_df(projects_df)
    people = _people_from_df(people_df)
    month_starts = _build_month_sequence(config)

    if not projects:
        return SolverResult(
            success=False,
            solution_type="failed",
            scheduled_projects=[],
            unscheduled_projects=[],
            violations=[],
            resource_timeline=pd.DataFrame(),
            recommendations={"error": "No projects to schedule"},
        )

    if not people:
        return SolverResult(
            success=False,
            solution_type="failed",
            scheduled_projects=[],
            unscheduled_projects=[],
            violations=[],
            resource_timeline=pd.DataFrame(),
            recommendations={"error": "No people available"},
        )

    print(f"\n{'='*60}")
    print(f"OR-Tools Solver: Multi-Pass Optimization")
    print(f"{'='*60}")
    print(f"Projects: {len(projects)}")
    print(f"People: {len(people)}")
    print(f"Planning Horizon: {len(month_starts)} months")
    print(f"Time Limit: {config.solver_time_limit_seconds}s")
    print()

    # Pass 1: Try strict constraints
    print("PASS 1: Attempting strict constraint satisfaction...")
    print("-" * 60)

    model_strict = CapacityPlannerModel(projects, people, config, month_starts)
    model_strict.build_strict_model()
    solver_strict = model_strict.solve(time_limit_seconds=config.solver_time_limit_seconds)

    if solver_strict:
        print("✓ SUCCESS: Found feasible solution with strict constraints!")
        print()

        scheduled, unscheduled = _extract_solution(
            solver_strict, model_strict, projects, people, month_starts
        )

        return SolverResult(
            success=True,
            solution_type="strict",
            scheduled_projects=scheduled,
            unscheduled_projects=unscheduled,
            violations=[],
            resource_timeline=_build_resource_timeline(solver_strict, model_strict, people, month_starts),
            recommendations={
                "status": "All projects scheduled within constraints",
                "hiring": [],
                "training": [],
                "summary": {"mode": "strict", "violations": 0}
            },
        )

    print("✗ FAILED: No feasible solution with strict constraints")
    print()

    # Pass 2: Try relaxed constraints
    print("PASS 2: Attempting relaxed optimization (allowing violations)...")
    print("-" * 60)

    model_relaxed = CapacityPlannerModel(projects, people, config, month_starts)
    model_relaxed.build_relaxed_model()
    solver_relaxed = model_relaxed.solve(time_limit_seconds=config.solver_time_limit_seconds)

    if solver_relaxed:
        print("✓ SUCCESS: Found solution with violations")
        print()

        violations = model_relaxed.extract_violations(solver_relaxed)
        print(f"Violations detected: {len(violations)}")
        for v in violations[:5]:  # Show first 5
            print(f"  - {v.description}")
        if len(violations) > 5:
            print(f"  ... and {len(violations) - 5} more")
        print()

        scheduled, unscheduled = _extract_solution(
            solver_relaxed, model_relaxed, projects, people, month_starts
        )

        # Generate recommendations
        rec_engine = RecommendationEngine(violations, scheduled, people, month_starts)
        recommendations = rec_engine.analyze()

        print(f"Recommendations generated:")
        print(f"  - Hiring: {len(recommendations['hiring'])}")
        print(f"  - Training: {len(recommendations['training'])}")
        print()

        return SolverResult(
            success=True,
            solution_type="relaxed",
            scheduled_projects=scheduled,
            unscheduled_projects=unscheduled,
            violations=violations,
            resource_timeline=_build_resource_timeline(solver_relaxed, model_relaxed, people, month_starts),
            recommendations=recommendations,
        )

    print("✗ FAILED: No solution found even with relaxed constraints")
    print()

    return SolverResult(
        success=False,
        solution_type="failed",
        scheduled_projects=[],
        unscheduled_projects=[{
            "id": p.id,
            "name": p.name,
            "reason": "Solver could not find any feasible solution"
        } for p in projects],
        violations=[],
        resource_timeline=pd.DataFrame(),
        recommendations={"error": "No feasible solution found"},
    )


def _extract_solution(
    solver: cp_model.CpSolver,
    model: CapacityPlannerModel,
    projects: List[Project],
    people: List[Person],
    month_starts: List[date],
) -> Tuple[List[Dict], List[Dict]]:
    """Extract scheduled and unscheduled projects from solver solution."""
    scheduled = []
    unscheduled = []

    for project in projects:
        # Check if project has any assignments
        project_assigned = False
        assigned_people = defaultdict(set)

        for key, task in model.task_vars.items():
            proj_id, role, person_name = key
            if proj_id == project.id:
                if solver.Value(task['assignment']):
                    project_assigned = True
                    assigned_people[role].add(person_name)

        if project_assigned:
            start_month_idx = solver.Value(model.project_start_vars[project.id])
            end_month_idx = solver.Value(model.project_end_vars[project.id])

            scheduled.append({
                "id": project.id,
                "name": project.name,
                "start_month": month_starts[start_month_idx].strftime(MONTH_FMT),
                "end_month": month_starts[min(end_month_idx, len(month_starts)-1)].strftime(MONTH_FMT),
                "duration_months": end_month_idx - start_month_idx,
                "assigned_people": {role: list(people) for role, people in assigned_people.items()},
            })
        else:
            unscheduled.append({
                "id": project.id,
                "name": project.name,
                "reason": "Could not find feasible assignment",
            })

    return scheduled, unscheduled


def _build_resource_timeline(
    solver: cp_model.CpSolver,
    model: CapacityPlannerModel,
    people: List[Person],
    month_starts: List[date],
) -> pd.DataFrame:
    """Build resource allocation timeline dataframe."""
    rows = []

    for person in people:
        for month_idx, month_start in enumerate(month_starts):
            month_str = month_start.strftime(MONTH_FMT)

            for role in person.roles:
                # Find all tasks assigned to this person in this month
                allocations = []
                total_pct = 0.0

                for key, task in model.task_vars.items():
                    proj_id, task_role, person_name = key

                    if person_name != person.name or task_role != role:
                        continue

                    if not solver.Value(task['assignment']):
                        continue

                    task_start = solver.Value(task['start'])
                    task_end = solver.Value(task['end'])

                    if task_start <= month_idx < task_end:
                        # Simplified: assume uniform distribution
                        duration = solver.Value(task['duration'])
                        effort_pm = task['effort_pm']
                        pct_per_month = effort_pm / max(1, duration)

                        allocations.append({
                            "project_id": proj_id,
                            "allocation_pct": pct_per_month,
                        })
                        total_pct += pct_per_month

                if allocations or month_idx < 6:  # Show first 6 months even if empty
                    rows.append({
                        "person": person.name,
                        "role": role,
                        "month": month_str,
                        "total_allocation_pct": round(total_pct, 3),
                        "project_count": len(allocations),
                    })

    return pd.DataFrame(rows)
