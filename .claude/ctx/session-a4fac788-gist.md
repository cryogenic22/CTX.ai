# Session memory (session a4fac788, 551 turns)

Deterministic ledger recovered from the session transcript. Full detail: `ctxpack hydrate` on the session .ctx, or grep the raw transcript.

## Decisions
- Decision: rank/v1-event-fold scores facts as kind-prior × basis × decision-marker × literal-kind multipliers, plus capped cross-session re-assertion (+0.2/session, cap +1.0), capped incident-linked deltas, a recency tie-break ≤0.01, and a CONSTRAINT floor of 2.5, because these ar (turn 354)
- Decision: extend fact_asserted detail with marker and literal_kind, because turn-74's junk is marker_stated by design (the parser accepts Verdict:/Conclusion:/Confirmed:) and the marker word is the only deterministic discriminator. (turn 354)
- Decision: eval exclusion compares each event row's transcript-derived cwd to the current transcript's cwd; rows predating the cwd stamp are kept, because a missing stamp is not evidence of eval traffic. (turn 354)
- Decision: the rank/v1 gist trim evicts the globally lowest-rank fact instead of lowest-stakes-section-first, because section-ordered eviction kept rank-1.2 junk decisions while dropping rank-1.8 identifiers on the real KP_SDLC gist. (turn 354)
- Decision: the inferred-basis penalty applies to DECISION facts only, because measured over-extraction is exclusively decision-verb junk, and penalizing FAILED-APPROACH evicted "do not retry" facts below number_unit table noise. (turn 354)
- Decision: within-session re-mention counting is deferred to rank/v2, because the parser banks entities first-wins and the ratified fixture labels don't require it. (turn 354)
- Decision: fix the events.jsonl contract by regenerating each session's block in place at checkpoint (true materialized view), because append-with-partial-dedup was reproducible only under the same checkpoint cadence — a weaker property than spec §5 claimed. (turn 536)
- Decision: conflict evidence is a shared contiguous 5-word content n-gram, not full-text containment, because the flagship drift case contains neither text in the other — the quoted phrase is the exact match precision-first demands. (turn 536)
- Decision: lint only canonical Decision:-marked facts, because verb-inferred junk and Verdict:/Conclusion: self-assessments would make the lint cry wolf. (turn 536)
- Decision: conflict comparisons run only against sessions earlier in journal order plus the current session's own earlier turns, so a session's events block stays stable no matter when it is re-materialized. (turn 536)
- Decision: the ratified same-key/different-value case ships as documented-reserved, because fact keys today are only literal kinds where same-key/different-value is normal — it lands with the first keyed producer (tool_observed knobs). (turn 536)
- Decision: malformed Supersedes payloads are ignored rather than fail-open, because the safe failure direction for governance is the conflict staying visible. (turn 536)
- Decision: marker-led Decision:/Constraint: sentences bank up to a 900-char cap, because the 300-char sentence filter was silently dropping long convention-following statements. (turn 536)

## Exact identifiers (verbatim)
- 619d5850a72200b7 [git_sha] (turn 15)
- #4 [pr] (turn 15)
- paper/vision-dream-intuition-agents.md [path] (turn 15)
- 2bafd4e [git_sha] (turn 354)
- cf2d182 [git_sha] (turn 354)
- f2e7dae [git_sha] (turn 354)
- ctxpack/core/rank.py [path] (turn 354)
- 2.1.199 [version] (turn 354)
- #1 [pr] (turn 395)
- db9f37a [git_sha] (turn 536)
- 7b38fd3 [git_sha] (turn 536)
- b29352f [git_sha] (turn 536)
- .claude/ctx/protected.json [path] (turn 536)
- C:\Users\kapil\.claude\projects\C--Users-kapil-Documents-CTX-mod\memory\rank-v1-conflict-lint-shipped.md [path] (turn 550)
- 2f27a0a [git_sha] (turn 550)

