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
    ProbeResult,
    ctx_context,
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".", help="Repo with a .claude/ctx ledger")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--smoke", action="store_true", help="3 probes, live")
    ap.add_argument("--dry-run", action="store_true",
                    help="Generate probes + contexts, no API calls")
    ap.add_argument("--arms", default="ctx,grep,closed")
    ap.add_argument("--model", default="claude-sonnet-4-6")
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    ledger = os.path.join(repo, ".claude", "ctx")
    n = 3 if args.smoke else args.n
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]

    probes = generate_probes(ledger, n=n, seed=args.seed)
    if not probes:
        print(f"No probe candidates in {ledger} — needs checkpointed "
              f"sessions with decisions/constraints/literals.")
        return 1
    print(f"repo={os.path.basename(repo)}  probes={len(probes)} "
          f"({', '.join(sorted({p.kind for p in probes}))})  arms={arms}")

    model = args.model
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not args.dry_run and not api_key:
        print("ANTHROPIC_API_KEY missing (set it in .env) — use --dry-run "
              "to inspect probes without API calls.")
        return 1

    results: list[ProbeResult] = []
    for i, probe in enumerate(probes, 1):
        ctx = ctx_context(ledger, probe)
        budget = count_bpe_tokens(ctx, model="claude") if ctx else 0
        contexts = {
            "ctx": ctx,
            "grep": grep_context(repo, probe, budget or 2000),
            "closed": "",
        }
        for arm in arms:
            context = contexts.get(arm, "")
            bpe = count_bpe_tokens(context, model="claude") if context else 0
            if args.dry_run:
                results.append(ProbeResult(
                    probe_id=probe.probe_id, kind=probe.kind, arm=arm,
                    answer="(dry-run)", correct=False, context_bpe=bpe))
                continue
            answer = _ask_llm(
                _PREAMBLE + probe.question,
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

    report = to_report(repo, probes, results, seed=args.seed, model=model)
    if args.dry_run:
        for arm in report["arms"].values():
            arm["accuracy"] = None  # dry-run grades are meaningless
        print("\nDRY RUN — contexts built, no answers requested.")
    else:
        print()
        for name, arm in report["arms"].items():
            print(f"  {name:<7} accuracy={arm['accuracy']} "
                  f"ci95={arm['ci95']}  mean_ctx={arm['mean_context_bpe']}bpe")

    os.makedirs(RESULTS_DIR, exist_ok=True)
    stamp = report["generated_at"].replace(":", "").replace("-", "")
    tag = "dryrun" if args.dry_run else ("smoke" if args.smoke else "full")
    out = os.path.join(
        RESULTS_DIR,
        f"resume-probe-{report['repo']}-{tag}-{stamp}.json")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    print(f"\nResults: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
