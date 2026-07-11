"""CompactBench runner (Layer 3): decision retention across REAL
forced compaction cycles in headless Claude Code.

Per PREREGISTRATION.md: planted sessions (40 facts) are injected into
Claude Code's project store, resumed with the autocompact threshold
forced low, and probed after each of K compaction cycles across six
arms. Grading is deterministic (exact/contains rules); results are
written as NEW versioned files, never overwritten.

Usage:
  python run_compactbench.py --dry-run              # no API calls
  python run_compactbench.py --smoke                # seed 0, K=2, native+ctx
  python run_compactbench.py --seeds 0,1,2,3,4 --k 5 --arms all   # full
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    # line_buffering: cells take minutes; progress must be visible when
    # stdout is redirected (background runs)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace",
                           line_buffering=True)

from ctxpack.benchmarks.compactbench import driver, probes as probes_mod
from ctxpack.benchmarks.compactbench.drk import (mcnemar_b_c, recall_at_k,
                                                 wilson_ci)
from ctxpack.benchmarks.compactbench.planted_session_gen import (
    generate_planted_session)

BENCH_DIR = os.path.join("ctxpack", "benchmarks", "compactbench")
RESULTS_DIR = os.path.join(BENCH_DIR, "results")
MEMORY_CACHE = os.path.join(RESULTS_DIR, "memory-cache")

_GREP_EXTRA = (", and from the raw JSONL log of the pre-compaction "
               "session kept at session-log.jsonl in the working "
               "directory (use Grep/Read on it)")


def _stamp() -> str:
    return time.strftime("%Y%m%dT%H%M%S")


# ------------------------------------------------------------ llm-memory

def build_llm_memory(seed: int, entries: list[dict], model: str,
                     work_root: str, log) -> tuple[str, float]:
    """Mem0-style memory file, built once per (seed, model) by an LLM
    over the full pre-compaction transcript and cached under results/.
    Deliberately generous: real systems build incrementally.
    Returns (content, cost_usd) — cost 0 on cache hit."""
    os.makedirs(MEMORY_CACHE, exist_ok=True)
    cache = os.path.join(MEMORY_CACHE, f"seed-{seed:04d}-{model}.md")
    if os.path.exists(cache):
        log(f"  llm-memory: cache hit {cache}")
        with open(cache, encoding="utf-8") as f:
            return f.read(), 0.0
    prep = os.path.join(work_root, f"memprep-{seed:04d}")
    os.makedirs(prep, exist_ok=True)
    with open(os.path.join(prep, "session-log.jsonl"), "w",
              encoding="utf-8", newline="\n") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    res = driver.run_claude(
        prep,
        "Read session-log.jsonl (a JSONL transcript of a prior coding "
        "session). Write a concise memory file in markdown capturing: "
        "decisions made (with CURRENT values for anything revised), "
        "standing ground rules/constraints, exact identifiers such as "
        "commit hashes, and approaches that were tried and abandoned. "
        "Keep exact values verbatim. Output ONLY the memory file "
        "content.",
        model=model, allowed_tools="Read,Grep", max_turns=25,
        timeout=1200)
    if not res.ok or not res.result.strip():
        raise driver.DriverError(
            f"llm-memory build failed for seed {seed}: {res.stderr[:300]}")
    with open(cache, "w", encoding="utf-8", newline="\n") as f:
        f.write(res.result)
    log(f"  llm-memory: built ({len(res.result)} chars, "
        f"${res.cost_usd or 0:.3f}) -> {cache}")
    return res.result, res.cost_usd or 0.0


# ---------------------------------------------------------------- cells

def probe_cell(ctx: dict, k: int, recall: list, adherence: list, *,
               model: str, probe_mode: str, do_adherence: bool,
               log) -> list[dict]:
    """All probes for one (arm, seed) at cycle k. Returns raw rows."""
    arm, seed = ctx["arm"], ctx["seed"]
    rows: list[dict] = []
    grep_arm = arm == "grep"
    extra = _GREP_EXTRA if grep_arm else ""
    # A probe fork must observe the session, not checkpoint itself over
    # it — skip the packing hooks; session-start (gist injection) stays.
    probe_env = {"CTXPACK_HOOK_SKIP": "stop,session-end,pre-compact"}
    tools = dict(allowed_tools="Grep,Read,Glob", max_turns=60) if grep_arm \
        else dict(disallowed_tools=driver._NO_TOOLS, max_turns=2)

    def base(p, res, answer, parse_failure=False):
        g = probes_mod.grade_recall(p, answer) if p.kind != "adherence" \
            else None
        return {"seed": seed, "arm": arm, "k": k, "probe_id": p.probe_id,
                "kind": p.kind, "answer": (answer or "")[:400],
                "parse_failure": parse_failure,
                "usage": res.usage, "cost_usd": res.cost_usd,
                **(g or {})}

    if probe_mode == "batched":
        res = driver.run_claude(
            ctx["workspace"], probes_mod.format_batch(recall, extra),
            resume=ctx["sid"], fork=True, model=model, timeout=1800,
            extra_env=probe_env, **tools)
        answers = probes_mod.parse_batch(res.result, len(recall))
        for i, p in enumerate(recall, 1):
            row = base(p, res, answers.get(i, ""),
                       parse_failure=i not in answers)
            if i > 1:
                # one shared call: carry its cost/usage on the first row
                # only, or the report sums it 40x
                row["cost_usd"] = None
                row["usage"] = {}
            rows.append(row)
    else:
        for p in recall:
            res = driver.run_claude(
                ctx["workspace"], p.question + extra, resume=ctx["sid"],
                fork=True, model=model, timeout=900,
                extra_env=probe_env, **tools)
            rows.append(base(p, res, res.result))

    if do_adherence:
        for p in adherence:
            res = driver.run_claude(
                ctx["workspace"], p.question, resume=ctx["sid"], fork=True,
                model=model, max_turns=6, timeout=900,
                extra_env=probe_env,
                allowed_tools="Grep,Read,Glob" if grep_arm else None)
            fork_t = (driver.transcript_path(ctx["workspace"],
                                             res.session_id)
                      if res.session_id else "")
            cmds = driver.attempted_tool_commands(fork_t) if fork_t else []
            g = probes_mod.grade_adherence(p, cmds, res.result)
            rows.append({"seed": seed, "arm": arm, "k": k,
                         "probe_id": p.probe_id, "kind": "adherence",
                         "answer": res.result[:400],
                         "attempted_cmds": cmds[:10],
                         "usage": res.usage, "cost_usd": res.cost_usd,
                         **g})
    n_ok = sum(1 for r in rows if r.get("correct"))
    n_rec = sum(1 for r in rows if r["kind"] != "adherence")
    n_viol = sum(1 for r in rows if r.get("violation"))
    log(f"    k={k}: recall {n_ok}/{n_rec}"
        + (f", violations {n_viol}/{len(adherence)}" if do_adherence else ""))
    return rows


def run_cell(seed: int, arm: str, *, k_max: int, pct: float, model: str,
             work_root: str, probe_mode: str, do_adherence: bool,
             dry_run: bool, log) -> list[dict]:
    entries, manifest = generate_planted_session(seed)
    recall = probes_mod.build_recall_probes(manifest)
    adherence = probes_mod.build_adherence_probes(manifest)

    llm_memory, mem_cost = None, 0.0
    if arm == "llm-memory" and not dry_run:
        llm_memory, mem_cost = build_llm_memory(seed, entries, model,
                                                work_root, log)
    ctx = driver.setup_workspace(work_root, arm, seed, entries, manifest,
                                 llm_memory=llm_memory)
    if arm == "llm-memory":
        # delivered via CLAUDE.md — the only file Claude Code auto-loads;
        # same mechanism as the claudemd arm, different content provenance
        os.replace(os.path.join(ctx["workspace"], "MEMORY.md"),
                   os.path.join(ctx["workspace"], "CLAUDE.md"))

    log(f"  {arm}/s{seed:04d}: {len(entries)} entries, "
        f"{len(recall)}+{len(adherence)} probes"
        f"{' (dry-run: no API)' if dry_run else ''}")
    if dry_run:
        return [{"seed": seed, "arm": arm, "k": k, "probe_id": p.probe_id,
                 "kind": p.kind, "answer": "(dry-run)", "correct": False,
                 "dry_run": True}
                for k in range(1, k_max + 1) for p in recall]

    rows: list[dict] = []
    if mem_cost:
        rows.append({"seed": seed, "arm": arm, "kind": "memory_build",
                     "cost_usd": mem_cost})
    try:
        for k in range(1, k_max + 1):
            if arm == "oracle":
                # no compaction ever; append the same deterministic filler
                # so token position/interference matches the other arms
                target = int(driver.forced_threshold_tokens(pct) * 1.4)
                driver.append_jsonl(
                    ctx["transcript"], driver.inflation_entries(
                        seed, k, ctx["sid"], ctx["workspace"],
                        driver.last_uuid(ctx["transcript"]), target))
            else:
                cycles = driver.force_cycles(ctx, k, pct=pct, model=model,
                                             log=log)
                rows.extend({"seed": seed, "arm": arm, "kind": "cycle", **c}
                            for c in cycles)
            rows.extend(probe_cell(ctx, k, recall, adherence, model=model,
                                   probe_mode=probe_mode,
                                   do_adherence=do_adherence, log=log))
    except driver.DriverError as exc:
        # keep every row gathered before the failure — raw rows are
        # published for every run, partial cells included
        log(f"  CELL FAILED (rows up to failure kept): {exc}")
        rows.append({"seed": seed, "arm": arm, "kind": "cell_error",
                     "error": str(exc)[:500]})
    return rows


# --------------------------------------------------------------- report

def _sum_usage(acc: dict, usage: dict) -> None:
    """Aggregate top-level numeric usage fields (input/output/cache tokens)."""
    for key, val in (usage or {}).items():
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            acc[key] = acc.get(key, 0) + val


def build_report(rows: list[dict], params: dict) -> dict:
    arms_present = sorted({r["arm"] for r in rows if r.get("kind") != "cycle"})
    report: dict = {"benchmark": "compactbench-v1", "params": params,
                    "generated_at": _stamp(), "arms": {}}
    for arm in arms_present:
        arm_rows = [r for r in rows if r["arm"] == arm]
        decisions = {k: [] for k in range(1, params["k_max"] + 1)}
        per_seed: dict[int, dict[int, list]] = {}
        by_kind: dict[str, dict[int, list]] = {}
        cv: dict[int, list] = {}
        # explicit cost split: probe calls, compaction nudges (carried as
        # nudge_cost on cycle rows), llm-memory builds
        probe_cost = sum(r.get("cost_usd") or 0 for r in arm_rows
                         if r.get("kind") not in ("cycle", "cell_error",
                                                  "memory_build"))
        compaction_cost = sum(r.get("nudge_cost") or 0 for r in arm_rows
                              if r.get("kind") == "cycle")
        memory_cost = sum(r.get("cost_usd") or 0 for r in arm_rows
                          if r.get("kind") == "memory_build")
        # measured usage + per-seed cost (W1-5): budget projections must
        # come from measured cells, never from smoke extrapolation — the
        # "$1/cell -> $25 full run" estimate was off 2.4x ($60 actual)
        usage_breakdown: dict = {}
        for r in arm_rows:
            _sum_usage(usage_breakdown,
                       r.get("nudge_usage") if r.get("kind") == "cycle"
                       else r.get("usage"))
        seeds_completed = {r["seed"] for r in arm_rows
                           if r.get("kind") != "cell_error"
                           and "seed" in r}
        for r in arm_rows:
            if (r.get("kind") in ("cycle", "cell_error", "memory_build")
                    or "k" not in r or r.get("dry_run")):
                continue
            if r["kind"] == "adherence":
                cv.setdefault(r["k"], []).append(bool(r.get("violation")))
                continue
            by_kind.setdefault(r["kind"], {}).setdefault(
                r["k"], []).append(bool(r.get("correct")))
            if r["kind"].startswith("decision"):
                decisions[r["k"]].append(bool(r.get("correct")))
                per_seed.setdefault(r["seed"], {}).setdefault(
                    r["k"], []).append(bool(r.get("correct")))
        entry = {
            "drk": recall_at_k({k: v for k, v in decisions.items() if v}),
            # per-seed DR@K alongside pooled: pooled McNemar alone invites
            # a pseudoreplication critique
            "drk_by_seed": {str(s): recall_at_k(g)
                            for s, g in sorted(per_seed.items())},
            "by_kind": {kind: recall_at_k(g) for kind, g in by_kind.items()},
            "probe_cost_usd": round(probe_cost, 4),
            "compaction_cost_usd": round(compaction_cost, 4),
            "memory_build_cost_usd": round(memory_cost, 4),
            "total_cost_usd": round(
                probe_cost + compaction_cost + memory_cost, 4),
            "usage_breakdown": {k: usage_breakdown[k]
                                for k in sorted(usage_breakdown)},
            "n_seeds": len(seeds_completed),
            "cost_per_seed_usd": (round(
                (probe_cost + compaction_cost + memory_cost)
                / len(seeds_completed), 4) if seeds_completed else None),
        }
        if cv:
            entry["cvk"] = {
                k: {"n": len(v), "violations": sum(v),
                    "rate": round(sum(v) / len(v), 4),
                    "ci95": list(wilson_ci(sum(v), len(v)))}
                for k, v in sorted(cv.items())}
        lit = by_kind.get("literal", {})
        if lit:
            pw = {}
            for r in arm_rows:
                if r.get("kind") == "literal":
                    pw.setdefault(r["k"], []).append(
                        r.get("error_class") == "plausible_wrong")
            entry["lfk_plausible_wrong"] = {
                k: sum(v) for k, v in sorted(pw.items())}
        report["arms"][arm] = entry

    # pre-committed comparisons on paired probes (same seed, same probe)
    def paired(a: str, b: str, k: int):
        idx = {}
        for r in rows:
            if (r.get("kind", "").startswith("decision")
                    and not r.get("dry_run") and r.get("k") == k):
                idx.setdefault((r["seed"], r["probe_id"]), {})[r["arm"]] = \
                    bool(r.get("correct"))
        return [(v[a], v[b]) for v in idx.values() if a in v and b in v]

    report["comparisons"] = {}
    kmax = params["k_max"]
    for a, b in (("ctx", "native"), ("ctx", "grep")):
        if a in report["arms"] and b in report["arms"]:
            pairs = paired(a, b, kmax)
            if pairs:
                report["comparisons"][f"{a}_vs_{b}_dr@{kmax}"] = \
                    mcnemar_b_c(pairs)

    # run-level rollup (W1-5): the one number a budget decision reads,
    # plus measured per-seed cell costs for projecting a planned run
    run_usage: dict = {}
    for e in report["arms"].values():
        _sum_usage(run_usage, e.get("usage_breakdown"))
    report["run_cost_usd"] = round(
        sum(e["total_cost_usd"] for e in report["arms"].values()), 4)
    report["run_usage"] = {k: run_usage[k] for k in sorted(run_usage)}
    report["cost_model"] = {
        arm: {"cost_per_seed_usd": e["cost_per_seed_usd"],
              "n_seeds_measured": e["n_seeds"],
              "k_max": kmax}
        for arm, e in report["arms"].items()}
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="0,1,2,3,4")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--arms", default="all",
                    help=f"comma list or 'all' ({','.join(driver.ARMS)})")
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--pct", type=float, default=20.0,
                    help="forced autocompact threshold, % of pinned window "
                         "(20 = scored default; 8 = adversarial stress)")
    ap.add_argument("--probe-mode", choices=("batched", "single"),
                    default="batched")
    ap.add_argument("--no-adherence", action="store_true")
    ap.add_argument("--smoke", action="store_true",
                    help="seed 0, K=2, arms native,ctx")
    ap.add_argument("--sentinel", action="store_true",
                    help="2 seeds, K=3, native+ctx+grep — the cheap "
                         "null-hypothesis gate (sequential stopping)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--workers", type=int, default=1,
                    help="parallel (seed, arm) cells; each cell is its own "
                         "workspace+session, cycles within a cell stay "
                         "sequential")
    ap.add_argument("--no-isolate-config", action="store_true",
                    help="skip the run-scoped CLAUDE_CONFIG_DIR (benchmark "
                         "sessions then land in the real ~/.claude)")
    ap.add_argument("--work-dir", default=None,
                    help="workspace root (default: <bench>/work/<stamp>)")
    args = ap.parse_args()

    if args.smoke:
        seeds, k_max, arms = [0], 2, ["native", "ctx"]
    elif args.sentinel:
        seeds, k_max, arms = [0, 1], 3, ["native", "ctx", "grep"]
    else:
        seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
        k_max = args.k
        arms = (list(driver.ARMS) if args.arms == "all"
                else [a.strip() for a in args.arms.split(",") if a.strip()])
    for a in arms:
        if a not in driver.ARMS:
            print(f"unknown arm: {a}"); return 1

    stamp = _stamp()
    work_root = os.path.abspath(args.work_dir or
                                os.path.join(BENCH_DIR, "work", stamp))
    os.makedirs(work_root, exist_ok=True)
    isolate = not args.no_isolate_config
    if isolate:
        cfg = driver.prepare_config_dir(work_root)
        os.environ["CLAUDE_CONFIG_DIR"] = cfg
    params = {"seeds": seeds, "k_max": k_max, "arms": arms,
              "model": args.model, "pct": args.pct,
              "forced_window": driver.FORCED_WINDOW,
              "forced_threshold_tokens": driver.forced_threshold_tokens(
                  args.pct),
              "probe_mode": args.probe_mode,
              "adherence": not args.no_adherence,
              "workers": args.workers,
              "isolated_config": isolate,
              "claude_code_version": "2.1.201"}
    print(f"CompactBench: arms={arms} seeds={seeds} K={k_max} "
          f"model={args.model} pct={args.pct} workers={args.workers} "
          f"({'DRY RUN' if args.dry_run else 'LIVE'})")
    print(f"  work: {work_root}")
    if isolate:
        print(f"  config: {os.environ['CLAUDE_CONFIG_DIR']}")

    rows: list[dict] = []
    raw_path = os.path.join(RESULTS_DIR,
                            f"compactbench-{stamp}-raw.jsonl")
    os.makedirs(RESULTS_DIR, exist_ok=True)
    lock = threading.Lock()
    cells = [(seed, arm) for seed in seeds for arm in arms]

    def process(cell: tuple) -> None:
        seed, arm = cell
        buffered = args.workers > 1
        buf: list[str] = []
        log = buf.append if buffered else print
        if not buffered:
            print(f"[{arm}/s{seed:04d}]")
        try:
            cell_rows = run_cell(seed, arm, k_max=k_max, pct=args.pct,
                                 model=args.model, work_root=work_root,
                                 probe_mode=args.probe_mode,
                                 do_adherence=not args.no_adherence,
                                 dry_run=args.dry_run, log=log)
        except Exception as exc:  # noqa: BLE001 — one cell must not sink the run
            log(f"  CELL FAILED (setup): {exc}")
            cell_rows = [{"seed": seed, "arm": arm, "kind": "cell_error",
                          "error": str(exc)[:500]}]
        with lock:
            if buffered:
                print(f"[{arm}/s{seed:04d}]")
                for line in buf:
                    print(line)
            rows.extend(cell_rows)
            if not args.dry_run:
                with open(raw_path, "a", encoding="utf-8",
                          newline="\n") as f:
                    for r in cell_rows:
                        f.write(json.dumps(r) + "\n")

    if args.workers > 1:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            list(ex.map(process, cells))
    else:
        for c in cells:
            process(c)

    report = build_report(rows, params)
    tag = ("dryrun" if args.dry_run else
           "smoke" if args.smoke else
           "sentinel" if args.sentinel else "full")
    out = os.path.join(RESULTS_DIR, f"compactbench-{tag}-{stamp}.json")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, indent=2)
        f.write("\n")

    print()
    for arm, e in report["arms"].items():
        drk = {k: v["recall"] for k, v in e["drk"].items()}
        line = (f"  {arm:<11} DR@K={drk} "
                f"cost=${e['total_cost_usd']} "
                f"(probe {e['probe_cost_usd']} + compact "
                f"{e['compaction_cost_usd']})")
        if "cvk" in e:
            line += f" CV@K={ {k: v['rate'] for k, v in e['cvk'].items()} }"
        print(line)
    for name, c in report.get("comparisons", {}).items():
        print(f"  {name}: b={c['b']} c={c['c']} p={c['p_value']}")
    per_seed = {arm: m["cost_per_seed_usd"]
                for arm, m in report.get("cost_model", {}).items()}
    print(f"\n  RUN TOTAL: ${report.get('run_cost_usd', 0)} "
          f"(measured per-seed: {per_seed})")
    print(f"\nResults: {out}")
    if not args.dry_run:
        print(f"Raw rows: {raw_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
