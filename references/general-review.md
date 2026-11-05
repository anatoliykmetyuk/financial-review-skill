# General review

Complete the shared workflow for all tracked accounts and all categories in the period. Run `report` without `--category`; `scripts/render_report.py REPORT.json` formats it without charts.

Use the configured base currency. Compare spending with the full requested period allowance:

- Yellow: excess greater than zero and at most `defaults.yellow_excess_max`, measured in the base currency.
- Red: excess above that threshold.
- Green: all categories within the allowance, with no unresolved classifications or budget mappings and the data cutoff disclosed.

List exceptions with category, spending, allowance, and excess. Otherwise a short green statement is enough. Positive spending against zero budget is overspending under the same thresholds. Collect every tracked account before an all-clear. Future dates need no fabricated data; disclose partial snapshots.

State dates, timezone, cutoff, rate and retrieval time concisely. “Within the period allowance” does not assert time-adjusted pace. Income and internal movements are excluded by economic kind, independently of category names.
