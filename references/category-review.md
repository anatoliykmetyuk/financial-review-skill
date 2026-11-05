# Category review

Complete the shared workflow first. Run `report --category 'Example category'`, using the base and local currencies from settings unless the user requests an override. There is no preferred currency pair in source.

Run `scripts/render_report.py REPORT.json --chart /absolute/current-chat/work/financial-review.html` for the table and chart fragment. Follow the visualization skill when presenting or changing a visual. Use the current chat's durable working directory; never reuse another chat's absolute chart path.

State category, dates, timezone, and cutoff. Preserve these weekly labels, substituting configured currency codes and appropriately formatted amounts:

| | BASE | LOCAL |
|---|---:|---:|
| 📅 Monthly | … | … |
| 📆 Weekly | … | … |
| ☀️ Daily | … | … |
| 🍽️ Spent this week | … | … |
| ✅ Remaining this week | … | … |

If both currencies are the same, show one numeric column. For historical/nonweekly periods, label spending and remaining “in period”; adapt the allowance row to its length. Cross-month periods identify the applicable monthly and daily allowances. Use each currency's customary display precision and keep negative remaining values. JSON report fields use `*_base` for configured-base amounts and `*_local` for local display amounts.

## Two charts

1. **Daily spending line chart** in the local currency. X = local day/date; Y = money spent, with currency labeled. One node per covered day, including zero-expense days. Unavailable/future days have null values, no node, and break the connecting line. Partial days have explicit notes. The line spans every date in the requested period; when the user requests finer granularity, adapt the line's time bins and labels accordingly without changing the budget bars' daily sections.
2. **Shared budget progress bars**: split the requested dates into Monday–Sunday calendar weeks, rendering one bar per intersecting week in chronological order. Include only requested dates in partial boundary weeks. Thursday through the following Wednesday renders Thu–Sun, then Mon–Wed, even though the period is exactly seven days. A period contained within one calendar week renders just its requested days.

Each bar's capacity is the sum of its dates' daily allowances. Allocate **total period spending** across the bars sequentially: fill the first to capacity, overflow into the second, and continue. Do not allocate by the dates on which expenses occurred. For two full weeks with total spending equal to half of one week's allowance, the first bar is half full and the second is empty. Refunds reduce the shared spending total; negative net spending leaves all fills empty.

Use a common money scale across positive-budget bars. Partial bars are shorter: with equal daily allowances, four days occupy four-sevenths of a full week's width. Daily sections follow their allowances, including differing monthly budgets, and the labels show only that bar's dates. Keep week date ranges visible. Show period spending, maximum, percent, daily allowance, and remaining once; each bar may label its allocated fill and capacity.

If the period is overspent, cap every visible bar at capacity and show the actual period percent and excess explicitly. Zero budget means undefined percent, shown as “N/A (zero budget)”; keep daily reference sections and explicitly label positive spending as over budget. These bars share one fill; they are never independent daily or weekly expense charts.

Line nodes expose chronological transaction details. Header: local day/date and total local currency. Exactly one transaction per line: `HH:mm · description - formatted amount`, adapting currency. Preserve visual line breaks and show refunds with their signed spending value. Missing source time must say “time unavailable”, never invented midnight. The importer deliberately blocks date-only data until a bank-specific policy is resolved.

Keep zero as the lower Y-axis bound when every daily total is nonnegative. Extend below zero only for actual negative daily totals, such as net refunds; chart padding must not introduce negative spending labels by itself.

Hover tooltips disappear on leaving the node or chart even after a mouse click. Keyboard details disappear on blur and Escape. Touch tap shows details and tapping outside dismisses them. Keep the tooltip inside the visible surface with wrapping descriptions. Verify display and dismissal, narrow width, and daily/period reconciliation after renderer changes.

Final response includes the table, chart reference, and concise coverage/rate notes. Do not describe an ongoing category as “on pace” merely because it is below the full-period allowance.
