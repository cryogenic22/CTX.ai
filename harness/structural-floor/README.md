# Structural floor

`CLAUDE.md` and `.claude/rules/conservation-gates.md` state the principle:

> **Separation of authorship — you do not edit the bar to pass.**

and then say plainly that enforcing it was *"flagged, not built — owner's call"*.
This directory builds the half a repository can build for itself.

## How it works

```
harness/structural-floor/protected-surface.txt   the success-definition surface
                  |
                  |  scripts/gen_codeowners.py
                  v
          .github/CODEOWNERS                     owner review on every path above
```

Two checks fail on drift, so the two files cannot separate quietly:

- `.github/workflows/structural-floor.yml` runs `gen_codeowners.py --check`
- `tests/test_protected_surface_sync.py` runs it too, and feeds violations

To change what is protected, edit `protected-surface.txt`, then:

```
python scripts/gen_codeowners.py
```

Editing `.github/CODEOWNERS` directly fails the gate. That is the point.

## What this is, honestly

**Ceiling.** A generated CODEOWNERS file is advisory. It asks for review; it
does not require it, and nothing here stops a commit.

**Floor** arrives only when the owner enables, on GitHub:

1. Branch protection on `main`
2. Require review from Code Owners
3. Disallow self-approval / require approval from someone other than the author
4. Require the `structural-floor` and `ci` checks to pass

Steps 1–4 are owner actions. A repository cannot assert them about itself, and
this README will not pretend otherwise — the same rule the PF-11 threat model
applies to security claims: surface, flag, audit, degrade; never guarantee,
prevent or block.

## Why these paths

Each entry in `protected-surface.txt` is somewhere a change would move the
definition of success rather than the code:

| Group | Why it defines the bar |
|---|---|
| `CLAUDE.md`, `AGENTS.md`, `.claude/rules/` | owner-authored doctrine |
| `scripts/check_*.py`, `gen_codeowners.py` | a gate the implementer can edit is not a gate |
| `.github/workflows/`, `CODEOWNERS` | what CI actually enforces |
| `**/PREREGISTRATION*.md` | amended only by commit **before** a scored run |
| `**/results/` | eval results are immutable |
| `test_p0_trust_repairs.py`, `test_negation_preservation.py` | the two invariants the product rests on |
| this directory | the surface itself |

## Related

- `.claude/commands/review.md` — the flag list to walk before a handoff
- `.claude/commands/before-i-commit.md` — the pre-commit attestation
- `.github/pull_request_template.md` — required sections, enforced by
  `scripts/check_pr_template.py`
