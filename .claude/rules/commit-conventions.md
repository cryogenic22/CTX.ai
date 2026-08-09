---
description: Commit message conventions detected from git history
alwaysApply: true
---
# Commit Conventions

This project uses **conventional commits**.

Format: `type(scope): description`

**Detected prefixes** (from recent history):
- `Board`
- `Scorecard`
- `Cohort`
- `fix`
- `Discipline`

**Recent examples**:
- Discipline: vacuous-green guard codified (owner-mandated)
- Board: PF-11 approval + P1 batch handoff; re-review requested (85302ea..600aef9)
- TM-4: role-evidence occurrences replace irreversible first-wins role (TC-8/9)
- TM-3/TM-16: journal degradation + quarantine rotation (TC-6/7/20)
- TM-2: authority axes â€” LOCAL_RATIFIED migration, no elevation (TC-4/TC-5)

# Rules

- Keep commit messages concise (under 72 chars for first line)
- Reference issue numbers when applicable
- Always use a recognized prefix from the list above
- Include scope in parentheses when the change targets a specific module
