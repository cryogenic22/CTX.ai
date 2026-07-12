"""Resume-probe eval runner (Layer 2): can a fresh session recover this
repo's own history?

Arms (interleaved per probe, budget parity): CTX (gists + hydrated
sections) / GREP (raw-transcript keyword windows, same budget) / CLOSED
(no context — contamination floor). Rule-based grading against the
ledger; results written as a NEW versioned file every run.

Usage:
  python run_resume_probe.py --repo <path> --dry-run   # no API calls
  python run_resume_probe.py --repo <path> --smoke     # 3 probes, live
  python run_resume_probe.py --repo <path> --n 20      # full run, live
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from ctxpack.benchmarks.dotenv import load_dotenv
load_dotenv()
# Answerer is Claude regardless of what .env sets for the doc evals —
# the provider is hardcoded to anthropic below (cross-model judging is
# not used here; grading is rule-based).

from ctxpack.benchmarks.agentic.resume_probe import (
    DRIFT_FORK_GRADE,
    ProbeResult,
    _norm,
    automem_context,
    ctx_context,
    drift_candidates,
    fork_unlock,
    generate_probes,
    grade,
    grep_context,
    to_report,
)
from ctxpack.benchmarks.metrics.cost import count_bpe_tokens
from ctxpack.benchmarks.metrics.fidelity import _ask_llm, _INTER_CALL_DELAY

RESULTS_DIR = os.path.join("ctxpack", "benchmarks", "agentic", "results")

_PREAMBLE = (
    "You are resuming work on a software project. Answer the question "
    "about the project's own history. If the context below contains the "
    "answer, use it; be precise with exact values.\n\n"
)

# Drift preamble is deliberately NEUTRAL: it must not hint that the
# proposal conflicts with anything — noticing is the behavior under test.
_DRIFT_PREAMBLE = (
    "You are resuming work on a software project; context about the "
    "project's history is below. A teammate sends you the following "
    "message. Reply as you would to the teammate.\n\n"
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".", help="Repo with a .claude/ctx ledger")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--smoke", action="store_true", help="3 probes, live")
    ap.add_argument("--dry-run", action="store_true",
                    help="Generate probes + contexts, no API calls")
    ap.add_argument("--arms", default=None,
                    help="comma list; default ctx,grep,closed — or "
                         "ctx-nowarn,ctx-warn,grep for drift-fork")
    ap.add_argument("--model", default="claude-sonnet-4-6")
    ap.add_argument("--probe-set", default="recall",
                    choices=("recall", "drift", "drift-fork",
                             "drift-fork-v2"),
                    help="recall: history questions; drift: conflicting "
                         "proposals graded on surfacing the prior; "
                         "drift-fork: planted unresolved-supersession "
                         "forks (pre-registered A3) — ignores --repo, "
                         "runs on a synthetic fixture ledger; "
                         "drift-fork-v2: independent clusters + "
                         "fixed-budget arms + negative controls "
                         "(pre-registered A5)")
    ap.add_argument("--work-dir", default=None,
                    help="drift-fork only: fixture dir (default: temp)")
    ap.add_argument("--clusters", type=int, default=None,
                    help="drift-fork-v2 only: cluster count override "
                         "(dry-run only; live runs require the pinned 8)")
    ap.add_argument("--authorized-run", action="store_true",
                    help="drift-fork-v2 only: assert BOTH pinned gates "
                         "are cleared — reviewer (Codex) approval of the "
                         "A5 text + harness, and the owner's explicit "
                         "<=$2 authorization. Live v2 runs refuse to "
                         "start without this flag.")
    args = ap.parse_args()

    if args.probe_set == "drift-fork-v2":
        return _run_fork_v2(args)

    repo = os.path.abspath(args.repo)
    ledger = os.path.join(repo, ".claude", "ctx")
    n = 3 if args.smoke else args.n
    default_arms = ("ctx-nowarn,ctx-warn,grep"
                    if args.probe_set == "drift-fork" else "ctx,grep,closed")
    arms = [a.strip() for a in (args.arms or default_arms).split(",")
            if a.strip()]

    gen_meta: dict = {}
    fixture = None
    warn_blk = ""
    nowarn_cache: dict = {}
    if args.probe_set == "drift-fork":
        import random
        import tempfile

        from ctxpack.benchmarks.agentic.fork_fixture import (
            DRIFT_FORK_VERSION,
            FORK_SOURCE,
            build_fork_fixture,
            fork_candidates,
            fork_grep_context,
            fork_warn_block,
        )
        work = args.work_dir or tempfile.mkdtemp(prefix="ctx-drift-fork-")
        fixture = build_fork_fixture(work)
        ledger = fixture.ledger_dir
        warn_blk = fork_warn_block(fixture.ledger_dir)
        cands = fork_candidates(fixture)
        random.Random(args.seed).shuffle(cands)
        probes = cands[:n]
        print(f"  fixture: {len(fixture.forks)} forks planted through the "
              f"real producer at {fixture.root} (fork_source={FORK_SOURCE})")
        # Honesty gate: the nowarn arm measures NOTICING an unflagged
        # fork, which is only meaningful if the other head's value is
        # PRESENT in its context. Absent v2 = a structurally blind arm
        # that would inflate the miss rate toward building the feature.
        missing = []
        for p in probes:
            nowarn_cache[p.probe_id] = ctx_context(ledger, p)
            if _norm(p.expected) not in _norm(nowarn_cache[p.probe_id]):
                missing.append(p.probe_id)
        if missing:
            print("fixture presence check FAILED — the other head's value "
                  "is absent from the ctx-nowarn context for: "
                  + ", ".join(missing)
                  + ". The arm would measure absence, not noticing; "
                  "aborting.")
            return 1
    elif args.probe_set == "drift":
        probes = generate_probes(ledger, n=n, seed=args.seed,
                                 candidates=drift_candidates, meta=gen_meta)
    else:
        probes = generate_probes(ledger, n=n, seed=args.seed, meta=gen_meta)
    if not probes:
        print(f"No {args.probe_set} probe candidates in {ledger} — needs "
              f"checkpointed sessions with decisions/constraints/literals.")
        return 1
    print(f"repo={os.path.basename(repo)}  set={args.probe_set}  "
          f"probes={len(probes)} "
          f"({', '.join(sorted({p.kind for p in probes}))})  arms={arms}")
    if gen_meta.get("ambiguous_literals_skipped"):
        print(f"  note: {gen_meta['ambiguous_literals_skipped']} ambiguous "
              f"same-turn literal candidates skipped (pre-registered A2, "
              f"PREREGISTRATION-resume-probe.md)")

    # AUTOMEM arm: probe-independent by nature — computed once. Empty
    # means the repo has no curated auto-memory; the arm then equals
    # CLOSED, which is itself informative (nothing was curated).
    automem = automem_context(repo) if "automem" in arms else ""
    if "automem" in arms and not automem:
        print("  note: no auto-memory dir found — automem arm runs "
              "context-free (equals closed)")

    model = args.model
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not args.dry_run and not api_key:
        print("ANTHROPIC_API_KEY missing (set it in .env) — use --dry-run "
              "to inspect probes without API calls.")
        return 1

    results: list[ProbeResult] = []
    for i, probe in enumerate(probes, 1):
        if fixture is not None:
            nowarn = nowarn_cache[probe.probe_id]
            warn = nowarn + "\n\n" + warn_blk
            # grep budget = max of the two ctx arms — over-powers the
            # null arm, the conservative direction (standing grep rule)
            budget = max(count_bpe_tokens(nowarn, model="claude"),
                         count_bpe_tokens(warn, model="claude"))
            contexts = {
                "ctx-nowarn": nowarn,
                "ctx-warn": warn,
                "grep": fork_grep_context(fixture, probe, budget),
            }
        else:
            ctx = ctx_context(ledger, probe)
            budget = count_bpe_tokens(ctx, model="claude") if ctx else 0
            contexts = {
                "ctx": ctx,
                "grep": grep_context(repo, probe, budget or 2000),
                "closed": "",
                "automem": automem,
            }
        preamble = (_DRIFT_PREAMBLE if probe.kind.startswith("drift")
                    else _PREAMBLE)
        for arm in arms:
            context = contexts.get(arm, "")
            bpe = count_bpe_tokens(context, model="claude") if context else 0
            if args.dry_run:
                results.append(ProbeResult(
                    probe_id=probe.probe_id, kind=probe.kind, arm=arm,
                    answer="(dry-run)", correct=False, context_bpe=bpe))
                continue
            answer = _ask_llm(
                preamble + probe.question,
                context or "(no context provided)",
                model=model, api_key=api_key, provider="anthropic")
            results.append(ProbeResult(
                probe_id=probe.probe_id, kind=probe.kind, arm=arm,
                answer=answer[:500], correct=grade(probe, answer),
                context_bpe=bpe, error=answer.startswith("(error:")))
            time.sleep(_INTER_CALL_DELAY)
        marks = "".join(
            ("?" if args.dry_run else ("Y" if r.correct else "n"))
            for r in results[-len(arms):])
        print(f"  [{i:>2}/{len(probes)}] {probe.kind:<11} {marks}  "
              f"ctx={budget}bpe")

    report = to_report(repo, probes, results, seed=args.seed, model=model,
                       probe_set=args.probe_set, gen_meta=gen_meta)
    if fixture is not None:
        report["repo"] = "fork-fixture"
        report["config"].update({
            "fork_source": FORK_SOURCE,
            "prereg": (f"{DRIFT_FORK_VERSION} — amendment A3, "
                       f"PREREGISTRATION-resume-probe.md"),
            "fork_grade": DRIFT_FORK_GRADE,
            "fork_grading": (
                "pass = an explicit conflict token (conflict/"
                "unreconciled/unresolved/fork/diverg/competing/"
                "contradict) PLUS an exact anchor never shown in the "
                "proposal: the OTHER head's value verbatim, or both "
                "head session ids (pre-registered A4 — the A3 "
                "v2-containment disjunct false-passed linear-recency "
                "dismissals on the first smoke). Paraphrased flags "
                "grade as misses. grep budget = max(ctx-nowarn, "
                "ctx-warn) BPE per probe (over-powers the null arm — "
                "conservative)."),
        })
        report["fork_unlock"] = (None if args.dry_run
                                 else fork_unlock(results))
    if args.dry_run:
        for arm in report["arms"].values():
            arm["accuracy"] = None  # dry-run grades are meaningless
        print("\nDRY RUN — contexts built, no answers requested.")
    else:
        print()
        for name, arm in report["arms"].items():
            print(f"  {name:<7} accuracy={arm['accuracy']} "
                  f"ci95={arm['ci95']}  mean_ctx={arm['mean_context_bpe']}bpe")
        if report.get("fork_unlock"):
            fu = report["fork_unlock"]
            print(f"  fork_unlock: nowarn_miss={fu['nowarn_miss_rate']} "
                  f"warn_miss={fu['warn_miss_rate']} "
                  f"b={fu['mcnemar_b_warn_fixed']} "
                  f"c={fu['mcnemar_c_warn_broke']} "
                  f"p={fu['mcnemar_p_one_sided']} unlock={fu['unlock']}")

    os.makedirs(RESULTS_DIR, exist_ok=True)
    stamp = report["generated_at"].replace(":", "").replace("-", "")
    tag = "dryrun" if args.dry_run else ("smoke" if args.smoke else "full")
    out = os.path.join(
        RESULTS_DIR,
        f"resume-probe-{report['repo']}-{args.probe_set}-{tag}-{stamp}.json")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    print(f"\nResults: {out}")
    return 0


_RETRY_POLICY = ("retry-level enforcement (harness notes v3): every "
                 "attempt — initial or retry — is ceiling-guarded "
                 "BEFORE issue and ledgered immediately before "
                 "('issued') and after ('result') the call "
                 "(fork_cluster.call_with_budget; max 5 retries, "
                 "exponential 2s..32s). Transient HTTP rejections "
                 "ledger at $0 (no usage block — not billed); "
                 "unknown-usage outcomes (timeout, reset) reserve the "
                 "pinned worst case. A call that still fails "
                 "INVALIDATES the scored run — abort, no cluster "
                 "analysis, no unlock (v2 blocker 4 unchanged)")


def _harness_commit() -> str:
    import subprocess
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:  # noqa: BLE001
        return ""


def _run_fork_v2(args) -> int:
    """drift-fork/v2 (pre-registered A5 + harness notes v2):
    deterministic full enumeration over the pinned 8 independent
    clusters; every inferential statistic at cluster level. Live runs
    are interlocked on --authorized-run, the pinned model, and the $2
    ceiling (preflight worst-case + running guard + durable invocation
    ledger). Any API failure or ceiling breach aborts the scored run."""
    import tempfile

    from ctxpack.benchmarks.agentic import fork_cluster as fc
    from ctxpack.benchmarks.metrics.fidelity import anthropic_attempt

    try:
        tokenizer = fc.require_exact_tokenizer()   # blocker 6
        # exact-manifest gate (harness notes v3): dry AND live runs
        # refuse inputs that drifted from the reviewed pinned sha
        manifest_sha = fc.require_pinned_manifest()
    except RuntimeError as exc:
        print(f"ABORT: {exc}")
        return 1
    n_clusters = args.clusters or fc.N_CLUSTERS_PINNED
    model = args.model
    harness_commit = _harness_commit()
    if not args.dry_run:
        if n_clusters != fc.N_CLUSTERS_PINNED:
            print(f"live drift-fork-v2 runs require the pinned "
                  f"{fc.N_CLUSTERS_PINNED} clusters (got {n_clusters}); "
                  f"--clusters is dry-run only.")
            return 1
        if model != fc.FORK_V2_MODEL:
            print(f"live drift-fork-v2 runs pin the model to "
                  f"{fc.FORK_V2_MODEL} (got {model}); the $2 ceiling is "
                  f"priced against the pinned model only.")
            return 1
        if not args.authorized_run:
            print("drift-fork-v2 live runs are gated (A5 + Q3 ruling "
                  "2026-07-11): (1) reviewer (Codex) approval of the A5 "
                  "text AND this harness, then (2) the owner's explicit "
                  "<=$2 authorization. Re-run with --authorized-run "
                  "once BOTH gates are cleared, or use --dry-run.")
            return 1
        if not os.environ.get("ANTHROPIC_API_KEY", ""):
            print("ANTHROPIC_API_KEY missing (set it in .env) — use "
                  "--dry-run to inspect the plan without API calls.")
            return 1
        if not harness_commit:
            print("cannot resolve the harness commit (git rev-parse "
                  "HEAD failed) — scored artifacts must stamp it.")
            return 1

    work = args.work_dir or tempfile.mkdtemp(prefix="ctx-drift-forkv2-")
    print(f"building {n_clusters} independent clusters through the real "
          f"producer at {work} (fork_source={fc.FORK_SOURCE}) ...")
    try:
        clusters = fc.build_clusters(work, n_clusters)
        plan = fc.build_plan(clusters)
    except RuntimeError as exc:
        # any failed receipt / absent product warning / pad-parity
        # failure aborts pre-flight (blockers 1 + 7); never partial
        print(f"ABORT (A5 harness notes v2): {exc}")
        return 1
    print(f"clusters={len(clusters)}  completions={len(plan)}  "
          f"(all receipts passed — any failure would have aborted)")

    # ── $2 ceiling enforcement (blocker 5 + notes v4 finding 3): the
    # bound prices the ENTIRE request (wrapper + system prompt) with
    # tokenizer headroom, and the SAME bound backs preflight and every
    # per-attempt guard ──
    def _worst_case(row) -> float:
        preamble = (_DRIFT_PREAMBLE
                    if row.ptype in ("fork", "false-alarm")
                    else _PREAMBLE)
        return fc.request_worst_case_usd(
            preamble + row.probe.question, row.context)

    def _price_usage(usage: dict) -> "float | None":
        it = usage.get("input_tokens")
        ot = usage.get("output_tokens")
        return (None if it is None or ot is None else round(
            (it * fc.PRICE_IN_PER_MTOK
             + ot * fc.PRICE_OUT_PER_MTOK) / 1_000_000, 6))

    worst_total = round(sum(_worst_case(r) for r in plan), 4)
    print(f"preflight worst-case cost: ${worst_total} "
          f"(ceiling ${fc.CEILING_USD}, model pinned {fc.FORK_V2_MODEL})")
    if not args.dry_run and worst_total > fc.CEILING_USD:
        print("ABORT: preflight worst-case exceeds the ceiling.")
        return 1

    from dataclasses import asdict

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    inv_path = os.path.join(work, "invocations.jsonl")

    def _record_invocation(rec: dict) -> None:
        # durable means durable (notes v4): flushed AND fsynced before
        # the write is claimed
        with open(inv_path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(rec) + "\n")
            f.flush()
            os.fsync(f.fileno())

    results: "list[dict]" = []
    invocations: "list[dict]" = []
    probes_seen: "dict[str, dict]" = {}
    spent = 0.0
    aborted: "dict | None" = None
    for i, row in enumerate(plan, 1):
        probes_seen.setdefault(row.probe.probe_id, asdict(row.probe))
        rec = {"probe_id": row.probe.probe_id, "cluster": row.cluster,
               "ptype": row.ptype, "arm": row.arm,
               "context_bpe": row.context_bpe,
               "context_sha256": row.context_sha256,
               "receipts": row.receipts,
               "pad_delta": row.pad_delta,
               "filler_sha256": row.filler_sha256,
               "filler_len": row.filler_len,
               "answer": None, "correct": None, "flagged": None}
        if not args.dry_run:
            preamble = (_DRIFT_PREAMBLE
                        if row.ptype in ("fork", "false-alarm")
                        else _PREAMBLE)
            wc = _worst_case(row)

            def _attempt(row=row, preamble=preamble):
                return anthropic_attempt(
                    preamble + row.probe.question,
                    row.context or "(no context provided)",
                    model=model, api_key=api_key,
                    max_tokens=fc.MAX_COMPLETION_TOKENS)

            def _ledger(payload, row=row, i=i):
                # every attempt is ledgered durably, before AND after
                # the call (retry-level enforcement, harness notes v3)
                inv = {"i": i, "probe_id": row.probe.probe_id,
                       "arm": row.arm, "model": model,
                       "context_sha256": row.context_sha256}
                inv.update(payload)
                _record_invocation(inv)
                invocations.append(inv)

            answer, spent, outcome = fc.call_with_budget(
                _attempt, worst_case_usd=wc, spent_usd=spent,
                ceiling_usd=fc.CEILING_USD, record=_ledger,
                price_usage=_price_usage)
            if outcome == "ceiling":
                aborted = {"reason": "ceiling", "at": i,
                           "probe_id": row.probe.probe_id,
                           "arm": row.arm, "level": "attempt",
                           "spent_usd": round(spent, 4)}
                print(f"ABORT before call {i}: the next attempt's "
                      f"worst case would exceed the ${fc.CEILING_USD} "
                      f"ceiling (spent ${spent:.4f}).")
                break
            if outcome == "empty-response":
                # an empty HTTP-200 completion is not a valid
                # measurement — grading it would bank a false miss
                aborted = {"reason": "empty-response", "at": i,
                           "probe_id": row.probe.probe_id,
                           "arm": row.arm,
                           "retry_policy": _RETRY_POLICY}
                rec.update(answer="", error=True)
                results.append(rec)
                print(f"ABORT at call {i}: the completion came back "
                      f"empty — an empty response invalidates the "
                      f"scored run (harness notes v3).")
                break
            if outcome == "api-error":
                # blocker 4: an error row must never be graded as a
                # miss — the scored run is invalid, full stop
                aborted = {"reason": "api-error", "at": i,
                           "probe_id": row.probe.probe_id,
                           "arm": row.arm,
                           "error": (answer or "")[:200],
                           "retry_policy": _RETRY_POLICY}
                rec.update(answer=(answer or "")[:500], error=True)
                results.append(rec)
                print(f"ABORT at call {i}: {(answer or '')[:120]} — a "
                      f"failed call invalidates the scored run "
                      f"(preregistered retry policy exhausted).")
                break
            correct, flagged = fc.grade_row(row, answer)
            rec.update(answer=answer[:500], correct=correct,
                       flagged=flagged, error=False)
            time.sleep(_INTER_CALL_DELAY)
        results.append(rec)
        if not args.dry_run:
            mark = "Y" if rec["correct"] else "n"
            print(f"  [{i:>3}/{len(plan)}] {row.cluster} "
                  f"{row.ptype:<12} {row.arm:<17} {mark}  "
                  f"ctx={row.context_bpe}bpe  spent=${spent:.4f}")

    analysis = None
    if not (args.dry_run or aborted):
        try:
            # result-set manifest gate (harness notes v4): the graded
            # rows must be EXACTLY the enumerated plan — deletion,
            # duplication, or unexpected rows invalidate the run
            fc.validate_result_manifest(
                results,
                expected_keys=[(r.cluster, r.ptype, r.probe.probe_id,
                                r.arm) for r in plan])
            analysis = fc.cluster_analysis(results)
        except RuntimeError as exc:
            aborted = {"reason": "result-manifest",
                       "error": str(exc)[:400]}
            print(f"ABORT: {exc}")
    import datetime
    report = {
        "schema": "ctxpack-drift-fork-v2/v2",
        "measurement_class": (
            "quasi-experimental — planted-fork surfacing under "
            "fixed-budget arms on synthetic cluster fixtures; the claim "
            "under test is scoped to SURFACING (A5); behavior-grade "
            "claims belong to CompactBench"),
        "generated_at": datetime.datetime.now(
            datetime.timezone.utc).isoformat(timespec="seconds"),
        "repo": "fork-fixture-v2",
        "config": {
            "model": model, "model_pinned": fc.FORK_V2_MODEL,
            "n_clusters": n_clusters,
            "sampling": "none — deterministic full enumeration of the "
                        "pinned cluster table",
            "fork_source": fc.FORK_SOURCE,
            "prereg": (f"{fc.DRIFT_FORK_V2_VERSION} — amendment A5 + "
                       f"harness notes v2, "
                       f"PREREGISTRATION-resume-probe.md"),
            "fork_grade": DRIFT_FORK_GRADE,
            "arms": {"fork": list(fc.FORK_ARMS),
                     "displacement": list(fc.DISPLACEMENT_ARMS),
                     "false-alarm": [fc.FALSE_ALARM_ARM]},
            "arm_counterbalancing": "fork/displacement arm call order "
                                    "rotates by cluster index "
                                    "(fork_cluster.arm_order)",
            "tokenizer": tokenizer,
            "harness_commit": harness_commit or "unknown (dry-run only)",
            "cluster_manifest_sha256": manifest_sha,
            "cluster_manifest_gate": "verified against "
                                     "PINNED_CLUSTER_MANIFEST_SHA256",
            "pad_filler_sha256": fc.pad_filler_sha256(),
            "ceiling_usd": fc.CEILING_USD,
            "prices_per_mtok": {"input": fc.PRICE_IN_PER_MTOK,
                                "output": fc.PRICE_OUT_PER_MTOK},
            "preflight_worst_case_usd": worst_total,
            "retry_policy": _RETRY_POLICY,
            "authorized_run": bool(args.authorized_run),
        },
        "spent_usd": round(spent, 4),
        "invocation_ledger": inv_path,
        "invocations": invocations,
        "aborted": aborted,
        "cluster_analysis": analysis,
        "probes": list(probes_seen.values()),
        "results": results,
    }
    if analysis:
        pr = analysis["primary"]
        print(f"\n  padded-nowarn cluster-mean miss="
              f"{pr['cluster_mean_miss_padded_nowarn']}  warn="
              f"{pr['cluster_mean_miss_warn']}  sign-test "
              f"p={pr['sign_test']['p_one_sided']}")
        print(f"  false-alarm 0/8 passed="
              f"{analysis['false_alarm_gate']['passed']}  "
              f"displacement gate passed="
              f"{analysis['displacement_gate']['passed']}  "
              f"unlock={analysis['unlock']}")
    elif args.dry_run:
        print("\nDRY RUN — clusters built, contexts + receipts computed, "
              "no answers requested.")

    os.makedirs(RESULTS_DIR, exist_ok=True)
    stamp = report["generated_at"].replace(":", "").replace("-", "")
    tag = ("dryrun" if args.dry_run
           else ("aborted" if aborted
                 else ("smoke" if args.smoke else "full")))
    out = os.path.join(
        RESULTS_DIR,
        f"resume-probe-fork-fixture-v2-drift-fork-v2-{tag}-{stamp}.json")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    print(f"\nResults: {out}")
    return 1 if aborted else 0


if __name__ == "__main__":
    sys.exit(main())
