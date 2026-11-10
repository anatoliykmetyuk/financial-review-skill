# Sony Bank savings history

Use the common Fetch workflow and the configured browser through computer use. Sony Bank's savings history supplies the posting date, deposit or withdrawal, currency, running balance, and memo, including Visa merchant names when available. Fetch reads these rows directly from the browser.

## Optional sign-in prefill

To enable prefill, save the user's confirmed `branch_number` (3 digits) and `account_number` (7 digits) under `banks.sony-bank` in Git-ignored `data/settings.yaml`. Store them as quoted strings to preserve leading zeros. Once saved, the pair applies to every sign-in for that profile, across its tracked currencies. Keep the values out of reports and tracked files.

1. Whenever Sony Bank presents a sign-in form during Fetch, apply prefill to the visible form regardless of its URL. Locate the editable **Branch Number (店番号)** and **Account Number (口座番号)** fields by their visible labels and the current browser state.
2. Read the saved pair before contacting the user. If the saved values are valid and both fields are empty or already match, fill the empty fields and verify that both now match.
3. Hand off the same tab for the user to finish signing in. If prefill could not complete, tell the user what blocked it and leave any conflicting values for them to resolve. Wait for sign-in to complete before resuming Fetch.

## Accounts and date range

Register each tracked savings balance with `account --bank sony-bank`, its currency, a stable source ID for that balance, and the confirmed source timezone. Use the registered accounts to select currencies. The history screen shows one savings balance per available currency for the signed-in profile. Verify the intended profile if several are in use.

1. Open [Savings Account Transaction History](https://sonybank.jp/pages/ea/eaba0600/) in the configured browser. If prompted to sign in, follow the prefill and handoff steps above. The same screen is reachable through **Transaction history → Savings Account Transaction History**.
2. Select the account's currency and the inclusive posting date range. Use whole source dates, including today when needed, and include both deposits and withdrawals. Choose **Display**. Verify the currency, dates, and unfiltered results before reading the rows.
3. Read the result count and all rows across the result pages. Match the number collected to the displayed count. If results are truncated or the count cannot be reconciled, split the query into smaller date ranges and verify those individually. Treat zero rows as evidence only after verifying a successful query for the intended dates and currency.
4. For today, record the bank's as-of time if available, or the time the query was submitted, as temporary coverage context. Today remains partial. Reuse results within the current review and query again on a later review when today's coverage is needed. Use the earliest verified cutoff across tracked accounts when reporting on combined coverage.

## Import the browser rows

Send one JSON object per verified account and range to `ingest - --adapter sony-bank --account ACCOUNT_ID` on standard input. The object contains `currency`, `start`, `end`, `result_count`, and `rows`. Use inclusive ISO dates for `start`, `end`, and each row's `date`. Each row also contains the displayed `currency`, `description` (memo or 摘要), signed `amount`, and `balance_after`. Amounts and balances are plain decimal strings without grouping separators or currency symbols. Convert the deposit or withdrawal column to a signed amount and keep the running balance as shown. Use the original bank memo, including any card reference.

The adapter normalizes full-width text, extracts Visa merchant names and references, and identifies explicit transfers between Sony Bank savings balances as internal. A rule matching `SONY BANK SAVINGS TRANSFER` can label those rows with the user's transfer category. Unknown credits follow the shared classification workflow.

The adapter stores midnight in the source timezone as UTC microseconds and preserves the bank's posting date for reporting. Reports show the posting date without a clock time. Imports reconcile the posting date, signed amount, running balance, and available Visa reference within each account. If those fields cannot distinguish rows reliably, resolve the ambiguity before importing. Repeat imports preserve manual classifications. Keep the browser payload and coverage details temporary.
