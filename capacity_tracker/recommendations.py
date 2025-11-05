"""
Enhanced recommendations engine for capacity planning.

Analyzes violations and capacity gaps to provide actionable recommendations:
- Hiring needs (how many people, what skills, by when)
- Training needs (which people need which skills)
- Timeline adjustments (which projects should be delayed)
- Resource reallocation suggestions
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Set

from dateutil.relativedelta import relativedelta


@dataclass
class HiringRecommendation:
    """Recommendation to hire additional resources."""
    role: str
    required_skills: Set[str]
    count: int  # How many people needed
    by_month: str  # When they're needed
    reason: str
    affected_projects: List[str]
    severity: str  # "critical", "high", "medium", "low"


@dataclass
class TrainingRecommendation:
    """Recommendation to train existing resources."""
    person: str
    current_skills: Set[str]
    recommended_skills: Set[str]
    reason: str
    affected_projects: List[str]
    priority: str  # "high", "medium", "low"


@dataclass
class TimelineRecommendation:
    """Recommendation to adjust project timeline."""
    project_id: str
    current_timeline: str
    recommended_timeline: str
    reason: str
    impact: str  # Description of impact


@dataclass
class ReallocationRecommendation:
    """Recommendation to reallocate resources."""
    person: str
    from_project: str
    to_project: str
    from_month: str
    to_month: str
    reason: str


class RecommendationEngine:
    """Analyzes violations and generates actionable recommendations."""

    def __init__(
        self,
        violations: List,
        scheduled_projects: List[Dict],
        people: List,
        month_starts: List[date],
    ):
        self.violations = violations
        self.scheduled_projects = scheduled_projects
        self.people = people
        self.month_starts = month_starts

        self.hiring_recommendations: List[HiringRecommendation] = []
        self.training_recommendations: List[TrainingRecommendation] = []
        self.timeline_recommendations: List[TimelineRecommendation] = []
        self.reallocation_recommendations: List[ReallocationRecommendation] = []

    def analyze(self) -> Dict[str, object]:
        """Run full analysis and return comprehensive recommendations."""
        self._analyze_over_allocations()
        self._analyze_skill_gaps()
        self._analyze_timeline_violations()
        self._prioritize_recommendations()

        return {
            "hiring": [self._hiring_to_dict(h) for h in self.hiring_recommendations],
            "training": [self._training_to_dict(t) for t in self.training_recommendations],
            "timeline": [self._timeline_to_dict(t) for t in self.timeline_recommendations],
            "reallocation": [self._realloc_to_dict(r) for r in self.reallocation_recommendations],
            "summary": self._generate_summary(),
        }

    def _analyze_over_allocations(self):
        """Analyze over-allocation violations and recommend hiring."""
        # Group violations by person and month
        over_alloc_by_person_month = defaultdict(list)

        for violation in self.violations:
            if violation.violation_type == "over_allocation":
                key = (violation.person, violation.month)
                over_alloc_by_person_month[key].append(violation)

        # Identify chronic over-allocation (multiple months)
        person_overload = defaultdict(list)
        for (person, month), viols in over_alloc_by_person_month.items():
            person_overload[person].append((month, viols))

        for person, month_violations in person_overload.items():
            if len(month_violations) >= 3:  # Over-allocated for 3+ months
                # Find person's role and skills
                person_obj = next((p for p in self.people if p.name == person), None)
                if not person_obj:
                    continue

                for role in person_obj.roles:
                    # Recommend hiring someone with similar skillset
                    # Filter out None months and find earliest
                    months_with_values = [mv[0] for mv in month_violations if mv[0] is not None]
                    first_month = min(months_with_values) if months_with_values else "ASAP"

                    self.hiring_recommendations.append(HiringRecommendation(
                        role=role,
                        required_skills=set(person_obj.skillsets),
                        count=1,
                        by_month=first_month,
                        reason=f"{person} is over-allocated for {len(month_violations)} months ({first_month} onwards)",
                        affected_projects=[],  # TODO: Extract from violations
                        severity="high" if len(month_violations) >= 6 else "medium",
                    ))

    def _analyze_skill_gaps(self):
        """Analyze skill mismatch violations and recommend training or hiring."""
        skill_gaps = defaultdict(lambda: {"count": 0, "people": set(), "projects": set()})

        for violation in self.violations:
            if violation.violation_type == "skill_mismatch":
                for skill in violation.required_skills:
                    if skill not in violation.actual_skills:
                        skill_gaps[skill]["count"] += 1
                        skill_gaps[skill]["people"].add(violation.person)
                        skill_gaps[skill]["projects"].add(violation.project_id)

        for skill, gap_info in skill_gaps.items():
            if gap_info["count"] >= 2:  # Skill needed in multiple places
                # Recommend training for people who are close
                for person in gap_info["people"]:
                    person_obj = next((p for p in self.people if p.name == person), None)
                    if not person_obj:
                        continue

                    self.training_recommendations.append(TrainingRecommendation(
                        person=person,
                        current_skills=set(person_obj.skillsets),
                        recommended_skills={skill},
                        reason=f"{skill} is required by {gap_info['count']} projects",
                        affected_projects=list(gap_info["projects"]),
                        priority="high" if gap_info["count"] >= 3 else "medium",
                    ))

                # Also recommend hiring if gap is severe
                if gap_info["count"] >= 3:
                    # Find role associated with this skill
                    role = self._infer_role_from_skill(skill)

                    self.hiring_recommendations.append(HiringRecommendation(
                        role=role,
                        required_skills={skill},
                        count=1,
                        by_month=self._get_earliest_need_month(skill),
                        reason=f"{skill} is a critical gap affecting {gap_info['count']} projects",
                        affected_projects=list(gap_info["projects"]),
                        severity="critical",
                    ))

    def _analyze_timeline_violations(self):
        """Analyze timeline extensions and recommend adjustments."""
        # TODO: Implement timeline violation analysis
        pass

    def _prioritize_recommendations(self):
        """Sort and prioritize recommendations."""
        # Sort hiring by severity
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        self.hiring_recommendations.sort(
            key=lambda h: (severity_order.get(h.severity, 999), h.by_month)
        )

        # Sort training by priority
        priority_order = {"high": 0, "medium": 1, "low": 2}
        self.training_recommendations.sort(
            key=lambda t: priority_order.get(t.priority, 999)
        )

    def _infer_role_from_skill(self, skill: str) -> str:
        """Infer most likely role for a skill."""
        # Simple heuristic - can be improved
        skill_lower = skill.lower()
        if any(kw in skill_lower for kw in ["frontend", "backend", "dev", "code", "programming"]):
            return "Dev"
        elif any(kw in skill_lower for kw in ["planning", "scrum", "agile", "project"]):
            return "Planner"
        elif any(kw in skill_lower for kw in ["business", "analysis", "requirement"]):
            return "BA"
        return "Dev"  # Default

    def _get_earliest_need_month(self, skill: str) -> str:
        """Get earliest month when this skill is needed."""
        # TODO: Extract from violations
        return self.month_starts[0].strftime("%Y-%m") if self.month_starts else "ASAP"

    def _generate_summary(self) -> Dict[str, object]:
        """Generate executive summary of recommendations."""
        return {
            "total_hiring_needs": len(self.hiring_recommendations),
            "critical_hires": sum(1 for h in self.hiring_recommendations if h.severity == "critical"),
            "training_opportunities": len(self.training_recommendations),
            "timeline_adjustments": len(self.timeline_recommendations),
            "reallocation_suggestions": len(self.reallocation_recommendations),
        }

    @staticmethod
    def _hiring_to_dict(h: HiringRecommendation) -> Dict:
        return {
            "type": "hiring",
            "role": h.role,
            "required_skills": list(h.required_skills),
            "count": h.count,
            "by_month": h.by_month,
            "reason": h.reason,
            "affected_projects": h.affected_projects,
            "severity": h.severity,
        }

    @staticmethod
    def _training_to_dict(t: TrainingRecommendation) -> Dict:
        return {
            "type": "training",
            "person": t.person,
            "current_skills": list(t.current_skills),
            "recommended_skills": list(t.recommended_skills),
            "reason": t.reason,
            "affected_projects": t.affected_projects,
            "priority": t.priority,
        }

    @staticmethod
    def _timeline_to_dict(t: TimelineRecommendation) -> Dict:
        return {
            "type": "timeline",
            "project_id": t.project_id,
            "current_timeline": t.current_timeline,
            "recommended_timeline": t.recommended_timeline,
            "reason": t.reason,
            "impact": t.impact,
        }

    @staticmethod
    def _realloc_to_dict(r: ReallocationRecommendation) -> Dict:
        return {
            "type": "reallocation",
            "person": r.person,
            "from_project": r.from_project,
            "to_project": r.to_project,
            "from_month": r.from_month,
            "to_month": r.to_month,
            "reason": r.reason,
        }
