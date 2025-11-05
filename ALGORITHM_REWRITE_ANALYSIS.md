# Algorithm Rewrite Analysis: pyschedule Integration

**Branch**: `algorithm-rewrite-pyschedule`
**Date**: 2025-11-04
**Purpose**: Evaluate pyschedule library for replacing/enhancing current greedy allocation algorithm

---

## Executive Summary

### Key Findings

⚠️ **CRITICAL**: pyschedule **requires PuLP** as a hard dependency - this is the source of the "ModuleNotFoundError: No module named 'pulp'" error you saw earlier.

**Recommendation**: **Do NOT use pyschedule** for the following reasons:
1. ❌ Hard PuLP dependency (exactly what you wanted to avoid)
2. ❌ No built-in skills/qualifications modeling
3. ❌ Limited scalability (small-to-medium problems only)
4. ❌ Questionable maintenance status (appears dormant)
5. ❌ Fixed task durations (can't adjust based on resource capability)

**Better alternatives**:
- Implement custom constraint-based optimization with Google OR-Tools (no PuLP dependency)
- Use genetic algorithms or simulated annealing for large-scale problems
- Enhance current greedy algorithm with better lookahead/backtracking

---

## Current Algorithm Analysis

### Algorithm Type: **Greedy Heuristic with Priority Scheduling**

### How It Works

Your current implementation in `capacity_tracker/engine.py` uses a **greedy sequential allocation** approach:

1. **Initialization** (`_build_person_states`)
   - Build month-by-month capacity for each person/role
   - Account for KTLO reservations
   - Track person availability windows, skills, and preferences

2. **Project Ordering** (line 769-779)
   - Sort projects by priority (if enabled)
   - Lower priority number = scheduled first
   - Tie-break by input row order

3. **Per-Project Scheduling** (line 781+)
   - For each project (in priority order):
     - Calculate minimum duration based on effort/capacity
     - Try multiple start dates (early to late)
     - For each start date, attempt allocation

4. **Month-by-Month Allocation** (`_allocate_month`, line 383-595)
   - For each role/month in the project:
     - Find available people with required skills
     - Sort candidates by:
       1. Already assigned to this project (continuity)
       2. Covers needed skillsets
       3. Preferred program match
       4. Random tie-breaker
     - Greedily assign capacity until demand met
     - Allow overbooking for high-priority projects (optional)

5. **Backtracking** (`_rollback_assignments`)
   - If allocation fails, rollback all assignments for that project
   - Skip project or fail (depending on strict mode)

### Strengths of Current Approach

✅ **Fast**: Runs in near-linear time relative to projects × months
✅ **Handles skills**: Explicit skillset matching
✅ **Flexible**: Supports preferences, availability windows, program affinity
✅ **Transparent**: Easy to understand and debug
✅ **No external solver dependencies**: Pure Python + pandas
✅ **Handles concurrency limits**: Max concurrent projects per role
✅ **KTLO-aware**: Reserves capacity for keep-the-lights-on work

### Weaknesses of Current Approach

❌ **Greedy = suboptimal**: First project grabs best resources, starving later ones
❌ **No global optimization**: Can't trade off between projects
❌ **Limited backtracking**: Only tries different start dates, not different resource assignments
❌ **Priority dependency**: Heavily dependent on correct priority ordering
❌ **No cost optimization**: Can't minimize total cost or resource usage
❌ **No load balancing**: Doesn't try to distribute work evenly

### Example Failure Case

```
Given:
- Projects: P1 (priority 1, needs 6 months), P2 (priority 2, needs 3 months)
- Resources: Alice (expert), Bob (junior)
- P1 requires expert skills for 2 months, junior for 4 months
- P2 requires expert skills for all 3 months

Greedy Result:
- P1 gets Alice for all 6 months (priority 1)
- P2 FAILS (no expert available)

Optimal Result:
- P1 gets Alice for 2 months, Bob for 4 months
- P2 gets Alice for 3 months
- Both projects complete
```

---

## pyschedule Library Details

### What It Is

- Python scheduling library using **Mixed Integer Programming (MIP)**
- Designed for resource-constrained task scheduling
- Scale: Small-to-medium (10 resources, 100 tasks, 100 periods)
- Applications: School timetables, manufacturing, job shops

### Architecture

```
Task Definition → Constraint Declaration → MIP Formulation → Solver → Schedule
     ↓                     ↓                    ↓              ↓
  pyschedule          pyschedule            PuLP          CBC/CPLEX
```

### Dependencies

**Required**:
- **PuLP** - Linear programming modeling (THIS IS THE ISSUE!)
- **CBC** - Free MIP solver (bundled with PuLP)

**Optional**:
- `google-ortools` - Alternative constraint programming solver
- `matplotlib` - Visualization
- Commercial solvers: CPLEX, GUROBI, SCIP

### Core Concepts

#### 1. Resources
```python
S = Scenario('example', horizon=20)
Teacher = S.Resource('T', size=2)  # Capacity 2
```
- **No skills system** - must be modeled indirectly
- Size = concurrent capacity
- Can have custom attributes (e.g., `R['skill_level']`)

#### 2. Tasks
```python
Task1 = S.Task('T1', length=5, delay_cost=10)
```
- Fixed length (can't vary by resource)
- Delay costs for priority
- Schedule costs for setup minimization

#### 3. Constraints
```python
# Resource assignment
Task1 += Teacher  # Requires Teacher

# Alternative resources
from pyschedule import alt
Task1 += alt([Teacher1, Teacher2])  # Can use either

# Precedence
S += Task1 < Task2  # Task1 before Task2

# Capacity
S += Teacher[:10].max <= 3  # Max 3 tasks in first 10 periods
```

### What's Missing for Our Use Case

1. **No skills/qualifications**
   - Would need to model as: "create alternative resource groups per skill"
   - Example: `Task += alt([AliceExpert, BobExpert])` for expert-only tasks
   - Cumbersome and error-prone

2. **No dynamic effort**
   - Task length is fixed at creation
   - Can't say "takes 5 days with expert, 10 days with junior"

3. **No team/project structure**
   - All tasks are flat
   - No hierarchy or grouping

4. **No availability calendars**
   - Can set `periods=[0,10]` for time windows
   - But no built-in vacation/PTO handling

5. **No person-level tracking**
   - Resources are abstract (not people with names, roles, skills)

---

## Integration Options

### Option 1: Direct pyschedule Integration (❌ NOT RECOMMENDED)

**Approach**: Replace current algorithm with pyschedule

**Implementation**:
```python
from pyschedule import Scenario, solvers, alt

def allocate_with_pyschedule(projects, people, config):
    horizon = len(month_sequence)
    S = Scenario('capacity_plan', horizon=horizon)

    # Create resources (one per person per role)
    resources = {}
    for person in people:
        for role in person.roles:
            r = S.Resource(f"{person.name}_{role}",
                          periods=get_availability_periods(person))
            resources[(person.name, role)] = r

    # Create tasks (one per project per role)
    for project in projects:
        for role, effort in project.role_efforts().items():
            task = S.Task(f"{project.id}_{role}",
                         length=calc_duration(effort),
                         delay_cost=project.priority)

            # Find capable resources (manual skill matching)
            capable = [resources[(p.name, role)]
                      for p in people
                      if role in p.roles and has_skills(p, project.skills[role])]

            if capable:
                task += alt(capable)

    # Solve
    solvers.mip.solve(S, kind='CBC', time_limit=300)

    # Extract schedule
    return parse_solution(S)
```

**Pros**:
- Global optimization (finds better solutions than greedy)
- Can minimize costs, delays, resource usage
- Handles complex constraints naturally

**Cons**:
- ❌ **PuLP dependency** (defeats your goal)
- ❌ Major rewrite required
- ❌ Skill matching is manual and fragile
- ❌ No person-level metrics (harder to generate resource heatmaps)
- ❌ Slower for large problems
- ❌ Less transparent (solver is a black box)

**Effort**: 3-4 weeks
**Risk**: High (maintenance, dependencies, debugging)

---

### Option 2: Hybrid Approach - pyschedule for Hard Cases Only (⚠️ PARTIAL)

**Approach**: Use greedy for most projects, fall back to pyschedule for conflicts

**Implementation**:
```python
def hybrid_allocate(projects, people, config):
    # Phase 1: Greedy allocation
    scheduled, failed = greedy_allocate(projects, people, config)

    if not failed:
        return scheduled

    # Phase 2: Retry failed projects with pyschedule
    # Only model failed projects + impacted resources
    partial_schedule = pyschedule_solve(
        projects=failed,
        people=get_available_people(scheduled),
        config=config
    )

    return merge_schedules(scheduled, partial_schedule)
```

**Pros**:
- Best of both worlds (speed + optimization)
- PuLP only loaded when needed
- Smaller problem size for solver

**Cons**:
- ❌ Still requires PuLP
- ⚠️ Complex to implement and maintain
- ⚠️ Merging schedules is tricky
- ⚠️ May not find global optimum

**Effort**: 2-3 weeks
**Risk**: Medium

---

### Option 3: Replace PuLP with Google OR-Tools (✅ RECOMMENDED)

**Approach**: Use Google OR-Tools CP-SAT solver instead of pyschedule/PuLP

Google OR-Tools is a production-grade optimization library from Google that:
- ✅ **No PuLP dependency**
- ✅ World-class constraint programming solver
- ✅ Actively maintained by Google
- ✅ Free and open-source
- ✅ Excellent documentation and examples
- ✅ Built-in support for scheduling problems
- ✅ Scales to large problems

**Installation**:
```bash
pip install ortools
```

**Example Implementation**:
```python
from ortools.sat.python import cp_model

def allocate_with_ortools(projects, people, config):
    model = cp_model.CpModel()
    horizon = len(month_sequence)

    # Decision variables: task[project, role, person, start_time]
    task_vars = {}
    for project in projects:
        for role, effort in project.role_efforts().items():
            duration = calc_duration(effort)
            for person in people:
                if role in person.roles and has_skills(person, project):
                    # Interval variable for task assignment
                    start_var = model.NewIntVar(0, horizon, f'start_{project.id}_{role}_{person.name}')
                    end_var = model.NewIntVar(0, horizon, f'end_{project.id}_{role}_{person.name}')
                    interval_var = model.NewIntervalVar(
                        start_var, duration, end_var,
                        f'interval_{project.id}_{role}_{person.name}'
                    )
                    task_vars[(project.id, role, person.name)] = {
                        'start': start_var,
                        'end': end_var,
                        'interval': interval_var
                    }

    # Constraint: Each project-role assigned to exactly one person
    for project in projects:
        for role in project.role_efforts():
            candidates = [task_vars.get((project.id, role, p.name))
                         for p in people if (project.id, role, p.name) in task_vars]
            if candidates:
                model.Add(sum([task['is_assigned'] for task in candidates]) == 1)

    # Constraint: No person overloaded (capacity limits)
    for person in people:
        for role in person.roles:
            for month in range(horizon):
                person_tasks = [task_vars[(p, r, person.name)]['interval']
                               for (p, r, pname) in task_vars
                               if pname == person.name and r == role]
                model.AddCumulative(person_tasks, [1]*len(person_tasks), capacity=1)

    # Objective: Minimize total completion time (or prioritize high-priority projects)
    model.Minimize(sum([task['end'] * project.priority
                       for project in projects
                       for task in task_vars if task[0] == project.id]))

    # Solve
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 300
    status = solver.Solve(model)

    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        return extract_schedule(solver, task_vars)
    else:
        return None
```

**Pros**:
- ✅ **No PuLP** - avoids the dependency issue
- ✅ Production-grade solver (used by Google internally)
- ✅ Better performance than CBC (faster, better solutions)
- ✅ Excellent constraint modeling (skills, availability, concurrency)
- ✅ Active development and support
- ✅ Well-documented with many examples

**Cons**:
- ⚠️ Steeper learning curve than greedy
- ⚠️ Requires constraint programming knowledge
- ⚠️ Still a rewrite (2-3 weeks)

**Effort**: 2-3 weeks
**Risk**: Low-Medium (mature library, good docs)

---

### Option 4: Enhance Current Greedy Algorithm (✅ ALSO RECOMMENDED)

**Approach**: Keep greedy but add smarter heuristics

**Enhancements**:

1. **Lookahead scoring**
   ```python
   def score_assignment(person, project, month):
       # Score based on:
       # - Current capacity usage
       # - Future project needs for this person
       # - Skill scarcity (prefer common skills for common tasks)
       # - Load balancing across team
       return calculate_composite_score(...)
   ```

2. **Multi-pass allocation**
   ```python
   # Pass 1: High-priority projects only
   # Pass 2: Medium priority
   # Pass 3: Low priority with backfilling
   ```

3. **Conflict resolution**
   ```python
   # When allocation fails:
   # - Identify conflicting projects
   # - Try swapping resource assignments
   # - Delay lower-priority projects
   ```

4. **Load balancing**
   ```python
   # Penalize assigning to already-busy people
   # Prefer spreading work across team
   ```

5. **Better backtracking**
   ```python
   # Instead of just trying different start dates:
   # - Try different resource combinations
   # - Try different task orderings within project
   ```

**Pros**:
- ✅ No new dependencies
- ✅ Builds on existing code
- ✅ Incremental improvements
- ✅ Maintains transparency
- ✅ Fast execution

**Cons**:
- ⚠️ Still not globally optimal
- ⚠️ Requires careful tuning
- ⚠️ May hit limits on very complex scenarios

**Effort**: 1-2 weeks
**Risk**: Low

---

## Recommendations

### Short-term (1-2 weeks): Enhance Greedy Algorithm (Option 4)

**Priority improvements**:

1. **Better candidate scoring** (2 days)
   - Add lookahead: penalize using scarce skills for tasks that don't need them
   - Load balancing: prefer less-utilized people
   - Skill scarcity: track which skills are bottlenecks

2. **Multi-pass scheduling** (1 day)
   - Pass 1: Critical projects (priority ≤ 3)
   - Pass 2: Normal projects
   - Pass 3: Low priority + backfill gaps

3. **Conflict resolution** (3 days)
   - When project fails, identify why (capacity, skills, timing)
   - Try limited backtracking: swap resources between projects
   - Use "aggressive mode" more intelligently

4. **Resource pool optimization** (2 days)
   - Group people by skill profiles
   - Ensure each project gets diverse skill coverage
   - Avoid "skill hoarding" by early projects

### Medium-term (1-2 months): Evaluate OR-Tools (Option 3)

**Research phase** (1 week):
- Build proof-of-concept with OR-Tools
- Test on sample portfolios
- Compare results to greedy algorithm
- Measure performance and solution quality

**Implementation phase** (2-3 weeks):
- Implement full OR-Tools solver
- Add skills, availability, concurrency constraints
- Optimize for performance
- Handle edge cases

**Integration phase** (1 week):
- Add as alternative solver mode (`--solver=greedy` or `--solver=ortools`)
- Update web UI to allow solver selection
- Document solver differences

### Long-term: Consider Hybrid Approach

Once OR-Tools is validated:
- Use greedy for small/simple portfolios (fast)
- Use OR-Tools for large/complex portfolios (optimal)
- Let users choose based on their needs

---

## Alternative Libraries to Consider

Instead of pyschedule, consider these PuLP-free alternatives:

### 1. **Google OR-Tools** (✅ BEST CHOICE)
- GitHub: https://github.com/google/or-tools
- Constraint programming + MIP
- No PuLP dependency
- Production-grade
- Active development

### 2. **Python-MIP**
- GitHub: https://github.com/coin-or/python-mip
- Pure Python MIP modeling
- Uses CBC or GUROBI
- Simpler than OR-Tools
- Active development

### 3. **CVXPY**
- GitHub: https://github.com/cvxpy/cvxpy
- Convex optimization
- Multiple backend solvers
- Well-documented
- May not fit scheduling problems perfectly

### 4. **ProcessScheduler**
- GitHub: https://github.com/tpaviot/ProcessScheduler
- Built on top of Microsoft Z3
- Designed for manufacturing/scheduling
- Mentioned in pyschedule issues as potential successor
- Worth exploring

---

## Action Items

### Immediate (This Week)

- [x] Create algorithm rewrite branch
- [x] Document current algorithm
- [x] Research pyschedule
- [ ] Prototype enhanced greedy algorithm
  - [ ] Implement lookahead scoring
  - [ ] Add load balancing
  - [ ] Test on sample portfolios

### Next Steps (Next 2 Weeks)

- [ ] Finalize greedy enhancements
- [ ] Build OR-Tools proof-of-concept
- [ ] Run comparative benchmarks
- [ ] Choose final approach

### Future

- [ ] Implement chosen solver
- [ ] Add solver selection to web UI
- [ ] Document algorithm improvements
- [ ] Write tests for edge cases

---

## Conclusion

**DO NOT use pyschedule** - it introduces the exact PuLP dependency you wanted to avoid and lacks critical features for your use case.

**RECOMMENDED PATH**:
1. **Short-term**: Enhance current greedy algorithm (quick wins, low risk)
2. **Medium-term**: Evaluate Google OR-Tools (modern, powerful, PuLP-free)
3. **Long-term**: Offer both solvers as options

This approach gives you incremental improvements now while building toward a more optimal solution later, all without the PuLP dependency.
