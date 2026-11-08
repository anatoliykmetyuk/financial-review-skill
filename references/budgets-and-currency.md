# Budget and currency inputs

## Spreadsheet

The configured spreadsheet/tab determines the monthly budget for each category. Inspect its current contents on **every review** using the connected Google Sheets skill. Do not assume fixed rows, columns, headings, orientation, sections, or a previous layout. The user may freely reorganize it.

The skill discovers the meaning of the current cells and extracts category/month amounts. Do not ask the user to restore an old layout or maintain parser settings. Only genuine ambiguity in the budget's meaning or missing budget values needs clarification.

Perform this discovery afresh on every review. Read the current spreadsheet through the connected spreadsheet tools and extract category/month amounts directly. Pass only those normalized amounts to the shared calculation script. This interface describes financial meaning, not spreadsheet layout.

The result uses monthly magnitudes in the configured base currency:

```json
{"categories":{"Example category":{"2040-01":"120","2040-02":"150"}}}
```

Blank cells, formulas returning an empty string, and omitted trailing cells at verified intersections are zero. Missing/ambiguous categories or month headers are errors. Do not substitute a previous month's budget or write zero into the spreadsheet.

Daily allowance = monthly magnitude / days in that date's month. Sum all requested dates for the period allowance, including future dates in an ongoing period. Never divide a monthly budget by a fixed four weeks. Keep Decimal arithmetic unrounded until display. Being below a full-period ceiling does not establish time-adjusted pace.

## Budget checks

All categories are monthly unless their exact spreadsheet names appear in local `ongoing_categories`. For each month touched by the request, compare its net spending from the first of the month through the earliest of the requested end, the verified cutoff if available, and the review time. Check each month separately when dates cross a month boundary.

- **Monthly** uses the full calendar month's limit.
- **Ongoing** uses a single cumulative allowance from the first of the month through Sunday of the review week, capped at month-end. Use the week containing the last requested date in that month, or the current week if that date is in the future. Multiply the monthly limit by the included calendar days and divide by the number of days in the month. Spending above the allowance in one week can be offset by spending below it in another week of the same month.

## Rates

Fetch current Wise rates for every account currency used and the chosen local display currency, converting to the configured base. Historical periods still use current rates unless the user explicitly requests historical rates. The base itself needs no conversion. Never substitute saved historical transaction rates or another provider.

Example rate input with an invented rate, not a current quote:

```json
{"base_currency":"USD","retrieved_at":"2040-01-10T12:00:00Z","rates":{"CAD":{"base_per_unit":"0.75","source_url":"https://wise.com/gb/currency-converter/cad-to-usd-rate"}}}
```

`base_per_unit` means base-currency units per one foreign-currency unit. Base amount = account amount × its rate. Local display amount = base amount / local rate. Cite the fetched rate and retrieval time in the response. Missing rates leave conversion incomplete; do not invent them. The script checks the base currency, positive rates, source URL, and snapshot age. `--as-of` supports explicit historical-rate runs and reproducible tests, not disguising stale data as current.

## Accounting

Use account debits once per stored transaction. Exclude economic kinds `income` and `internal`; their category labels need not match expense categories. Net identifiable refunds as negative spending. Unclear credits require classification of their kind. The merchant charge in a description is additional transaction detail, not an extra account debit.

Retain the included transaction list in report output so daily sums reconcile with the period total. Flag expense category strings absent from the live budget; do not discard their spending, invent budgets, or rename historical classifications automatically.
