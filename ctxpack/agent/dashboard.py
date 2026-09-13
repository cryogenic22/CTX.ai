"""Static HTML dashboard rendered from a scorecard dict.

Self-contained (inline CSS, no JS, no external requests) so it can be
opened from disk, committed, or published as-is. Values are direct-labeled
— the bars are magnitude aids, never the only carrier of a number — and
the measurement-class disclaimer is part of the page, not a footnote.
"""

from __future__ import annotations

from html import escape
from typing import Any

# Reference palette (dataviz method): swap values here to re-brand.
_CSS = """
:root {
  --surface-1: #fcfcfb; --page: #f9f9f7;
  --ink-1: #0b0b0b; --ink-2: #52514e; --ink-3: #898781;
  --grid: #e1e0d9; --ring: rgba(11,11,11,0.10);
  --series-1: #2a78d6; --seq-150: #b7d3f6;
  --good: #0ca30c; --warning: #fab219; --critical: #d03b3b;
}
@media (prefers-color-scheme: dark) {
  :root {
    --surface-1: #1a1a19; --page: #0d0d0d;
    --ink-1: #ffffff; --ink-2: #c3c2b7; --ink-3: #898781;
    --grid: #2c2c2a; --ring: rgba(255,255,255,0.10);
    --series-1: #3987e5; --seq-150: #184f95;
  }
}
* { box-sizing: border-box; margin: 0; }
body { background: var(--page); color: var(--ink-1);
  font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif;
  padding: 24px; }
.wrap { max-width: 1080px; margin: 0 auto; }
h1 { font-size: 20px; font-weight: 650; }
.sub { color: var(--ink-2); margin: 4px 0 16px; }
.note { background: var(--surface-1); border: 1px solid var(--ring);
  border-left: 3px solid var(--warning); border-radius: 6px;
  padding: 10px 14px; color: var(--ink-2); margin-bottom: 20px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px; margin-bottom: 24px; }
.tile { background: var(--surface-1); border: 1px solid var(--ring);
  border-radius: 8px; padding: 14px 16px; }
.tile .k { color: var(--ink-3); font-size: 12px; letter-spacing: .02em; }
.tile .v { font-size: 26px; font-weight: 650; margin-top: 2px; }
.tile .d { color: var(--ink-2); font-size: 12px; margin-top: 2px; }
.card { background: var(--surface-1); border: 1px solid var(--ring);
  border-radius: 8px; padding: 16px; overflow-x: auto; }
table { border-collapse: collapse; width: 100%; }
th { text-align: left; color: var(--ink-3); font-size: 12px;
  font-weight: 600; padding: 6px 10px; border-bottom: 1px solid var(--grid); }
td { padding: 8px 10px; border-bottom: 1px solid var(--grid);
  font-variant-numeric: tabular-nums; vertical-align: middle; }
tr:hover td { background: rgba(42,120,214,0.06); }
.repo { font-weight: 600; }
.chip { display: inline-block; font-size: 11px; padding: 1px 8px;
  border-radius: 999px; border: 1px solid var(--ring); color: var(--ink-2); }
.chip.active { border-color: var(--good); color: var(--good); }
.bar { display: flex; align-items: center; gap: 8px; min-width: 140px; }
.bar .track { flex: 1; height: 10px; background: none; position: relative; }
.bar .fill { position: absolute; inset: 0 auto 0 0; background: var(--series-1);
  border-radius: 0 4px 4px 0; min-width: 2px; }
.bar .num { color: var(--ink-2); font-size: 12px; min-width: 34px; }
.rate { font-weight: 600; }
.rate.good { color: var(--good); } .rate.warning { color: var(--warning); }
.rate.critical { color: var(--critical); }
.rate .lbl { font-weight: 400; color: var(--ink-3); font-size: 11px; }
footer { color: var(--ink-3); font-size: 12px; margin-top: 16px; }
"""


