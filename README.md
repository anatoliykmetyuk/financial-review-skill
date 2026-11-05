# Financial Review

Review your spending against your budget by asking Codex in plain language. The skill keeps a local transaction ledger, classifies transactions, and compares spending with the monthly budgets in your spreadsheet. No separate financial application is required.

## Requirements

You need a Google Sheet recording how much budget is allocated to each category for each month. Use any layout convenient for you; no template, fixed rows, columns, or section structure is required. The skill reads the current layout each review.

Choose any budget currency convenient for you. During setup, that currency becomes the base currency for budget comparisons and reports. Make the category names, applicable months, budget amounts, and currency understandable from the sheet. Codex needs access to it through the connected Google Drive integration.

For example, a sheet could contain the following fictional monthly budgets, all in the user's chosen currency:

| Category | January 2035 | February 2035 | March 2035 |
|---|---:|---:|---:|
| Rent | 200 | 220 | 200 |
| Food | 80 | 80 | 100 |
| Entertainment | 50 | 60 | 50 |

This is only an illustration, not a required layout. The currency can be stated in the sheet and confirmed during setup.

## Getting started

First, ask your agent to install the skill:

> Clone https://github.com/anatoliykmetyuk/financial-review-skill into my user-level skills directory as financial-review, so it is available across projects. For Codex, use `${CODEX_HOME:-$HOME/.codex}/skills/financial-review`.

Installation means cloning this repository into your agent's user-level skills directory, outside any individual project. For Codex, you can also run:

```sh
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
git clone https://github.com/anatoliykmetyuk/financial-review-skill.git "${CODEX_HOME:-$HOME/.codex}/skills/financial-review"
```

For another agent, use its supported user-level skills directory. If the skill is not visible immediately, start a new chat or restart your agent.

Once installed, ask:

> Set up financial review.

Codex prepares the local files and guides you through setup. You do not need to write configuration files or run commands yourself.

You will choose or confirm:

- Your budget spreadsheet and tab.
- The bank accounts to track and the timezone used by their exported timestamps.
- Your reporting timezone and default review period.
- Your base currency, matching the budget spreadsheet, and an optional second display currency.
- The amount of overspending that separates yellow from red warnings.
- Any category shortcuts you want to use in requests.

You need access to the spreadsheet through the connected Google Drive integration and access to your bank statements. Wise acquisition and CSV import are supported; another bank requires a compatible adapter before its exports can be imported. Bank access uses Chrome by default. If login is needed, Codex asks you to log in yourself.

## Ask for a review

### General review

> Financial review for this month.

> Financial review for the past week.

> Financial review from January 10 through January 20, 2035.

A request without a category reviews spending across categories. You get a concise report in your base currency, without charts. Overspending is marked 🟡 or 🔴 according to your configured threshold. When spending is within budget and there are no unresolved data or budget problems, the report shows 🟢.

If you omit the period, your saved default applies. “This week” means Monday through Sunday. An ongoing week or month is valid: future days are not treated as zero spending. The comparison uses the allowance for the full requested period, and the report states the available data cutoff.

### Category review

> Financial review for Example category this month.

> Review Example category for the last two weeks, using GBP as the local display currency.

Replace “Example category” with a category from your spreadsheet or a saved shortcut. A category review includes an allowance, spending, and remaining-budget table, a daily spending line chart with transaction details, and budget progress bars. It uses your base currency and configured second currency unless you request an alternative.

For periods spanning multiple calendar weeks, the budget bars share one spending total: the first fills before spending overflows into the next. Boundary weeks include only the dates you requested. The bars show how much of the period's allowance has been used; the line chart shows when spending happened.

## What happens during a review

Codex reuses suitable available statements and obtains missing bank data, imports transactions without duplicating repeated imports, reads your current spreadsheet, and applies classification rules. You can explicitly ask to refresh bank data.

If transactions still need classification, Codex pauses before the final report and shows their local date/time, description, account amount, suggested category, and reasoning. Suggestions are saved only after you confirm them.

You can respond with either a reusable rule or a one-off decision:

> Always classify transactions containing “Example merchant” as Example category.

> Assign transaction 123 to Example category, just for this transaction.

Use the transaction ID shown in the classification table. One-off decisions remain saved even when rules change. Updated rules are applied to the active review period; other history is reconsidered when reviewed. Even a category review resolves unclassified transactions throughout the requested period first.

You can also correct a previous classification in the same way. If a credit is unclear, Codex may ask whether it is income, a refund, or a transfer between your accounts.

## How the budget is interpreted

Your spreadsheet defines category names and monthly budget amounts. You can reorganize it: Codex reads its current layout each review. The calculation script receives category/month amounts and does not depend on spreadsheet coordinates. The skill does not edit your spreadsheet to perform a review.

- A verified blank budget cell means zero. An unclear or missing budget needed for a comparison requires clarification.
- A spreadsheet category with no transactions in the period is normal.
- An expense transaction classified under a category absent from the spreadsheet is flagged for resolution.
- Daily allowance is the month's budget divided by that month's number of days. A period's allowance sums its daily allowances, including across month boundaries.
- Spending comes from account debits. Income and internal transfers are excluded, and identifiable refunds reduce spending.

Currency conversions use current Wise rates, including for past periods unless you explicitly request historical rates. Reports disclose the rate retrieval time and data cutoff. Being within the full-period allowance does not necessarily mean spending is on pace.

## Your local data

Personal settings, classification rules, and the transaction database live under the skill's Git-ignored `data/` directory. They persist between chats. Git does not back them up or transfer them to another computer. Bank acquisition and spreadsheet access still use their respective external services.

The database has automatic daily backups with a rolling seven-date retention window. These protect the database, not settings or rules. See [backup details](references/data-and-cli.md#backups) for the exact policy.

To change your setup, ask Codex to update your financial-review settings, tracked accounts, or category shortcuts. To use another computer, either securely transfer your private local data or complete setup again; installing the skill's source alone does not restore your ledger.
