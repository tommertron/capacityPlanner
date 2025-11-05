Run comprehensive tests on the Portfolio Planner model to validate correctness.

Execute the following test sequence:
1. Run the model on the sample portfolio with a fixed seed (42)
2. Validate all output files were created
3. Check critical constraints:
   - All `total_pct` ≤ 1.0 (or overbooking tolerance)
   - No person allocated outside their availability window
   - Planner allocations ≤ `planner_project_month_cap_pct`
   - All required skillsets covered
   - Start/end months within planning window
4. Verify determinism by running twice and comparing outputs

Report:
- ✅ All validations passed
- ❌ Any constraint violations with details
- Summary statistics (projects scheduled, people utilized, avg capacity %)