## Failed approaches (do not retry)
- **rank/v1 — the event-sourced salience fold**, using the KP_SDLC ca35891c session as the labeled fixture (load-bearing turns 813/858/1173 must rise; verb-inferred junk at turns 57/74 must sink; constraints floor), plus the CTX_mod session-id-extractor false positive as additional (turn 15)

## Memory incidents (ctx telemetry)
- ctx-incident: native-better | fact="ratified 07-05 sequence with KP_SDLC ca35891c fixture turns 813/858/1173" | expected="session resume surfaces the ratified plan as a Decision" | got="ledger decisions for bdfbd48b carried CompactBench/creation-critique lines but not the ratified rank/v1 sequence; full detail recovered from auto-memory MEMORY.md instead" | evidence="resume output decisions[] vs r (turn 15)
- ctx-incident: missed | fact="11 mid-turn Decision: lines stated in session a4fac788" | expected="transcript carries all assistant text; parser banks marker decisions" | got="CC 2.1.199 never wrote mid-turn text blocks to the JSONL; 0 DECISION entities extracted" | evidence="raw grep: 207 assistant entries, 17 text blocks, 0 with Decision:; bdfbd48b same CC version banked 10/10 turn-final" (turn 354)
- ctx-incident: missed | fact="Decision: rank/v1-event-fold scoring formula (restated turn-final per convention)" | expected="turn-final marker decisions always bank" | got="430-char sentence dropped by the 15..300 sentence filter; 5/6 banked" | evidence="fixed 7b38fd3, regression-tested; 6/6 bank after fix" (turn 536)

## What was asked
- resume (turn 1)
- commit the leftovers first, then start rank/v1 (turn 16)
- start on the conflict lint (turn 355)
- save to memory so we can clear and resume (turn 537)

## Tasks
- Read spec v1.1 reserved salience-fold section + events schema (turn 37)
- Build KP_SDLC ca35891c labeled fixture (turn 39)
- Design + implement rank/v1 salience fold (turn 41)
- Tests: fixture assertions + determinism + commit (turn 43)
- Parser: Supersedes: marker extraction + literal-mining strip (turn 436)
- conflict_lint.py: collision + protected-subject cases (turn 438)
- Wire lint into checkpoint: events, gist section, journal (turn 440)
- Lint tests + cohort silence check + conventions + commit (turn 442)

## Errors seen
- Exit code 1 as_of="2026-07-05") rows = [json.loads(l) for l in (tmp_path / "ctx" / "events.jsonl") .read_text(encoding="utf-8").splitlines()] asserted = [r for r in rows if r["event"] == "fact_asserted"] kinds = {r["detail"]["kind"] for r i (turn 178)
- Exit code 1 ____________ test_gist_literal_cap_keeps_highest_rank_identifiers _____________ tmp_path = WindowsPath('C:/Users/kapil/AppData/Local/Temp/pytest-of-kapil/pytest-978/test_gist_literal_cap_keeps_hi0') monkeypatch = <_pytest.monkey (turn 182)
- Exit code 1 File "<string>", line 5 return {type: etype, sessionId: rank1234-session, timestamp: 2026-07-05T09:00:00Z, ^ SyntaxError: leading zeros in decimal integer literals are not permitted; use an 0o prefix for octal integers (turn 186)
- <tool_use_error>File has not been read yet. Read it first before writing to it.</tool_use_error> (turn 319)
- Exit code 1 warning: in the working copy of 'ctxpack/agent/checkpoint.py', LF will be replaced by CRLF the next time Git touches it warning: in the working copy of 'ctxpack/agent/transcript_parser.py', LF will be replaced by CRLF the next t (turn 337)

## Files changed
- C:\Users\kapil\.claude\projects\C--Users-kapil-Documents-CTX-mod\memory\rank-v1-conflict-lint-shipped.md (1 edits) (turn 540)
- C:\Users\kapil\.claude\projects\C--Users-kapil-Documents-CTX-mod\memory\MEMORY.md (4 edits) (turn 544)