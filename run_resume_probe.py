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
                    choices=("recall", "drift", "drift-fork"),
                    help="recall: history questions; drift: conflicting "
                         "proposals graded on surfacing the prior; "
                         "drift-fork: planted unresolved-supersession "
                         "forks (pre-registered A3) — ignores --repo, "
                         "runs on a synthetic fixture ledger")
    ap.add_argument("--work-dir", default=None,
                    help="drift-fork only: fixture dir (default: temp)")
    args = ap.parse_args()

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


if __name__ == "__main__":
    sys.exit(main())
