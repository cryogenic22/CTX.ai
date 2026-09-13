# Session memory (session a21df970, 288 turns)

Deterministic ledger recovered from the session transcript. Full detail: `ctxpack hydrate` on the session .ctx, or grep the raw transcript.

## Decisions
- Decision: rank `session_why` matches section_name → field_key → value_exact → value_substring, because an entity whose VALUE equals the needle is the literals-ledger recovery path and must beat any substring hit. (turn 270)
- Decision: resolve the live transcript by newest mtime under the munged `~/.claude/projects/<project>` dir with a name tie-break, because write-path input selection is outside the byte-determinism contract, which governs pack output only. (turn 270)
- Decision: keep the agent-constraint extractor marker-only (`Constraint:`/`Invariant:`, no verb heuristics), because over-extraction is the established failure mode and the dogfood convention already asks sessions to mark load-bearing statements. (turn 270)
- Decision: version the onboard CLAUDE.md block and refresh older blocks in place on re-onboard, because cohort repos otherwise keep stale conventions forever after upgrades. (turn 270)
- Decision: excluded the concurrent CompactBench worktree changes from commit 4b49f79 by staging CLAUDE.md at the blob level, because committing another session's in-progress files (or a doc line referencing not-yet-committed scripts) would misattribute unfinished work. (turn 287)

## Exact identifiers (verbatim)
- bae8e5d2 [git_sha] (turn 234)
- docs/agent-consumer-feedback-2026-07-04.md [path] (turn 270)
- cee22d9 [git_sha] (turn 270)
- 0308e87 [git_sha] (turn 270)
- #5 [pr] (turn 270)
- #6 [pr] (turn 270)
- #7 [pr] (turn 270)
- paper/vision-dream-intuition-agents.md [path] (turn 270)
- 4b49f79 [git_sha] (turn 287)
- tests/test_compactbench_driver.py [path] (turn 287)
- a21df970 [git_sha] (turn 287)

## What was asked
- get yourself acquainted with the repo and then i want you to play the role of fixing some of the issues other repos are facing in using ctx modules in their workflows etc. (turn 0)
- commit it (turn 271)

## Errors seen
- <tool_use_error>File has not been read yet. Read it first before writing to it.</tool_use_error> (turn 195)

## Files changed
- C:\Users\kapil\Documents\CTX_mod\ctxpack\agent\session_reader.py (5 edits) (turn 74)
- C:\Users\kapil\Documents\CTX_mod\ctxpack\agent\checkpoint.py (2 edits) (turn 80)
- C:\Users\kapil\Documents\CTX_mod\ctxpack\integrations\mcp_server.py (5 edits) (turn 94)
- C:\Users\kapil\Documents\CTX_mod\ctxpack\agent\transcript_parser.py (4 edits) (turn 118)
- C:\Users\kapil\Documents\CTX_mod\tests\test_session_reader.py (1 edits) (turn 143)
- C:\Users\kapil\Documents\CTX_mod\ctxpack\cli\main.py (8 edits) (turn 170)
- C:\Users\kapil\Documents\CTX_mod\README.md (4 edits) (turn 190)
- C:\Users\kapil\Documents\CTX_mod\CLAUDE.md (6 edits) (turn 210)
- C:\Users\kapil\Documents\CTX_mod\docs\session-memory-onboarding.md (4 edits) (turn 221)
- C:\Users\kapil\.claude\projects\C--Users-kapil-Documents-CTX-mod\memory\MEMORY.md (3 edits) (turn 285)