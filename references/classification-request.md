# Classification request

Use the existing [HTML template](../scripts/classification-table.html) for every classification request. Do not reconstruct its styling, substitute a Markdown table, change its typography, allocate percentage widths to the short columns, or move justifications outside the table.

Populate the template from the fresh unclassified query in the shared workflow. Keep its six headers and chronological order. Each row has six cells:

- **ID:** the database transaction ID.
- **Date:** weekday, abbreviated month and day, and 24-hour time on separate lines, using `<br>` between them. Use the reporting timezone for timed rows. For Sony Bank, compute the weekday from the bank posting date and omit the time line.
- **Description:** an accurate, concise transaction description.
- **Account:** a recognizable account name, separate from the amount.
- **Amount:** signed account amount in its account currency. Outflows have a leading minus sign, such as `-€100`; inflows have no minus sign, such as `€100`. Preserve meaningful precision and use a currency code when a symbol would be ambiguous.
- **Proposed Category:** `<strong>` around only the proposed category, followed by `<span class="reason">` containing a brief unbolded justification in the same cell.

Replace `__TABLE_CONTEXT__` with the actual shared year or years and reporting timezone. Replace `__TABLE_ROWS__` with the generated `<tr>` rows. HTML-escape all inserted text, including bank descriptions, account names, categories, justifications, and context; only the deliberately generated row/cell/formatting markup is HTML. Do not insert raw bank text as markup.

Write the populated fragment into the current chat's durable working directory, never over the shared source template and never with personal examples in repository source. Present it inline using the visualization content reference, following the visualization guidance available in the environment:

```text
visualize{"path":"/absolute/current-chat/work/classification-request.html"}
```

Keep the content-sized ID, Date, Account, and Amount columns and the small gaps. Description and Proposed Category wrap into the remaining space. Retain the narrow-screen wrapping behavior; no horizontal scroll, clipping, hidden text, or smaller typography to force a fit. Check the populated output at the available width. If the environment cannot display the fragment inline, state that limitation rather than silently changing the approved format.

This table contains suggestions, not saved decisions. Only confirmed inferences become manual assignments or reusable rules through the shared workflow.
