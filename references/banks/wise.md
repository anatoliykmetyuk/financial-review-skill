# Wise acquisition and adapter

Read only when checking Wise exports, acquiring missing data, or configuring Wise accounts. The common classification/report workflow remains in SKILL.md.

## Reuse downloaded exports first

Inspect existing transactions and local CSVs, including the user's Downloads directory for suitable CSV folders and ZIPs. Extract ZIPs into an adjacent archive-stem folder; preserve ZIPs and do not overwrite differing files. Verify headers, statement range, account IDs, and export cutoff. A downloaded current-day export is reusable and partial; do not repeat the download merely because its cutoff predates the request time or it has no purchases on a covered day. Apply [the shared workflow](../../SKILL.md#shared-workflow) for the ongoing-day completeness rule and user opt-outs.

Use the tracked Wise accounts registered in SQLite, including their IDs, names, currencies, and source timezones. On first setup, ask which accounts to track and use their bank account IDs. Currency alone cannot distinguish multiple accounts or jars. Do not substitute removed/closed accounts or another-currency jar. Reuse configured accounts and timezones rather than asking again on every review.

## Download missing coverage or an explicit refresh

Use the configured browser through the computer-use tool, with Chrome as the initial default. Read its current instructions and inspect fresh UI state. Do not substitute another browser, undocumented endpoints, or the Wise developer API.

1. Open https://wise.com/balances/statements/balance-statement/create.
2. If login is needed, ask the user to log in to Wise in Chrome and wait. Do not attempt login or retrieve credentials. Resume afterward.
3. Select dates covering missing data, the ongoing day when suitable bank export files are unavailable, or the explicitly requested refresh, in the report timezone, accounting for the source timezone. Overlap previously imported dates when needed. A currently ongoing export ends today, never at a future month-end. Obtain adjacent dates when needed to cover local report boundaries.
4. Select exactly the configured tracked accounts. If account identities are unclear, inspect the selection and clarify.
5. Choose **CSV**, keep **Display transactions with fees shown separately** unchecked, and retain **Don't repeat**. Do not schedule recurring statements.
6. Generate and verify the summary's accounts, dates, and format. Download to Downloads, verify completion, and extract if zipped.
7. Verify every selected account's file, headers, identity, range, and cutoff; use these details for the current review only; do not store an import log. A filename ending today does not prove full-day coverage.

## Source timezone and coverage

The observed browser CSV timestamps are `DD-MM-YYYY HH:mm:ss.fraction` **without a timezone offset**. Read the source timezone from the account record. For a new account, do not infer the source timezone from currency, account location, browser timezone, spreadsheet timezone, or file modification time. Establish the export timezone from statement/UI evidence or a known transaction time confirmed by the user. Set it with `account --source-timezone ...`. Do not store evidence. If unknown, retain the files and ask before ingestion.

Ingest the CSV directly without storing import records, coverage, or provenance. For an ongoing review, note the export cutoff in the response and optionally pass it to `report --cutoff`; this is temporary report context. If unknown, disclose that the available data may be partial. Do not turn absent transactions into proof of zero spending.

## Adapter

`ingest --adapter wise` requires `TransferWise ID`, `Date Time`, `Amount`, `Currency`, `Description`, and `Transaction Details Type`. It retains the raw row and uses Description, Merchant, Payment Reference, and Transaction Details Type for matching. Signed Amount/Currency is the account debit/credit.

A recognized `Card transaction of … CUR issued by …` description supplies optional original charged amount/currency. It is metadata, not another debit. Unknown formats retain the description; do not guess the charged amount.

CARD debits are expenses and CARD credits are identifiable card refunds/reversals. CONVERSION rows are internal; DEPOSIT rows are income. Other positive transfers require review of their economic kind. Source IDs may recur for payment, reversal, and refund, so never deduplicate by source ID alone.
