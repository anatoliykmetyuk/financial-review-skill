# General review

Complete the shared workflow for all tracked accounts. Run `report` without `--category` and format it with `scripts/render_report.py REPORT.json`.

Use the configured base currency and the [budget checks](budgets-and-currency.md#budget-checks). Show one line per over-budget category and month with month-to-date spending, the limit and its applicable dates, and the amount over. Use these markers:

- 🟡 for an excess greater than zero and at most `defaults.yellow_excess_max`.
- 🔴 for an excess above that threshold.
- 🟢 for a short all-clear when all categories are within their limits, classifications and budget mappings are resolved, and coverage is verified through the stated cutoff.

Keep the default output to the exception lines or the all-clear, with concise dates, timezone, coverage, and rate notes. If coverage is unverified and the available ledger shows no overages, state that without a green marker. A positive spend against a zero limit follows the same warning thresholds.