def _fallback_cell(read_path: dict[str, Any]) -> str:
    reads = read_path.get("ledger_reads", 0)
    greps = read_path.get("transcript_greps", 0)
    rate = read_path.get("raw_fallback_rate")
    if rate is None:
        return '<span class="rate"><span class="lbl">no reads yet</span></span>'
    cls = "good" if rate <= 0.2 else ("warning" if rate <= 0.5 else "critical")
    return (f'<span class="rate {cls}">{rate:.0%} '
            f'<span class="lbl">({greps}/{reads + greps} fell back)</span></span>')


def _recall_headline(read_path: dict[str, Any]) -> str:
    """"3 / 11" — sessions that explicitly queried the ledger over
    sessions where we can tell. Sessions with no telemetry are excluded
    from the denominator rather than counted as zero: an unmeasured
    session is not evidence of non-use."""
    explicit = read_path.get("sessions_explicit_recall")
    zero = read_path.get("sessions_zero_recall")
    if explicit is None or zero is None or (explicit + zero) == 0:
        return "–"
    return (f"{explicit}<span style='font-size:14px;color:var(--ink-3)'>"
            f" / {explicit + zero}</span>")


def _bar(value: int, max_value: int) -> str:
    pct = 0 if max_value <= 0 else round(100 * value / max_value)
    return (f'<span class="bar"><span class="track">'
            f'<span class="fill" style="width:{max(pct, 2 if value else 0)}%">'
            f'</span></span><span class="num">{value}</span></span>')


def render_dashboard(scorecard: dict[str, Any]) -> str:
    cohort = scorecard.get("cohort", {})
    repos = scorecard.get("repos", [])
    captured = cohort.get("captured", {})
    rate = cohort.get("read_path", {}).get("raw_fallback_rate")

    tiles = [
        ("Repos active", f"{cohort.get('repos_active', 0)}"
                         f"<span style='font-size:14px;color:var(--ink-3)'>"
                         f" / {cohort.get('repos_total', 0)}</span>",
         "checkpointing at least once"),
        ("Sessions banked", str(cohort.get("sessions", 0)),
         f"{cohort.get('turns_packed', 0):,} turns packed"),
        ("Decisions", str(captured.get("decisions", 0)),
         f"+ {captured.get('constraints', 0)} constraints, "
         f"{captured.get('failed_approaches', 0)} dead ends"),
        ("Sessions querying ledger", _recall_headline(
            cohort.get("read_path", {})),
         "queried vs never queried — "
         + ("raw-fallback n/a" if rate is None
            else f"raw-fallback {rate:.0%}")),
    ]
    tile_html = "".join(
        f'<div class="tile"><div class="k">{escape(k)}</div>'
        f'<div class="v">{v}</div><div class="d">{escape(d)}</div></div>'
        for k, v, d in tiles)

    max_dec = max((r.get("captured", {}).get("decisions", 0)
                   for r in repos if r.get("status") == "active"), default=0)
    rows = []
    for r in repos:
        name = escape(str(r.get("repo", "?")))
        status = r.get("status", "?")
        chip = (f'<span class="chip active">active</span>'
                if status == "active" else
                f'<span class="chip">{escape(status.replace("_", " "))}</span>')
        if status != "active":
            rows.append(f'<tr><td class="repo">{name}</td><td>{chip}</td>'
                        f'<td colspan="6" style="color:var(--ink-3)">no '
                        f'checkpoints yet — restart Claude Code in this repo '
                        f'and work a session</td></tr>')
            continue
        cap = r.get("captured", {})
        gists = (r.get("gist_bpe") or {}).get("latest_per_session") or []
        gist = f"{max(gists):,} BPE" if gists else "–"
        lat = (r.get("checkpoint_latency_ms") or {}).get("max")
        rows.append(
            f'<tr><td class="repo">{name}</td><td>{chip}</td>'
            f'<td>{r.get("sessions", 0)}</td>'
            f'<td>{r.get("turns_packed", 0):,}</td>'
            f'<td>{_bar(cap.get("decisions", 0), max_dec)}</td>'
            f'<td>{cap.get("constraints", 0)} / {cap.get("failed_approaches", 0)}</td>'
            f'<td>{_fallback_cell(r.get("read_path", {}))}</td>'
            f'<td>{gist}<span style="color:var(--ink-3)"> · '
            f'{"–" if lat is None else f"{lat:.0f}ms"}</span></td></tr>')

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CtxPack Scorecard</title><style>{_CSS}</style></head>
<body><div class="wrap">
<h1>CtxPack session-memory scorecard</h1>
<div class="sub">Generated {escape(scorecard.get("generated_at", "?"))}
 &middot; schema {escape(scorecard.get("schema", "?"))}</div>
