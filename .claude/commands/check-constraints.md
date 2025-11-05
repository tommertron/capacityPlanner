Validate a portfolio's input data and check for constraint violations or potential issues.

If no portfolio name is specified, prompt the user to select from available portfolios.

For the selected portfolio, perform these checks:

**Input Validation:**
- All required files exist (projects.csv, people.json, config.json)
- CSV/JSON schema is correct
- Dates are valid ISO format
- Numeric values are valid (person-months > 0)
- Skillsets properly formatted (semicolon-separated)

**Feasibility Checks:**
- People availability windows overlap with planning window
- Required skills exist in people roster
- Sufficient people for each role
- KTLO percentages are reasonable (< 100%)
- Concurrent limits are positive integers

**Output Validation (if outputs exist):**
- Read resource_capacity.csv and check all total_pct values
- Verify no allocations outside availability windows
- Check planner cap compliance
- List any constraint violations

Report findings with:
- ✅ Checks passed
- ⚠️ Warnings (non-critical issues)
- ❌ Errors (violations or invalid data)
