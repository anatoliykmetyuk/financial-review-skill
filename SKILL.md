---
name: financial-review
description: Review bank spending against the live budget, maintaining a local SQLite transaction ledger and YAML classification rules. Use for financial review or fin review requests, by period or by category, and for classification corrections in this workflow.
---

# Financial Review

`data/transactions.sqlite3` owns transactions and classifications. `data/rules.yaml` owns reusable keyword rules. The live budget spreadsheet owns expense categories and budgets. All user choices belong in ignored `data/settings.yaml` or account records, never in the skill's source. This skill requires no other financial application.

## First run and configuration

Read [data and CLI](references/data-and-cli.md) before running scripts. If the runtime or `data/` is absent, run its bootstrap commands automatically. `init` creates the file structures and returns missing setup fields; it does not guess currencies, timezone, or category aliases.

Before the first review, finish setup in one guided conversation:

1. Collect or confirm the local timezone, default period, base/report currency (also the spreadsheet's currency), optional second display currency, and the threshold separating small from large overspending. Chrome is the initial browser choice; honor an explicitly requested alternative and save it locally.
2. Find the budget spreadsheet through the connected Google Drive integration or ask for it. Following its Google Sheets skill, inspect metadata and bounded ranges. Identify the intended tab and save its ID/name locally. The tab specifies monthly budgets for categories; do not prescribe or persist a required sheet layout. Confirm only genuinely ambiguous budget meanings or source choices.
3. Ask which bank accounts to track, and their source timezones. Register them with `account`. Discover details from available CSVs or bank UI where possible. Collect optional category shortcuts; an empty alias map is valid.
4. Write the complete local settings using the data reference's schema and run `configure`. Check `status.setup`: resolve every missing item, including tracked accounts and their source timezones, before declaring setup finished or producing reviews. Do not ask the user to write YAML themselves.

On later runs, read the saved configuration. Script errors identify missing configuration; do not silently fall back to somebody else's setup. Unreadable existing data is an error, not permission to replace it with an empty installation.

## Review modes

A named category selects a category review with the configured base and local currencies. Without a category, review all expense categories in the configured base currency without charts. Resolve shortcuts through local `category_aliases`; there are no built-in category names.

Use the requested timezone/period/currency overrides when supplied; otherwise use local defaults. “This week” means the containing Monday–Sunday week, “last week” the preceding one, and “last month” the preceding calendar month. Honor explicit ranges. Future days are unavailable, not zero spending.

## Shared workflow

1. Check `status.setup` and read local settings. Resolve the mode and dates. Inspect transactions and available CSVs for every tracked account.
2. Reuse suitable local exports, including a current-day partial snapshot; disclose its cutoff. Download only missing data or an explicit refresh. Follow the relevant bank reference, initially [Wise](references/banks/wise.md). Use Chrome by default, or the locally configured alternative. Additional banks need their own acquisition reference and adapter, not guessed CSV columns. Ingest new data before classification.
3. Read the configured live spreadsheet through Google Drive, with metadata before bounded ranges. Discover the current budget values regardless of the tab's arrangement; [budgets and currency](references/budgets-and-currency.md) defines the normalized calculation input. The user may reorganize the spreadsheet freely. Adapt extraction automatically rather than asking the user to repair a layout or technical configuration. Never edit the spreadsheet merely to perform a review.
4. Run `classify` over the entire requested period, including for category reviews. Current rules update non-manual rows in those dates only. Manual assignments survive imports and rule updates.
5. Query `query --unclassified` for the requested period after running automatic classification. Request category decisions strictly for those returned rows whose stored `category` is null. Existing database classifications and automatic rule matches need no confirmation; never include them in a proposed-classification request, even if they were just imported or their category seems surprising. If no unclassified rows remain, skip this request. For unresolved rows, research merchants when useful and follow the table format below. Save inferred categories only after user confirmation; do not produce the final report until resolved.
6. An explicit reusable merchant/keyword instruction changes rules; a specific transaction correction becomes a manual database assignment. Ask if that scope is ambiguous. Use scripts, rerun classification, and query the remaining unclassified rows before any further request. Do not ask again about resolved rows. Do not create an overrides file or retain corrections only in conversation. If a credit's economic kind remains unclear, ask only whether it is income, a refund, or an internal transfer; do not reopen an already stored category decision.
7. Fetch current Wise rates into the configured base currency, including for historical periods unless historical rates are requested. Run `report`. Flag categories absent from the live sheet, resolve budget mappings, and use [category review](references/category-review.md) or [general review](references/general-review.md).

### Classification request table

Every classification request must reuse [scripts/classification-table.html](scripts/classification-table.html), populated and displayed inline as specified in [classification request](references/classification-request.md). This is the approved compact six-column layout, with three-line dates and justifications inside the Proposed Category cells. Do not substitute a Markdown table or redesign it per review.

## Data and operating rules

- There are only `accounts` and `transactions` tables. Do not store evidence, import history, coverage records, fingerprints, or raw source rows. User corrections update account/transaction data directly.
- Source timezones are account parsing configuration; transactions have one UTC timestamp. Ask about missing source timezones or conflicting duplicates rather than inventing values.
- A report cutoff describes the current output only and is not persisted. Do not infer full coverage from an empty date. A blank cell at a verified category/month intersection is a zero budget; missing or ambiguous rows/months are errors.
- Ask the user to log into the configured browser when necessary. Never retrieve credentials.
- Use the scripts' daily-backup implementation and retention policy documented once in [data and CLI](references/data-and-cli.md). Perform calculations through scripts rather than ad hoc arithmetic.