<div class="note"><strong>Measurement class: observational.</strong>
 These numbers support adoption and token-economics claims only.
 Accuracy claims come from the resume-probe evals; causal claims from
 CompactBench.</div>
<div class="tiles">{tile_html}</div>
<div class="card"><table>
<thead><tr><th>Repo</th><th>Status</th><th>Sessions</th><th>Turns packed</th>
<th>Decisions banked</th><th>Constraints / dead ends</th>
<th>Raw-fallback rate</th><th>Resume cost · ckpt latency</th></tr></thead>
<tbody>{"".join(rows)}</tbody>
</table></div>
<footer>ctxpack scorecard &middot; deterministic Layer-1 telemetry computed
 from each repo's ledger files (<code>checkpoints.jsonl</code> +
 <code>injections.jsonl</code>; git tracking of those files is not
 verified) — no content leaves the repo, only counts.</footer>
</div></body></html>
"""


def _fallback_md(read_path: dict[str, Any]) -> str:
    reads = read_path.get("ledger_reads", 0)
    greps = read_path.get("transcript_greps", 0)
    rate = read_path.get("raw_fallback_rate")
    if rate is None:
        return "no reads yet"
    return f"{rate:.0%} ({greps}/{reads + greps})"


def _injection_md(inj: dict[str, Any]) -> str:
    attempted = int(inj.get("attempted") or 0)
    if not attempted:
        return "not measured"
    failed = int(inj.get("failed") or 0)
    out = f"{int(inj.get('injected') or 0)} / {attempted}"
    return out + (f" ({failed} FAILED)" if failed else "")


def render_markdown(scorecard: dict[str, Any]) -> str:
    """Concise, commit-friendly exec-summary of a scorecard.

    Same deterministic Layer-1 counts as the HTML dashboard, rendered as
    Markdown for a PR comment or a cohort read-path report. Surfaces the
    per-repo ledger-read vs transcript-grep split the dashboard folds into
    a single rate — that per-repo pull is the whole point of a read-path
    report (does each repo's agents actually use the ledger?).
    """
    cohort = scorecard.get("cohort", {})
    repos = scorecard.get("repos", [])
    captured = cohort.get("captured", {})
    rp = cohort.get("read_path", {})
    inj = cohort.get("startup_injection", {})
    rate = rp.get("raw_fallback_rate")
    reads = rp.get("ledger_reads", 0)
    greps = rp.get("transcript_greps", 0)
    rate_txt = ("n/a (no reads yet)" if rate is None
                else f"**{rate:.0%}** ({greps}/{reads + greps} fell back)")

    lines = [
        "# CtxPack session-memory scorecard",
        "",
        f"_Generated {scorecard.get('generated_at', '?')} · "
        f"schema {scorecard.get('schema', '?')}_",
        "",
        "> **Measurement class: observational.** These numbers support "
        "adoption and token-economics claims only. Accuracy claims come "
        "from the resume-probe evals; causal claims from CompactBench.",
        "",
        "## Cohort",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Repos active | {cohort.get('repos_active', 0)} / "
        f"{cohort.get('repos_total', 0)} |",
        f"| Sessions banked | {cohort.get('sessions', 0)} |",
        f"| Turns packed | {cohort.get('turns_packed', 0):,} |",
        f"| Decisions / constraints / dead ends | "
        f"{captured.get('decisions', 0)} / {captured.get('constraints', 0)} / "
        f"{captured.get('failed_approaches', 0)} |",
        f"| Raw-fallback rate | {rate_txt} |",
        f"| Sessions with explicit recall | "
        f"{rp.get('sessions_explicit_recall', 0)} |",
        f"| Sessions with zero explicit recall | "
        f"{rp.get('sessions_zero_recall', 0)} |",
        f"| ...of which a gist was emitted | "
        f"{rp.get('sessions_zero_recall_with_emission', 0)} |",
        f"| ...hook ran, emitted empty (per receipt) | "
        f"{rp.get('sessions_zero_recall_emission_empty', 0)} |",
        f"| ...emission attempt failed (per receipt) | "
        f"{rp.get('sessions_zero_recall_emission_failed', 0)} |",
        f"| ...emission unmeasured (no receipt) | "
        f"{rp.get('sessions_zero_recall_emission_unmeasured', 0)} |",
        f"| Sessions using transcript fallback | "
        f"{rp.get('sessions_transcript_fallback', 0)} |",
        f"| Sessions with no read telemetry | "
        f"{rp.get('sessions_no_telemetry', 0)} |",
        f"| Startup gists emitted to hook stdout / attempted | "
        f"{_injection_md(inj)} |",
        "",
        "Raw-fallback rate = raw-transcript greps ÷ (ledger reads + greps); "
        "lower is better — the earliest honest signal of whether the ledger "
        "earns its keep.",
        "",
        "**Pull vs push.** Explicit recall counts deliberate queries "
        "(`ctx/session_*`, `ctxpack session`) only; the SessionStart "
        "hook is the push path and is not counted. Zero-recall sessions "
        "are split by what their emission receipts prove: gist emitted, "
        "hook ran empty, attempt failed, or unmeasured. A session "
        "without a receipt is unmeasured — absence of a receipt is "
        "never read as “no gist was emitted”.",
        "",
        "**Emission is not use.** The push-path figures measure exactly "
        "one thing: bytes successfully written to the SessionStart "
        "hook's stdout. Whether the harness forwarded them, whether they "
        "entered the model's context, whether the model read them and "
        "whether they helped are four further steps, all unmeasured. No "
        "figure on this page may be described as delivery to an agent, "
        "consumption, use or value. What the read path is measured to be "
        "is *uncalled*; what the push path is measured to be is "
        "*emitted*. Any claim beyond those two needs the flat-file arm, "
        "not this table. Sessions with no telemetry were packed before "
        "these counters existed and are excluded from the denominator: "
        "unmeasured is not the same as unused.",
        "",
        "### Incidents (agent-reported)",
        "",
    ]

    incidents = cohort.get("incident_types") or {}
    if incidents:
        for itype, count in sorted(incidents.items(),
                                   key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"- {itype}: {count}")
    else:
        lines.append("- none recorded")

    lines += [
        "",
        "## By repo",
        "",
        "| Repo | Status | Sessions | Turns | Decisions | "
        "Constraints / dead ends | Ledger reads | Greps | Fallback |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in repos:
        name = str(r.get("repo", "?")).replace("|", "\\|")
        status = str(r.get("status", "?"))
        if status != "active":
            lines.append(
                f"| {name} | {status.replace('_', ' ')} | — | — | — | — | "
                f"— | — | — |")
            continue
        cap = r.get("captured", {})
        rpr = r.get("read_path", {})
        lines.append(
            f"| {name} | active | {r.get('sessions', 0)} | "
            f"{r.get('turns_packed', 0):,} | {cap.get('decisions', 0)} | "
            f"{cap.get('constraints', 0)} / {cap.get('failed_approaches', 0)} | "
            f"{rpr.get('ledger_reads', 0)} | {rpr.get('transcript_greps', 0)} | "
            f"{_fallback_md(rpr)} |")

    lines += [
        "",
        "_Deterministic Layer-1 telemetry from each repo's ledger files "
        "(`checkpoints.jsonl` + `injections.jsonl`; git tracking of those "
        "files is not verified) — no content leaves the repo, only "
        "counts._",
        "",
    ]
    return "\n".join(lines)
