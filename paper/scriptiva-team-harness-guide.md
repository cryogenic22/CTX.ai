# Harness Engineering Guide — For the Scriptiva SCA Team

## Before Starting Any New Coding Task

### 1. Generate the Harness (one-time setup, refresh weekly)

```bash
# From the Scriptiva_SCA root:
pip install -e /path/to/CTX_mod  # Install ctxpack if not already done

# Generate the full harness
ctxpack codebase harness .

# This creates:
#   .claude/rules/anti-slop.md         — utility locations, DO NOT DUPLICATE list
#   .claude/rules/test-requirements.md — testing conventions for this codebase
#   .claude/rules/commit-conventions.md — commit message format from git history
#   .claude/hooks/quality-check.py     — post-write drift detection
```

These files auto-load in Claude Code. No additional configuration needed — Claude Code reads `.claude/rules/` when you enter relevant directories.

### 2. Refresh After Major Changes

```bash
# After adding new modules, refactoring, or merging large PRs:
ctxpack codebase harness . --force-refresh
```

The harness detects actual utilities, patterns, and conventions from your code. When the code changes significantly, the harness should be regenerated so agents see the current state.

### 3. Add the Codebase Map to CLAUDE.md

Add this line to your existing CLAUDE.md (don't replace it — supplement it):

```markdown
## Codebase Map
@.claude/codebase-map.md
```

Generate the map:
```bash
ctxpack codebase export --format claude-md . -o .claude/codebase-map.md
```

---

## For Every Coding Task (Agent Instructions)

When you start a new task in Claude Code, begin with this prompt structure. Copy and adapt:

---

### The Task Prompt Template

```
## Task
[Describe what you're building — be specific about the feature, endpoint, component, or fix]

## Constraints
- Follow the patterns in .claude/rules/anti-slop.md — check existing utilities before creating new ones
- Every new function needs a test. No exceptions. Check test-requirements.md for the testing framework and conventions.
- Follow commit conventions in .claude/rules/commit-conventions.md
- Keep files under 500 lines. If a file would exceed this, split it.

## Before Writing Code
1. Read the relevant sibling files in the same directory — match their patterns exactly
2. Check if a similar utility/function already exists (search the codebase)
3. Identify which test file this change needs and create/update it alongside the implementation

## Quality Checklist (verify before committing)
- [ ] Tests pass: `pytest apps/api/tests/ -x` (backend) or `npm run test -w @rescape/web` (frontend)
- [ ] No new utilities that duplicate existing ones
- [ ] Type annotations on all public functions
- [ ] Alembic migration if any model changes
- [ ] Commit message follows conventional format (feat/fix/chore)
```

---

### Example: Adding a New API Endpoint

```
## Task
Add a PUT endpoint for updating user preferences at /api/v1/users/{user_id}/preferences

## Constraints
- Follow the patterns in .claude/rules/anti-slop.md
- Look at apps/api/app/api/v1/routes/ for existing route patterns — match exactly
- Use Depends(get_current_user) for auth (see anti-slop.md utility list)
- Return a Pydantic response model, not a raw dict
- Add the route to the router includes in apps/api/app/api/v1/__init__.py

## Before Writing Code
1. Read apps/api/app/api/v1/routes/auth.py as the pattern reference
2. Check if a preferences model already exists in apps/api/app/models/
3. Create the test file at apps/api/tests/test_user_preferences.py

## Deliverables
1. Route handler in apps/api/app/api/v1/routes/users.py (or new file if appropriate)
2. Pydantic request/response models
3. Service function in apps/api/app/services/
4. Test file with at least 3 test cases (happy path, auth failure, validation error)
5. Alembic migration if new model fields needed
```

---

### Example: Adding a New React Component

```
## Task
Add a PreferencesPanel component to the user settings page

## Constraints
- Follow the patterns in .claude/rules/anti-slop.md
- Check apps/web/components/ui/ for existing reusable components — use them, don't recreate
- Use the API client from apps/web/lib/api.ts — don't create new fetch wrappers
- Add a Vitest test alongside the component

## Before Writing Code
1. Read 2-3 existing components in apps/web/components/ to match the pattern
2. Check if similar UI elements exist in components/ui/ (Badge, Button, Card, Input, etc.)
3. Use the hooks pattern from apps/web/hooks/ for data fetching

## Deliverables
1. Component in apps/web/components/settings/PreferencesPanel.tsx
2. Test in apps/web/__tests__/components/settings/PreferencesPanel.test.tsx
3. Integration into the settings page route
```

---

### Example: Bug Fix

```
## Task
Fix: diff panel doesn't show changes after AI draft in PSMF wizard

## Constraints
- This is a FIX, not a feature. Minimal changes only.
- Follow the patterns in .claude/rules/anti-slop.md
- Add a regression test that would have caught this bug

## Before Writing Code
1. Read the relevant component code to understand the current behavior
2. Identify the root cause before changing anything
3. Write the test FIRST (TDD) — the test should fail with the current code

## Deliverables
1. The minimal fix (as few changed lines as possible)
2. A regression test that fails without the fix and passes with it
3. Commit message: fix(psmf-wizard): [specific description]
```

---

## Multi-Agent Coordination

When multiple agents (or multiple Claude Code sessions) work on the same codebase:

### Rules
1. **Each agent works on a separate branch.** Never have two agents on the same branch.
2. **Use worktrees for isolation.** Claude Code supports `.claude/worktrees/` for this.
3. **Run the harness AFTER merging.** When branches merge, regenerate the harness to catch new patterns/utilities.
4. **Check for conflicts before merging.** Two agents might create similar utilities — the harness's utility detection catches this.

### Coordination Prompt (for the lead/orchestrator)

```
## Multi-Agent Task Distribution

I'm distributing this feature across 2-3 agent sessions. Before starting:

1. Each agent gets a separate branch (feature/task-1, feature/task-2)
2. Each agent reads .claude/rules/anti-slop.md FIRST
3. Each agent checks: does the utility/pattern I need already exist?
4. Shared utilities go in the FIRST agent's branch — other agents depend on it

## Merge Order
1. Merge shared utilities first (branch with new models/services)
2. Then merge dependent features (branches that use those models/services)
3. After merge: run `ctxpack codebase harness . --force-refresh` to update rules
4. Run full test suite: `npm run test` (root workspace)
```

---

## How the Harness Prevents Drift

| Problem | How the Harness Prevents It |
|---|---|
| Agent creates duplicate utility | `anti-slop.md` lists ALL existing utilities with paths |
| Agent forgets to write tests | `test-requirements.md` loads automatically in source directories |
| Agent uses wrong commit format | `commit-conventions.md` shows the format from git history |
| Agent ignores established patterns | Rules show actual patterns from sibling files |
| Agent produces sloppy code late in session | `quality-check.py` hook runs after every file write |
| Two agents create conflicting code | Separate branches + post-merge harness refresh |

---

## Measuring Harness Effectiveness

After 2 weeks of using the harness, check:

1. **Regression rate**: Are bugs being introduced by agent sessions? Compare before/after harness.
2. **Utility duplication**: Search the codebase for duplicate function names. Has it decreased?
3. **Test coverage**: Has the 40% floor ratchet moved up? Are agents writing tests consistently?
4. **Code review friction**: Are PRs requiring fewer revision cycles?
5. **Session quality**: Do later files in a session match the quality of earlier files?

If any metric hasn't improved, the harness rules need updating. Run `ctxpack codebase harness . --force-refresh` and check what patterns the tool detected vs what conventions the team actually follows.
