# Local configuration and CLI

## First-run setup

The agent performs setup for the user. From the skill directory:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r scripts/requirements.txt
.venv/bin/python scripts/finance.py init
```

`init` creates the two-table database, empty `rules.yaml`, `settings.yaml` with unset user choices, and the `backups/` directory, all under ignored `data/`. Its JSON lists what setup still needs. Re-running it preserves existing files and transactions. Python 3.11+ and the pinned PyYAML dependency are required.

Collect or discover every required choice before finishing setup: timezone, default period, base currency used by the budget, local display currency, overspending warning threshold, spreadsheet/tab, category shortcuts if wanted, and tracked accounts with source timezones. Chrome is the initial browser choice. Present discovered choices for confirmation when uncertain rather than repeatedly asking for facts already available from the client, spreadsheet, or CSVs.

Populate local settings, then run `configure data/settings.yaml` to validate them. Alternatively use an ignored `data/setup.yaml` draft; `configure` validates it before replacing active settings. Register accounts with `account`. Finally check `status.setup.ready`; finish every item in `status.setup.missing` before producing reviews. The command line reports missing choices; the conversational agent asks the setup questions and writes the files, so the user need not hand-author YAML.

Here is a complete **fictional example**, not a template of another user's setup:

```yaml
version: 2
defaults:
  timezone: UTC
  browser: chrome
  period: this_month
  base_currency: USD
  local_currency: CAD
  yellow_excess_max: '10'
budget:
  spreadsheet_id: YOUR_SPREADSHEET_ID
  sheet: Example sheet
category_aliases:
  shortcut: Example category
ongoing_categories:
  - Example category
banks: {}
```

The configured period is one of `this_week`, `this_month`, `last_week`, or `last_month`. The warning threshold is in the base currency. Empty alias maps and bank maps are valid; account details live in the accounts table. `ongoing_categories` contains exact spreadsheet category names and defaults to an empty list when omitted. Individual review arguments can override saved timezone/currency choices.

There is no saved spreadsheet layout. On each review the skill discovers category/month budgets from the current sheet through the connected spreadsheet tools. See [budgets and currency](budgets-and-currency.md).

On later runs, scripts read this configuration directly. No private choices belong in source, references, or tests. Missing configuration stops the operation with the fields needed; it never silently chooses a currency, timezone, or alias. Existing installations can edit their local settings and validate with `configure`.

## Database and money

There are exactly two tables:

- **accounts**: `id`, `name`, `currency`, `source_timezone`, `tracked`.
- **transactions**: `id`, `account_id`, `bank_transaction_id`, `timestamp_us`, optional `posting_date` and `balance_after_minor` for Sony Bank, `description`, `merchant`, `payment_reference`, `details_type`, `amount_minor`, `currency`, `charged_amount_minor`, `charged_currency`, `kind`, `category`, `classification_origin`.

Account IDs are namespaced strings such as `example-bank:account-a`. There is no separate institution table. `timestamp_us INTEGER` is the sole transaction timestamp, storing UTC Unix microseconds. SQLite has no native date/time type. Tables use ordinary typing, not STRICT mode.

Money uses integer minor units and currency codes, without floating-point storage. Decimal input is scaled exactly; fractional minor units or 64-bit overflow cause an error, never rounding. Report JSON converts amounts to major-unit decimal strings. IDs, currency codes, descriptions, and category labels are strings; flags and timestamps are integers. Manual classification origin preserves explicit decisions across rule changes.

There are no stored import records, evidence, raw source rows, fingerprints, coverage registries, legacy queues, or metadata tables. Wise and normalized CSV imports compare account, ID, timestamp, and transaction values. Sony Bank uses its [posting date and running balance](banks/sony-bank.md#import-the-browser-rows). Repeated imports preserve manual assignments. Conflicting duplicates require a user decision.

Schema version is in `PRAGMA user_version`. Supported older schemas upgrade directly in the same file, preserving actual transactions/classifications and using the daily backup policy below. An unrepresentable amount rolls the transaction back.

## Commands

The following are abstract examples; values must come from the completed local setup:

```sh
.venv/bin/python scripts/finance.py status
.venv/bin/python scripts/finance.py account --bank example-bank --source-id account-a --name 'Example account' --currency USD --source-timezone UTC
.venv/bin/python scripts/finance.py ingest /absolute/statement.csv --adapter normalized --account example-bank:account-a
.venv/bin/python scripts/finance.py classify --start 2040-01-02 --end 2040-01-08
.venv/bin/python scripts/finance.py query --start 2040-01-02 --end 2040-01-08 --unclassified
.venv/bin/python scripts/finance.py assign 123 --category 'Example category'
.venv/bin/python scripts/finance.py assign 456 --category 'Example category' --kind refund
.venv/bin/python scripts/finance.py clear 123
.venv/bin/python scripts/finance.py rule --keyword 'Example merchant' --category 'Example category' --start 2040-01-02 --end 2040-01-08
.venv/bin/python scripts/finance.py report --start 2040-01-02 --end 2040-01-08 --budget /absolute/budget.json --rates /absolute/rates.json
```

`assign` saves a manual classification; `clear` permits rules to apply again. Keyword updates trim the phrase, remove case-insensitive duplicates across categories, and reclassify only the supplied period. Longest literal keyword wins, with stable rule order for ties. Category shortcuts come only from local `category_aliases`.

`report --category 'Example category'` produces a category review; without category it produces a general review. The report includes `budget_checks` for category and month, and `categories` for the requested dates. Optional `--cutoff ISO_INSTANT` caps spending at a verified cutoff for that output. Without a cutoff, observed days are partial and other dates unavailable. A blank date does not prove zero spending. `--as-of` is for explicit historical-rate runs and reproducible tests; normal reviews fetch current rates.

## Bank adapters

Register accounts with their actual currency and source timezone. See the [Wise](banks/wise.md) and [Sony Bank](banks/sony-bank.md) references for each adapter. The normalized CSV adapter accepts other sources with these required columns:

```text
timestamp,amount,currency,description,kind
```

Optional columns are `bank_transaction_id`, `merchant`, `payment_reference`, `details_type`, `charged_amount`, `charged_currency`. Use signed account amounts and offset-bearing timestamps when possible. Kinds are `expense`, `refund`, `income`, `internal`, and `credit-review`. Charged amount/currency are supplied together or neither. Do not guess unknown CSV formats.

## Backups

Before the day's first database write, create `data/backups/YYYY-MM-DD.sqlite3` using the configured timezone. Later writes reuse it without overwriting; reads create none. Initializing a brand-new empty database creates no empty-file backup. These snapshots back up SQLite, not configuration files.

On access and before the first write, automatically retain only today and the previous six dates, at most one snapshot per date and seven snapshots total. Legacy timestamp-named duplicates are consolidated, keeping the newest where no daily snapshot exists. No permission prompt, background service, or extra database bookkeeping is needed.

## Development checks

Run `.venv/bin/python -m unittest discover -s tests -v`. Git ignores the entire local `data/` directory, runtime, caches, and generated outputs. Repository-specific maintenance and privacy requirements are in `AGENTS.md`.

For tooltip changes, open a generated category chart with the visualization wrapper in a Playwright CLI session and run `run-code --filename /absolute/skill/tests/tooltip_browser_checks.js`. This exercises hover recovery after focus loss, clicks, Escape, leaving points, responsive column alignment, and touch dismissal. Use synthetic transaction data for reusable fixtures.
