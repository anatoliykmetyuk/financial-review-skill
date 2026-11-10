# Sony Bank savings history

Use the common Fetch workflow and the configured browser through computer use. Sony Bank's savings history supplies the posting date, deposit or withdrawal, currency, running balance, and memo, including Visa merchant names when available. Fetch reads these rows directly from the browser.

## Optional sign-in prefill

When the user requests prefill, save their confirmed branch number and account number under `banks.sony-bank` in Git-ignored `data/settings.yaml`. Use `branch_number` (3 digits) and `account_number` (7 digits) as quoted strings to preserve leading zeros. The pair belongs to the login profile and is shared by its tracked currencies. Keep the values out of reports and tracked files.

When Fetch reaches the [official Sony Bank login form](https://sonybank.jp/pages/db/dbca0100/), read the saved pair and fill only **Branch number (店番号)** and **Account number (口座番号)**. Leave matching prefilled values in place. If either saved value is missing or invalid, or the form already shows a conflicting value, hand the form to the user. Let the user enter their password, submit the form, and complete any further verification before resuming Fetch.

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
