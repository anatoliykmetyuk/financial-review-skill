# Repository architecture and maintenance

Keep the skill compact, self-contained, and configuration-driven. Prefer straightforward code and shared functions over extra frameworks or bookkeeping.

## Separation of concerns

- This file governs how the repository is maintained. Skill behavior belongs in `SKILL.md`, its references, and executable scripts. Do not duplicate business rules here.
- Keep the shared workflow in one place. References hold specialized instructions; scripts implement reusable processing. Link to the relevant source rather than repeating it.
- User-specific configuration and state belong exclusively under the Git-ignored `data/` directory. Scripts read configuration there. First-run setup must collect or discover required choices and create the necessary files; do not embed a particular user's defaults in source.
- Never encode an individual's spreadsheet layout in shared scripts, skill text, references, or tests. Shared calculations consume category/month budget amounts, independently of sheet structure.
- Preserve existing local configuration and data when changing the implementation. Keep changes focused on the requested behavior.

## Privacy and version control

- Never commit private, identifying, personal, or user-specific information. Account/spreadsheet identifiers, personal paths, real transactions, budget figures, merchant rules, category aliases, spreadsheet layout, and selected currencies/timezones belong only under `data/`.
- Skill text, references, scripts, templates, and tests must remain independent of a particular user's setup. Documentation examples must be abstract. Test fixtures must be independently invented synthetic data, never copied personal data, even with names removed.
- Before staging or committing, inspect every non-ignored file and ensure `data/` remains ignored. Check examples and configuration assumptions as well as identifier patterns.
