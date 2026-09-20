<!--
Required sections: Summary, Assumptions, Non-goals, Verification, Self-review.
The CI `process` job runs scripts/check_pr_template.py and fails if one is
missing or left as a placeholder. Delete nothing; fill everything in.
-->

## Summary

Two to four bullets: what changed and why. Motivation and resulting behaviour,
not a restatement of the diff.

-

## Assumptions

What did this change take for granted that a reviewer should challenge? Be
honest about uncertain calls. If none, write "None".

-

## Non-goals

What this deliberately does not do. Useful when the change is one slice of a
longer sequence.

-

## Verification

How can a reviewer convince themselves this works? Paste the command and its
output — never claim a result from memory. "Committed" is not "done", and a
green suite is not evidence for a boundary no test covers.

- [ ] Test that fails without the change, demonstrated **red on the parent
      commit** (cite the path and the red count)
- [ ] Deterministic lane green: `python -m pytest tests/ -q -m "not slow"`
- [ ] Gates green: claims, capability registry, doc-privacy, protected-surface
- [ ] CI run linked

```
paste the actual command output here
```

## Self-review

- **Decisions / Constraints** stated in the turn-final message per `CLAUDE.md`,
  and any `Supersedes:` line recorded for a changed prior decision.
- **Reuse check:** searched `.claude/rules/anti-slop.md` before adding a helper.
- **Guards:** every boundary check added here ships a test that feeds a
  violation and requires rejection. If a test legitimately passes on the parent,
  its docstring says whether it is a regression pin or a forward guard.
- **Protected surface:** this PR does not edit the bar to pass. If it touches
  anything in `harness/structural-floor/protected-surface.txt`, say why.
- **Absent vs zero:** nothing unmeasured is reported as zero.

## Related

Closes #
