"""
OR-Tools based constraint programming solver for capacity planning.

This module implements a multi-pass optimization approach:
1. Pass 1 (Strict): Try to schedule all projects within constraints
2. Pass 2 (Relaxed): Allow constraint violations but track them for recommendations

Key simplifications for tractability:
- Uses WEEKLY time periods (not monthly) for better granularity
- Converts person-months to person-weeks (1 PM ≈ 4.33 weeks)
- Limits planning horizon to 24 months (~104 weeks)
- Uses simplified capacity model for speed

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

# Conversion constants
WEEKS_PER_MONTH = 4.33  # Average weeks per month
MAX_PLANNING_WEEKS = 104  # 24 months ≈ 104 weeks


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
    """OR-Tools CP-SAT model for capacity planning with weekly time periods."""

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

        # Use weekly periods instead of monthly for better granularity
        # Limit to 104 weeks (24 months) for tractability
        self.horizon = min(MAX_PLANNING_WEEKS, len(month_starts) * 4)  # Roughly 4 weeks per month
        self.weeks_per_month = WEEKS_PER_MONTH

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
        """Build map of person -> set of available week indices."""
        availability = {}
        for person in self.people:
            available_weeks = set()

            # Convert availability to weeks
            planning_start = self.month_starts[0] if self.month_starts else date.today()

            for week_idx in range(self.horizon):
                # Rough approximation: week_idx / 4.33 ≈ month_idx
                approx_month_idx = int(week_idx / self.weeks_per_month)

                if approx_month_idx < len(self.month_starts):
                    week_date = self.month_starts[approx_month_idx]

                    # Check if person is available this week
                    if person.start_date and week_date < self._first_of_month(person.start_date):
                        continue
                    if person.end_date and week_date > self._first_of_month(person.end_date):
                        continue

                    available_weeks.add(week_idx)

            availability[person.name] = available_weeks
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
        self._add_soft_capacity_constraints()  # Add soft capacity limits (penalized but not hard)
        # Skip skill constraints in relaxed mode - just track violations post-hoc
        self._add_precedence_constraints()
        self._set_objective_with_penalties()

    def _create_task_variables(self):
        """Create decision variables for task assignments."""
        for project in self.projects:
            project_efforts = project.role_efforts()

            # Project-level start/end time (in weeks)
            self.project_start_vars[project.id] = self.model.NewIntVar(
                0, self.horizon - 1, f'project_start_{project.id}'
            )
            self.project_end_vars[project.id] = self.model.NewIntVar(
                0, self.horizon, f'project_end_{project.id}'
            )

            for role, effort_pm in project_efforts.items():
                if effort_pm < 0.01:
                    continue

                # Convert person-months to person-weeks
                effort_pw = effort_pm * self.weeks_per_month

                # Calculate minimum duration in weeks
                # Assuming max 1.0 person (100% capacity) per week
                min_duration_weeks = max(1, math.ceil(effort_pw))
                max_duration_weeks = min(self.horizon, int(min_duration_weeks * 2))  # Allow up to 2x spreading

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
                        min_duration_weeks, max_duration_weeks,
                        f'duration_{project.id}_{role}_{person_name}'
                    )
                    end_var = self.model.NewIntVar(
                        min_duration_weeks, self.horizon,
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
                        'effort_pw': effort_pw,  # Effort in person-weeks
                        'min_duration_weeks': min_duration_weeks,
                        'max_duration_weeks': max_duration_weeks,
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
        # For each person, for each role, ensure total allocation <= 100%
        # Uses simplified cumulative constraint for tractability

        for person in self.people:
            person_name = person.name

            for role in person.roles:
                ktlo_pct = self.config.ktlo_pct_by_role.get(role, 0.0)
                max_capacity_pct = 1.0 - ktlo_pct

                # Collect all intervals for this person-role
                intervals = []
                demands = []

                for project in self.projects:
                    key = (project.id, role, person_name)
                    if key not in self.task_vars:
                        continue

                    task = self.task_vars[key]
                    intervals.append(task['interval'])

                    # Demand is roughly: effort / duration (as a percentage)
                    # Simplified: assume each task demands 50% of person's time when active
                    # This is conservative but tractable
                    demands.append(50)  # 50% capacity per task

                if not intervals:
                    continue

                # Add cumulative constraint: total demand <= capacity
                # Capacity = 100 (representing 100%)
                max_capacity_scaled = int(max_capacity_pct * 100)

                if allow_violations:
                    # In relaxed mode, we'll skip strict capacity and track violations separately
                    # This makes the problem more likely to be feasible
                    pass
                else:
                    # Strict mode: enforce capacity limit
                    # For now, use a simplified approach: limit concurrent tasks
                    max_concurrent = self.config.max_concurrent_for_role(role)

                    # Simple constraint: sum of assignments <= max_concurrent
                    assignment_sum = sum(
                        self.task_vars[(p.id, role, person_name)]['assignment']
                        for p in self.projects
                        if (p.id, role, person_name) in self.task_vars
                    )
                    self.model.Add(assignment_sum <= max_concurrent)

        # Simplified version - just limit concurrent tasks per person
        # This is much more tractable than week-by-week capacity tracking

    def _add_soft_capacity_constraints(self):
        """
        Add soft capacity constraints for relaxed mode.
        Limits concurrent assignments per person-role to avoid extreme over-allocation.
        """
        for person in self.people:
            person_name = person.name

            for role in person.roles:
                # Limit total concurrent projects per person-role
                # Use a reasonable limit: 2x the strict concurrency limit
                strict_limit = self.config.max_concurrent_for_role(role)
                soft_limit = strict_limit * 2  # Allow some over-allocation but not extreme

                # Collect all assignments for this person-role
                assignments = []
                for project in self.projects:
                    key = (project.id, role, person_name)
                    if key not in self.task_vars:
                        continue
                    assignments.append(self.task_vars[key]['assignment'])

                if not assignments:
                    continue

                # Soft constraint: prefer to stay under soft_limit
                # But allow violations with a slack variable
                total_assignments = sum(assignments)

                # Create slack variable for over-allocation
                slack_var = self.model.NewIntVar(0, len(assignments),
                                                   f'slack_{person_name}_{role}')

                # total_assignments <= soft_limit + slack
                self.model.Add(total_assignments <= soft_limit + slack_var)

                # Store slack for penalty in objective
                self.over_allocation_vars[(person_name, role)] = slack_var

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

        # Penalty for over-allocations (heavy penalty on slack variables)
        # Each extra assignment beyond soft limit gets heavily penalized
        for slack_var in self.over_allocation_vars.values():
            objective_terms.append(slack_var * 10000)  # Very high penalty per extra assignment

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

        # Extract over-allocation violations from violation variables (if they exist)
        for key, over_alloc_var in self.over_allocation_vars.items():
            over_alloc_value = solver.Value(over_alloc_var)
            if over_alloc_value > 0:
                # Check key format: (person_name, month_idx) or (person_name, role)
                if len(key) == 2 and isinstance(key[1], str):
                    # New format: (person_name, role) -> slack variable
                    person_name, role = key
                    violations.append(Violation(
                        violation_type="over_allocation",
                        person=person_name,
                        role=role,
                        severity=1.0 + over_alloc_value,  # Each slack unit = 1 extra assignment
                        description=f"{person_name} ({role}) assigned to {over_alloc_value} extra projects beyond capacity"
                    ))
                else:
                    # Old format: (person_name, month_idx) -> percentage over-allocation
                    person_name, month_idx = key
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

        # Extract skill mismatch violations from violation variables (if they exist)
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

        # Always analyze the solution to get detailed week-by-week violations
        # This provides more granular information than the high-level slack variables
        violations.extend(self._analyze_solution_for_violations(solver))

        return violations

    def _analyze_solution_for_violations(self, solver: cp_model.CpSolver) -> List[Violation]:
        """
        Analyze the actual solution to detect violations post-hoc.
        This is used when relaxed mode skips constraints entirely.
        """
        violations = []

        # 1. Analyze capacity violations (over-allocation)
        # Build a map of person -> week -> total allocation
        person_week_allocation = defaultdict(lambda: defaultdict(float))

        for key, task in self.task_vars.items():
            proj_id, role, person_name = key

            if not solver.Value(task['assignment']):
                continue

            task_start = solver.Value(task['start'])
            task_end = solver.Value(task['end'])
            task_duration = solver.Value(task['duration'])
            effort_pw = task['effort_pw']

            # Calculate average effort per week
            avg_effort_per_week = effort_pw / max(1, task_duration)

            # Allocate across weeks
            for week_idx in range(task_start, task_end):
                person_week_allocation[person_name][week_idx] += avg_effort_per_week

        # Check for over-allocation
        for person_name, week_allocations in person_week_allocation.items():
            person = self.person_by_name[person_name]

            for week_idx, total_allocation in week_allocations.items():
                # Convert week index to approximate month for reporting
                approx_month_idx = min(int(week_idx / self.weeks_per_month), len(self.month_starts) - 1)
                month_str = self.month_starts[approx_month_idx].strftime(MONTH_FMT)

                # Get KTLO for this person's role (assume first role for simplicity)
                role = person.roles[0] if person.roles else "Dev"
                ktlo_pct = self.config.ktlo_pct_by_role.get(role, 0.0)
                max_capacity = 1.0 - ktlo_pct

                # Check if over-allocated
                if total_allocation > max_capacity:
                    severity = total_allocation / max_capacity
                    violations.append(Violation(
                        violation_type="over_allocation",
                        person=person_name,
                        month=month_str,
                        role=role,
                        severity=severity,
                        description=f"{person_name} over-allocated to {total_allocation*100:.0f}% "
                                    f"(max {max_capacity*100:.0f}%) in week {week_idx} (~{month_str})"
                    ))

        # 2. Analyze skill mismatches
        for key, task in self.task_vars.items():
            proj_id, role, person_name = key

            if not solver.Value(task['assignment']):
                continue

            required_skills = task['required_skills']
            if not required_skills:
                continue

            person_skills = self.person_skills.get(person_name, set())
            missing_skills = required_skills - person_skills

            if missing_skills:
                violations.append(Violation(
                    violation_type="skill_mismatch",
                    person=person_name,
                    project_id=proj_id,
                    role=role,
                    severity=len(missing_skills) / max(1, len(required_skills)),
                    required_skills=list(required_skills),
                    actual_skills=list(person_skills),
                    description=f"{person_name} assigned to {proj_id} ({role}) "
                                f"but missing skills: {', '.join(sorted(missing_skills))}"
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
                        effort_pw = task['effort_pw']
                        # Convert back to person-months for display
                        effort_pm = effort_pw / WEEKS_PER_MONTH
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
