# Session memory (session eca3f61c, 287 turns)

Deterministic ledger recovered from the session transcript. Full detail: `ctxpack hydrate` on the session .ctx, or grep the raw transcript.

## Decisions
- Decision: current-session lint comparisons gate on strictly-earlier constraint turns (integer turn carried per constraint; cross-session rows always apply), because the old same-turn-only skip let a decision be flagged against future text — a retroactive conflict the contract for (turn 281)
- Decision: the onboard conventions block is bumped to v4 with the turn-FINAL marker rule and the Supersedes: override convention, because the v3 template silently withheld both from cohort repos on refresh. (turn 281)
- Decision: the checkpoint journal carries lint_status/lint_error/lint_ledgers_skipped, because a swallowed lint exception journaled the same zeros as a clean run and the governance signal could die silently. (turn 281)
- Decision: the resume-probe ctx arm (v2) appends the source session's session-literals block, because the baseline arm under-modeled the documented read path — this is the fix pre-registered on 2026-07-05, not post-hoc tuning, and the result files self-describe via the new ctx_arm (turn 281)
- Decision: the two remaining KP_SDLC literal misses stand as graded; before the next probe run, pre-register a same-turn disambiguation rule (skip or hint probes where more than one same-kind literal shares the source turn), because "the exact path near turn N" is degenerate when  (turn 281)

## Exact identifiers (verbatim)
- d2ed148 [git_sha] (turn 281)
- tests/test_conflict_lint.py [path] (turn 281)
- 3b25fbf [git_sha] (turn 281)
- e393408 [git_sha] (turn 281)
- 619d5850a72200b7 [git_sha] (turn 281)

## Memory incidents (ctx telemetry)
- ctx-incident: saved | fact="rank/v1+lint ship state and next action after /clear" | expected="one-call resume restores working state" | got="ctxpack session resume returned all 13 decisions, commits f2e7dae/b29352f/db9f37a/2f27a0a, and the drift-re-run next step" | evidence="zero transcript greps needed this session" (turn 281)
- ctx-incident: native-better | fact="pre-registered ctx-arm fix wording (arm under-models session_literals/why read path)" | expected="ledger why/recall surfaces the registration text" | got="session why 'under-models' returned found=false (235 entities searched); wording recovered from auto-memory automem-drift-baseline-2026-07-05.md" | evidence="why output found:false; the registration existed on (turn 281)

## What was asked
- continue (turn 1)
- done? (turn 238)
- I’m mostly aligned (turn 282)

## Tasks
- Re-materialize CTX_mod + KP_SDLC ledgers under rank/v1 (turn 35)
- Run drift + recall probe re-runs (rank/v1 delta) (turn 37)
- Fix same-session temporal filtering in conflict_lint.py (turn 92)
- Update onboard CLAUDE.md template with turn-final + Supersedes conventions (turn 94)
- Journal lint_status so lint crashes are distinguishable from clean (turn 96)

## Errors seen
- Exit code 1 warning: in the working copy of 'ctxpack/benchmarks/agentic/resume_probe.py', LF will be replaced by CRLF the next time Git touches it warning: in the working copy of 'tests/test_resume_probe.py', LF will be replaced by CRLF the (turn 205)
- Exit code 1 repo=KP_SDLC set=recall probes=20 (decision, literal, rationale) arms=['ctx', 'grep', 'closed', 'automem'] [ 1/20] decision ???? ctx=4051bpe [ 2/20] literal ???? ctx=4020bpe [ 3/20] rationale ???? ctx=4060bpe [ 4/20] decision ?? (turn 221)
- Exit code 1 Traceback (most recent call last): File "<string>", line 1, in <module> import json,sys; d=json.load(sys.stdin); [print(r['turn'], r['kind'], r['value'][:70]) for r in d['literals'] if 480 <= r['turn'] <= 600] ~~~~~~~~~^^^^^^^^^ (turn 254)
- Exit code 1 Exception calling "Substring" with "2" argument(s): "Index and length must refer to a location within the string. Parameter name: length" At line:1 char:138 + ... tFrom-Json; ($j.results | Where-Object { $_.arm -eq 'ctx' }).answ (turn 261)
- <tool_use_error>File has not been read yet. Read it first before writing to it.</tool_use_error> (turn 273)

## Files changed
- C:\Users\kapil\Documents\CTX_mod\ctxpack\benchmarks\agentic\resume_probe.py (3 edits) (turn 80)
- C:\Users\kapil\Documents\CTX_mod\tests\test_resume_probe.py (3 edits) (turn 88)
- C:\Users\kapil\Documents\CTX_mod\ctxpack\cli\main.py (2 edits) (turn 146)
- C:\Users\kapil\Documents\CTX_mod\tests\test_onboard.py (2 edits) (turn 154)
- C:\Users\kapil\Documents\CTX_mod\ctxpack\agent\conflict_lint.py (10 edits) (turn 177)
- C:\Users\kapil\Documents\CTX_mod\ctxpack\agent\checkpoint.py (2 edits) (turn 182)
- C:\Users\kapil\Documents\CTX_mod\tests\test_conflict_lint.py (2 edits) (turn 190)
- C:\Users\kapil\AppData\Local\Temp\claude\C--Users-kapil-Documents-CTX-mod\eca3f61c-a652-42b3-b60b-d427b24bbc5c\scratchpad\commitmsg.txt (1 edits) (turn 208)
- C:\Users\kapil\.claude\projects\C--Users-kapil-Documents-CTX-mod\memory\rank-v1-conflict-lint-shipped.md (2 edits) (turn 270)
- C:\Users\kapil\.claude\projects\C--Users-kapil-Documents-CTX-mod\memory\MEMORY.md (2 edits) (turn 276)