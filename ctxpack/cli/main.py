"""CLI entry point for ctxpack.

Commands:
  ctxpack parse <file> [--level 1|2|3] [--json]
  ctxpack validate <file> [--level 1|2|3]
  ctxpack fmt <file> [--ascii] [--inplace] [--natural-language]
  ctxpack pack <corpus-dir> [-o output.ctx] [--domain X] [--scope X] [--author X] [--ascii] [--validate] [--natural-language]
  ctxpack eval [--golden-set PATH] [--skip-fidelity] [--skip-latency] [--skip-human] [--output PATH]
  ctxpack bench [--sizes 1000,5000,10000] [--iterations 10] [--json]
  ctxpack telemetry [path] [--json]
  ctxpack codebase analyze <repo-path>
  ctxpack codebase export --format claude-md|agents-md <repo-path>
  ctxpack codebase harness <repo-path> [-o output-dir] [--no-hooks] [--no-rules]
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys

from ..core.errors import DiagnosticLevel, ParseError
from ..core.json_export import to_json
from ..core.parser import parse
from ..core.serializer import serialize
from ..core.validator import validate


def main(argv: list[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    if args_list[:1] == ["hook"]:
        # FAIL-OPEN GUARD: a hook that exits non-zero BLOCKS the session
        # (Claude Code refuses to compact on PreCompact failure). Nothing
        # a hook invocation hits — argparse SystemExit on version-skewed
        # event names included — may escape as a non-zero exit.
        try:
            return _run(args_list) or 0
        except BaseException as e:  # noqa: BLE001 — hooks must never fail the session
            print(f"ctxpack hook error (fail-open, session unaffected): {e}",
                  file=sys.stderr)
            return 0
    return _run(args_list)


def _run(argv: list[str]) -> int:
    # Ensure UTF-8 output on Windows
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(
        prog="ctxpack",
        description="CtxPack — MP3 for LLM context: parse, pack, and evaluate .ctx files",
    )
    sub = ap.add_subparsers(dest="command", required=True)

    # parse
    p_parse = sub.add_parser("parse", help="Parse a .ctx file and output AST")
    p_parse.add_argument("file", help="Path to .ctx file")
    p_parse.add_argument(
        "--level", type=int, default=2, choices=[1, 2, 3], help="Conformance level"
    )
    p_parse.add_argument(
        "--json", action="store_true", dest="json_output", help="Output as JSON"
    )

    # validate
    p_val = sub.add_parser("validate", help="Validate a .ctx file")
    p_val.add_argument("file", help="Path to .ctx file")
    p_val.add_argument(
        "--level", type=int, default=2, choices=[1, 2, 3], help="Conformance level"
    )

    # fmt
    p_fmt = sub.add_parser("fmt", help="Format a .ctx file")
    p_fmt.add_argument("file", help="Path to .ctx file")
    p_fmt.add_argument("--ascii", action="store_true", help="ASCII-only output")
    p_fmt.add_argument("--inplace", action="store_true", help="Modify file in place")
    p_fmt.add_argument("--natural-language", action="store_true", dest="natural_language",
                        help="Output in natural language (L1) format")

    # pack
    p_pack = sub.add_parser("pack", help="Pack a corpus directory into a .ctx file")
    p_pack.add_argument("corpus_dir", help="Path to corpus directory")
    p_pack.add_argument("-o", "--output", help="Output .ctx file path")
    p_pack.add_argument("--domain", help="Override domain name")
    p_pack.add_argument("--scope", help="Override scope")
    p_pack.add_argument("--author", help="Override author")
    p_pack.add_argument("--ascii", action="store_true", help="ASCII-only output")
    p_pack.add_argument("--validate", action="store_true", dest="do_validate",
                        help="Validate output after packing")
    p_pack.add_argument("--strict", action="store_true",
                        help="Suppress inferred fields (emit only explicit facts)")
    p_pack.add_argument("--enriched", action="store_true", default=True,
                        help="Emit inferred fields with (inferred) markers (default)")
    p_pack.add_argument("--provenance", choices=["companion", "inline", "none"],
                        default="companion",
                        help="Provenance mode: companion (.ctx.prov file), inline (SRC: in output), none")
    p_pack.add_argument("--layers", default="L2",
                        help="Comma-separated layers to generate (e.g. L2,L3)")
    p_pack.add_argument("--max-ratio", type=float, default=0,
                        help="Maximum compression ratio (e.g. 10.0). 0 = no limit")
    p_pack.add_argument("--min-tokens-per-entity", type=int, default=0,
                        help="Minimum token budget per entity (e.g. 25). 0 = no limit")
    p_pack.add_argument("--natural-language", action="store_true", dest="natural_language",
                        help="Output in natural language (L1) format")
    p_pack.add_argument("--template",
                        help="Domain template name (e.g. pharma, data-platform) or path to template YAML")
    p_pack.add_argument("--preset", choices=["conservative", "balanced", "aggressive"],
                        default="",
                        help="Compression preset (overrides --max-ratio and --min-tokens-per-entity)")
    p_pack.add_argument("--as-of", dest="as_of", default=None,
                        help="Pin the header date (YYYY-MM-DD) for byte-deterministic "
                             "repacks (also settable via CTXPACK_AS_OF)")

    # eval
    p_eval = sub.add_parser("eval", help="Run evaluation against golden set")
    p_eval.add_argument("--golden-set", dest="golden_set", help="Path to golden set directory")
    p_eval.add_argument("--skip-fidelity", action="store_true",
                        help="Skip fidelity testing (no API key needed)")
    p_eval.add_argument("--skip-latency", action="store_true",
                        help="Skip latency measurement")
    p_eval.add_argument("--skip-human", action="store_true",
                        help="Skip human evaluation")
    p_eval.add_argument("--output", help="Output directory for results")
    p_eval.add_argument("--version", default="0.2.0", help="Version tag for results")

    # diff
    p_diff = sub.add_parser("diff", help="Compare two .ctx files")
    p_diff.add_argument("file1", help="First .ctx file")
    p_diff.add_argument("file2", help="Second .ctx file")

    # bench
    p_bench = sub.add_parser("bench", help="Run latency benchmark across corpus sizes")
    p_bench.add_argument("--sizes", default="1000,5000,10000,25000,50000,100000",
                         help="Comma-separated corpus sizes in tokens (default: 1000,5000,10000,25000,50000,100000)")
    p_bench.add_argument("--iterations", type=int, default=10,
                         help="Iterations per size (default: 10)")
    p_bench.add_argument("--json", action="store_true", dest="json_output",
                         help="Output as JSON")

    # hydrate
    p_hydrate = sub.add_parser("hydrate", help="Hydrate sections from a .ctx file")
    p_hydrate.add_argument("file", help="Path to .ctx file")
    p_hydrate.add_argument("--section", help="Section name(s) to hydrate (comma-separated)")
    p_hydrate.add_argument("--query", help="Keyword query for section matching")
    p_hydrate.add_argument("--list", action="store_true", dest="list_sections",
                           help="List available sections with token counts")
    p_hydrate.add_argument("--max-sections", type=int, default=5,
                           help="Max sections to return for query mode (default: 5)")
    p_hydrate.add_argument("--raw", action="store_true",
                           help="Output raw .ctx notation instead of prose (for machine use only)")

    # scaling
    p_scale = sub.add_parser("scaling", help="Run scaling curve experiment")
    p_scale.add_argument("--skip-fidelity", action="store_true",
                         help="Skip fidelity testing (compression-only)")
    p_scale.add_argument("--max-questions", type=int, default=30,
                         help="Max questions per scale (controls API cost)")
    p_scale.add_argument("--regenerate", action="store_true",
                         help="Regenerate scaling corpora")
    p_scale.add_argument("--max-scale", type=int, default=0,
                         help="Max corpus scale to run (e.g. 5000 to skip 20K/50K)")

    # telemetry
    p_telem = sub.add_parser("telemetry", help="Show telemetry summary from hydration logs")
    p_telem.add_argument("path", nargs="?", default=".ctxpack/telemetry.jsonl",
                         help="Path to telemetry JSONL file (default: .ctxpack/telemetry.jsonl)")
    p_telem.add_argument("--json", action="store_true", dest="json_output",
                         help="Output as JSON")

    # codebase
    p_codebase = sub.add_parser("codebase", help="Analyze codebase and generate agent context")
    cb_sub = p_codebase.add_subparsers(dest="codebase_command", required=True)

    cb_analyze = cb_sub.add_parser("analyze", help="Analyze a codebase and print summary")
    cb_analyze.add_argument("repo_path", help="Path to repository root")

    cb_export = cb_sub.add_parser("export", help="Export codebase context to a format")
    cb_export.add_argument("repo_path", help="Path to repository root")
    cb_export.add_argument("--format", dest="export_format", required=True,
                           choices=["claude-md", "agents-md", "rules"],
                           help="Output format: claude-md, agents-md, or rules")
    cb_export.add_argument("-o", "--output", help="Output file path (default: stdout)")
    cb_export.add_argument("--max-lines", type=int, default=200,
                           help="Maximum lines for output (default: 200)")

    # dream — consolidate telemetry into INFERRED patterns
    p_dream = sub.add_parser(
        "dream",
        help="Consolidate telemetry into INFERRED patterns and a gap queue",
    )
    dream_sub = p_dream.add_subparsers(dest="dream_command", required=True)

    d_consolidate = dream_sub.add_parser(
        "consolidate",
        help="Mine co-occurrence patterns and gaps from a telemetry log",
    )
    d_consolidate.add_argument(
        "telemetry_path",
        nargs="?",
        default=".ctxpack/telemetry.jsonl",
        help="Path to telemetry JSONL (default: .ctxpack/telemetry.jsonl)",
    )
    d_consolidate.add_argument(
        "--min-co-occurrences",
        type=int,
        default=3,
        help="Minimum co-occurrences before a pattern is emitted (default: 3)",
    )
    d_consolidate.add_argument(
        "--gap-min-occurrences",
        type=int,
        default=3,
        help="Minimum recurrences before a gap is queued (default: 3)",
    )
    d_consolidate.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output as JSON instead of human-readable text",
    )

    d_queue = dream_sub.add_parser(
        "queue",
        help="Print elicitation prompts for current gaps",
    )
    d_queue.add_argument(
        "telemetry_path",
        nargs="?",
        default=".ctxpack/telemetry.jsonl",
    )
    d_queue.add_argument(
        "--gap-min-occurrences",
        type=int,
        default=3,
    )

    # elicit — capture expert tribal knowledge
    p_elicit = sub.add_parser(
        "elicit",
        help="Capture expert tribal knowledge as ELICITED facts",
    )
    elicit_sub = p_elicit.add_subparsers(dest="elicit_command", required=True)

    e_add = elicit_sub.add_parser("add", help="Capture a fact from a single expert")
    e_add.add_argument("name", help="Entity / section the fact belongs to")
    e_add.add_argument("fact", help="The fact text (free-form)")
    e_add.add_argument("--expert", required=True, help="Expert username")
    e_add.add_argument(
        "--store",
        default=".ctx-cache/elicited.json",
        help="Path to the elicit store (default: .ctx-cache/elicited.json)",
    )

    e_confirm = elicit_sub.add_parser(
        "confirm", help="Second expert confirms an existing fact"
    )
    e_confirm.add_argument("name")
    e_confirm.add_argument("--expert", required=True)
    e_confirm.add_argument("--store", default=".ctx-cache/elicited.json")

    e_challenge = elicit_sub.add_parser(
        "challenge", help="Different expert disputes an existing fact"
    )
    e_challenge.add_argument("name")
    e_challenge.add_argument("--expert", required=True)
    e_challenge.add_argument("--reason", default="")
    e_challenge.add_argument("--store", default=".ctx-cache/elicited.json")

    e_list = elicit_sub.add_parser("list", help="Print all captured facts")
    e_list.add_argument("--store", default=".ctx-cache/elicited.json")
    e_list.add_argument("--json", action="store_true", dest="json_output")

    cb_harness = cb_sub.add_parser("harness", help="Generate anti-drift harness for coding agents")
    cb_harness.add_argument("repo_path", help="Path to repository root")
    cb_harness.add_argument("-o", "--output", help="Output directory (default: <repo>/.claude/)")
    cb_harness.add_argument("--no-hooks", action="store_true",
                            help="Skip hook generation")
    cb_harness.add_argument("--no-rules", action="store_true",
                            help="Skip rules generation")
    cb_harness.add_argument("--max-utility-entries", type=int, default=30,
                            help="Max utility files to list (default: 30)")
    cb_harness.add_argument("--max-pattern-examples", type=int, default=3,
                            help="Max pattern examples per category (default: 3)")

    # checkpoint — pack a Claude Code session transcript into the ledger
    p_ckpt = sub.add_parser(
        "checkpoint",
        help="Pack a Claude Code session transcript into .claude/ctx/ "
             "(the pack-on-compact ledger)")
    p_ckpt.add_argument("--transcript", default=None,
                        help="Path to the session JSONL transcript "
                             "(default: auto-resolve this project's live "
                             "Claude Code session)")
    p_ckpt.add_argument("--out", default=".claude/ctx",
                        help="Output directory (default: .claude/ctx)")
    p_ckpt.add_argument("--as-of", dest="as_of", default=None,
                        help="Pin header date for byte-deterministic packs")
    p_ckpt.add_argument("--session", default=None,
                        help="Session id prefix to select among this "
                             "project's transcripts (default: newest)")

    # hook — entry points wired into .claude/settings.json by install-hooks
    p_hook = sub.add_parser(
        "hook", help="Claude Code hook entry points (read hook JSON on stdin)")
    p_hook.add_argument("event",
                        choices=["pre-compact", "session-start", "session-end",
                                 "stop"],
                        help="Which hook event to handle")
    p_hook.add_argument("--out", default=".claude/ctx",
                        help="Ledger directory (default: .claude/ctx)")

    # install-hooks — wire the checkpoint into a repo's Claude Code config
    p_install = sub.add_parser(
        "install-hooks",
        help="Install PreCompact/SessionStart/SessionEnd hooks into "
             ".claude/settings.json")
    p_install.add_argument("--project-dir", default=".",
                           help="Repo root (default: current directory)")

    # onboard — hooks + MCP + CLAUDE.md conventions + ledger dir, one shot
    p_onboard = sub.add_parser(
        "onboard",
        help="Wire session memory into a repo: hooks, MCP server, "
             "CLAUDE.md conventions, ledger dir (idempotent)")
    p_onboard.add_argument("--project-dir", default=".",
                           help="Repo root (default: current directory)")

    # scorecard — Layer-1 cross-repo telemetry aggregation
    p_score = sub.add_parser(
        "scorecard",
        help="Aggregate every onboarded repo's ledger telemetry into a "
             "versioned scorecard (+ optional HTML dashboard)")
    p_score.add_argument("--repos", nargs="+", default=None,
                         help="Repo paths; omitted = use the saved cohort "
                              "(scorecards/cohort.json)")
    p_score.add_argument("--out", default="scorecards",
                         help="Output dir (default: scorecards/)")
    p_score.add_argument("--html", action="store_true",
                         help="Also render dashboard.html")

    # session — read path over the checkpoint ledger (P4)
    p_session = sub.add_parser(
        "session",
        help="Read the checkpoint ledger: recall | timeline | decisions | "
             "why | literals | resume")
    p_session.add_argument("action",
                           choices=["recall", "timeline", "decisions", "why",
                                    "graph", "stats", "literals", "resume"],
                           help="What to read")
    p_session.add_argument("key", nargs="?", default="",
                           help="why: key to trace; recall: keyword query; "
                                "graph: start entity")
    p_session.add_argument("--ledger", default=".claude/ctx",
                           help="Ledger directory (default: .claude/ctx)")
    p_session.add_argument("--session", dest="session_id", default=None,
                           help="Session id (default: most recent checkpoint)")
    p_session.add_argument("--section", default="",
                           help="recall: section name(s), comma-separated")
    p_session.add_argument("--kinds", default="",
                           help="timeline: comma-separated kind filter "
                                "(DECISION,CONSTRAINT,...)")
    p_session.add_argument("--limit", type=int, default=0,
                           help="timeline: only the last N events")
    p_session.add_argument("--op", default="neighbors",
                           choices=["neighbors", "parents", "bfs", "path"],
                           help="graph: operation (default: neighbors)")
    p_session.add_argument("--to", default="",
                           help="graph path: target entity")
    p_session.add_argument("--depth", type=int, default=2,
                           help="graph bfs: depth (default: 2)")
    p_session.add_argument("--direction", default="out",
                           choices=["out", "in", "both"],
                           help="graph bfs/path: edge direction")

    args = ap.parse_args(argv)

    try:
        if args.command == "parse":
            return _cmd_parse(args)
        elif args.command == "validate":
            return _cmd_validate(args)
        elif args.command == "fmt":
            return _cmd_fmt(args)
        elif args.command == "pack":
            return _cmd_pack(args)
        elif args.command == "eval":
            return _cmd_eval(args)
        elif args.command == "diff":
            return _cmd_diff(args)
        elif args.command == "hydrate":
            return _cmd_hydrate(args)
        elif args.command == "bench":
            return _cmd_bench(args)
        elif args.command == "scaling":
            return _cmd_scaling(args)
        elif args.command == "telemetry":
            return _cmd_telemetry(args)
        elif args.command == "codebase":
            return _cmd_codebase(args)
        elif args.command == "dream":
            return _cmd_dream(args)
        elif args.command == "elicit":
            return _cmd_elicit(args)
        elif args.command == "checkpoint":
            return _cmd_checkpoint(args)
        elif args.command == "hook":
            return _cmd_hook(args)
        elif args.command == "install-hooks":
            return _cmd_install_hooks(args)
        elif args.command == "onboard":
            return _cmd_onboard(args)
        elif args.command == "scorecard":
            return _cmd_scorecard(args)
        elif args.command == "session":
            return _cmd_session(args)
    except ParseError as e:
        print(f"Parse error: {e}", file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        print(f"File not found: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    return 0


def _cmd_parse(args: argparse.Namespace) -> int:
    text = _read_file(args.file)
    doc = parse(text, level=args.level, filename=args.file)

    if args.json_output:
        print(to_json(doc))
    else:
        # Summary output
        h = doc.header
        print(f"Magic: {h.magic}")
        print(f"Version: {h.version}")
        print(f"Layer: {h.layer.value}")
        print(f"Fields: {len(h.all_fields)}")
        if args.level >= 2:
            sections = _count_sections(doc.body)
            print(f"Sections: {sections}")
            print(f"Body elements: {len(doc.body)}")

    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    text = _read_file(args.file)
    doc = parse(text, level=args.level, filename=args.file)
    diags = validate(doc, level=args.level)

    if not diags:
        print(f"{args.file}: OK")
        return 0

    errors = 0
    for d in diags:
        print(d)
        if d.level == DiagnosticLevel.ERROR:
            errors += 1

    return 1 if errors > 0 else 0


def _cmd_fmt(args: argparse.Namespace) -> int:
    text = _read_file(args.file)
    doc = parse(text, level=2, filename=args.file)
    output = serialize(doc, ascii_mode=args.ascii, natural_language=args.natural_language)

    if args.inplace:
        with open(args.file, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Formatted {args.file}")
    else:
        print(output, end="")

    return 0


def _cmd_pack(args: argparse.Namespace) -> int:
    from ..core.packer import pack

    layer_list = [l.strip() for l in args.layers.split(",")]
    result = pack(
        args.corpus_dir,
        domain=args.domain,
        scope=args.scope,
        author=args.author,
        strict=args.strict,
        provenance=args.provenance,
        layers=layer_list,
        max_ratio=args.max_ratio,
        min_tokens_per_entity=args.min_tokens_per_entity,
        template=args.template,
        preset=args.preset,
        as_of=args.as_of,
    )

    output_text = serialize(result.document, ascii_mode=args.ascii,
                            natural_language=args.natural_language)

    if args.do_validate:
        diags = validate(result.document)
        errors = [d for d in diags if d.level == DiagnosticLevel.ERROR]
        if errors:
            for d in errors:
                print(d, file=sys.stderr)
            print(f"Validation failed with {len(errors)} error(s)", file=sys.stderr)
            return 1

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_text)
        print(f"Packed {result.source_file_count} files → {args.output}")

        # Write companion provenance file if available
        if result.provenance_text and args.provenance == "companion":
            prov_path = args.output + ".prov"
            with open(prov_path, "w", encoding="utf-8") as f:
                f.write(result.provenance_text)
            print(f"  Provenance: {prov_path}")

        # Write L3 and manifest if generated
        if result.l3_document:
            import os
            out_dir = os.path.dirname(args.output) or "."
            l3_path = os.path.join(out_dir, "L3.ctx")
            with open(l3_path, "w", encoding="utf-8") as f:
                f.write(serialize(result.l3_document, ascii_mode=args.ascii))
            print(f"  L3 gist: {l3_path}")

        if result.manifest_document:
            manifest_path = os.path.join(out_dir, "MANIFEST.ctx")
            with open(manifest_path, "w", encoding="utf-8") as f:
                f.write(serialize(result.manifest_document, ascii_mode=args.ascii))
            print(f"  Manifest: {manifest_path}")

        print(f"  Entities: {result.entity_count}")
        print(f"  Source tokens: ~{result.source_token_count}")
        print(f"  Warnings: {result.warning_count}")
    else:
        print(output_text, end="")

    return 0


def _cmd_hydrate(args: argparse.Namespace) -> int:
    from ..core.hydrator import hydrate_by_name, hydrate_by_query, list_sections
    from ..core.serializer import serialize_section

    text = _read_file(args.file)
    doc = parse(text, level=2, filename=args.file)

    if args.list_sections:
        sections = list_sections(doc)
        print(f"Sections in {args.file}:")
        for s in sections:
            print(f"  {s['name']:40s} ~{s['tokens']:>4d} tokens")
        print(f"\nTotal: {len(sections)} sections")
        return 0

    if args.section:
        names = [n.strip() for n in args.section.split(",")]
        result = hydrate_by_name(doc, names)
    elif args.query:
        result = hydrate_by_query(doc, args.query, max_sections=args.max_sections)
    else:
        print("Provide --section, --query, or --list", file=sys.stderr)
        return 1

    # Print header
    if result.header_text:
        print(result.header_text)
        print()

    # Print matched sections — prose by default for LLM consumption
    use_raw = getattr(args, "raw", False)
    for section in result.sections:
        for line in serialize_section(section, natural_language=not use_raw):
            print(line)
        print()

    # Summary to stderr
    print(f"[{len(result.sections)}/{result.sections_available} sections, "
          f"~{result.tokens_injected} tokens]", file=sys.stderr)
    return 0


def _cmd_diff(args: argparse.Namespace) -> int:
    from ..core.diff import diff_documents, format_diff

    text1 = _read_file(args.file1)
    text2 = _read_file(args.file2)
    doc1 = parse(text1, level=2, filename=args.file1)
    doc2 = parse(text2, level=2, filename=args.file2)

    result = diff_documents(doc1, doc2)
    print(format_diff(result))

    return 0 if not result.has_changes else 1


def _cmd_eval(args: argparse.Namespace) -> int:
    import json

    from ..benchmarks.eval_config import EvalConfig
    from ..benchmarks.runner import run_eval, save_results
    from ..core.packer import pack

    config = EvalConfig(
        run_fidelity=not args.skip_fidelity,
        run_latency=not args.skip_latency,
        run_human_eval=not args.skip_human,
    )

    if args.golden_set:
        config.golden_set_path = args.golden_set
    if args.output:
        config.output_dir = args.output

    # Pack the golden set corpus
    import os
    corpus_dir = os.path.join(config.golden_set_path, "corpus")
    if not os.path.isdir(corpus_dir):
        print(f"Golden set corpus not found: {corpus_dir}", file=sys.stderr)
        return 1

    print(f"Packing golden set corpus: {corpus_dir}")
    pack_result = pack(corpus_dir)
    ctx_text = serialize(pack_result.document)

    print(f"Running evaluation (fidelity={'on' if config.run_fidelity else 'off'})...")
    results = run_eval(config, ctx_text=ctx_text, version=args.version)

    # Save results
    path = save_results(results, config)
    print(f"Results saved: {path}")

    # Print summary
    print(f"\n{'='*50}")
    print(f"  ctxpack eval v{args.version}")
    print(f"{'='*50}")
    for name, data in results.get("baselines", {}).items():
        tokens = data.get("tokens", "?")
        ratio = data.get("ratio", "?")
        cost = data.get("cost", "?")
        fidelity = data.get("fidelity", "N/A")
        details = data.get("fidelity_details", {})
        llm_judge = details.get("llm_judge_score", "")
        judge_str = f"  judge={llm_judge}" if llm_judge != "" else ""
        print(f"  {name:20s}  tokens={tokens:>6}  ratio={ratio:>6}  cost={cost}  fidelity={fidelity}{judge_str}")

    if "conflict_detection" in results:
        cd = results["conflict_detection"]
        print(f"\n  Conflict detection: planted={cd['planted']} found={cd['found']} "
              f"P={cd['precision']} R={cd['recall']}")

    return 0


def _cmd_scaling(args: argparse.Namespace) -> int:
    from ..benchmarks.scaling.scaling_runner import (
        run_scaling_eval,
        save_scaling_results,
        print_scaling_summary,
    )

    base_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "benchmarks", "scaling",
    )

    print("Running scaling curve experiment...")
    results = run_scaling_eval(
        base_dir,
        max_questions_per_scale=args.max_questions,
        regenerate=args.regenerate,
        skip_fidelity=args.skip_fidelity,
        max_scale=args.max_scale,
    )

    output_path = os.path.join(base_dir, "results", "scaling_curve.json")
    save_scaling_results(results, output_path)
    print(f"\nResults saved: {output_path}")

    print_scaling_summary(results)
    return 0


def _cmd_bench(args: argparse.Namespace) -> int:
    from ..benchmarks.bench import format_table, run_bench

    sizes = [int(s.strip()) for s in args.sizes.split(",")]
    print(f"Running latency benchmark: sizes={sizes}, iterations={args.iterations}")

    suite = run_bench(sizes=sizes, iterations=args.iterations)

    if args.json_output:
        print(suite.to_json())
    else:
        print()
        print(format_table(suite))

    return 0


def _cmd_telemetry(args: argparse.Namespace) -> int:
    import json as _json

    from ..core.telemetry import TelemetryLog

    tlog = TelemetryLog(path=args.path)
    summary = tlog.summary()

    if args.json_output:
        print(_json.dumps(summary, indent=2))
    else:
        print(f"Telemetry summary: {args.path}")
        print(f"{'='*50}")
        print(f"  Total hydrations:       {summary['total_hydrations']}")
        print(f"  Unique sessions:        {summary['unique_sessions']}")
        print(f"  Avg tokens/hydration:   {summary['avg_tokens_per_hydration']:.1f}")
        print(f"  Avg latency (ms):       {summary['avg_latency_ms']:.2f}")
        print(f"  Rehydration rate:       {summary['rehydration_rate']:.1%}")
        print(f"  Zero-match rate:        {summary['zero_match_rate']:.1%}")

        if summary['top_sections']:
            print(f"\n  Top sections:")
            for name, count in summary['top_sections'][:10]:
                print(f"    {name:40s} {count:>4d}")

    return 0


def _cmd_codebase(args: argparse.Namespace) -> int:
    from ..modules.codebase import (
        analyze_codebase, export_claude_md, export_agents_md, export_rules,
        generate_harness,
    )

    repo_path = args.repo_path
    if not os.path.isdir(repo_path):
        print(f"Not a directory: {repo_path}", file=sys.stderr)
        return 1

    if args.codebase_command == "harness":
        print(f"Generating anti-drift harness for: {repo_path}", file=sys.stderr)
        output_dir = args.output or ""
        files = generate_harness(
            repo_path,
            output_dir=output_dir,
            include_hooks=not args.no_hooks,
            include_rules=not args.no_rules,
            max_utility_entries=args.max_utility_entries,
            max_pattern_examples=args.max_pattern_examples,
        )
        for f in files:
            print(f"  Created: {f}")
        if files:
            print(f"\n{len(files)} harness files generated.", file=sys.stderr)
        else:
            print("No new files created (all already exist).", file=sys.stderr)
        return 0

    print(f"Analyzing codebase: {repo_path}", file=sys.stderr)
    cmap = analyze_codebase(repo_path)

    if args.codebase_command == "analyze":
        print(f"Files: {cmap.total_files}")
        print(f"Lines: {cmap.total_lines:,}")
        print(f"Architecture: {cmap.architecture}")
        print(f"Frameworks: {', '.join(cmap.frameworks)}")
        all_routes = sum(len(m.routes) for m in cmap.modules)
        all_models = sum(len(m.models) for m in cmap.modules)
        total_tests = sum(m.test_count for m in cmap.modules)
        print(f"API routes: {all_routes}")
        print(f"Data models: {all_models}")
        print(f"Test functions: {total_tests}")
        return 0

    elif args.codebase_command == "export":
        max_lines = args.max_lines
        fmt = args.export_format

        if fmt == "claude-md":
            # Generate supplementary codebase map (NOT a CLAUDE.md replacement)
            existing = ""
            existing_path = os.path.join(repo_path, "CLAUDE.md")
            if os.path.isfile(existing_path):
                with open(existing_path, encoding="utf-8") as f:
                    existing = f.read()
                print("NOTE: Existing CLAUDE.md found. This generates a SUPPLEMENTARY", file=sys.stderr)
                print("codebase map, not a replacement. Add '@.claude/codebase-map.md'", file=sys.stderr)
                print("to your CLAUDE.md to import it.", file=sys.stderr)
            output = export_claude_md(cmap, existing_claude_md=existing, max_lines=max_lines)
        elif fmt == "agents-md":
            output = export_agents_md(cmap, max_lines=max_lines)
        elif fmt == "rules":
            out_dir = args.output or os.path.join(repo_path, ".claude", "rules")
            files = export_rules(cmap, out_dir)
            for f in files:
                print(f"  Created: {f}")
            print(f"\n{len(files)} rule files written to {out_dir}")
            return 0
        else:
            print(f"Unknown format: {fmt}", file=sys.stderr)
            return 1

        if args.output:
            os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output)
            print(f"Written to {args.output}", file=sys.stderr)
        else:
            print(output)

        return 0

    return 0


def _cmd_dream(args: argparse.Namespace) -> int:
    """Run a consolidation pass over a telemetry log."""
    import json as _json

    from ..core.telemetry import TelemetryLog
    from ..modules.dream import consolidate, detect_gaps
    from ..modules.elicit import build_elicitation_prompt as _bep

    tlog = TelemetryLog(path=args.telemetry_path)

    if args.dream_command == "consolidate":
        result = consolidate(
            tlog,
            min_co_occurrences=args.min_co_occurrences,
            gap_min_occurrences=args.gap_min_occurrences,
        )
        if getattr(args, "json_output", False):
            payload = {
                "patterns": [
                    {
                        "name": e.name,
                        "confidence": e.confidence,
                        "observation_count": e.observation_count,
                    }
                    for e in result.entities
                ],
                "gaps": [
                    {
                        "question_hash": g.question_hash,
                        "occurrences": g.occurrences,
                        "first_seen": g.first_seen,
                        "last_seen": g.last_seen,
                    }
                    for g in result.gaps
                ],
            }
            print(_json.dumps(payload, indent=2))
            return 0

        print(f"Dream pass over {args.telemetry_path}")
        print("=" * 60)
        print(f"Patterns mined : {len(result.entities)}")
        print(f"Gaps queued    : {len(result.gaps)}")
        if result.entities:
            print("\nTop patterns (by observation count):")
            for e in sorted(
                result.entities, key=lambda e: -e.observation_count
            )[:10]:
                print(
                    f"  {e.name:60s}  obs={e.observation_count:>4d}  "
                    f"conf={e.confidence:.2f}"
                )
        if result.gaps:
            print("\nTop gaps:")
            for g in result.gaps[:10]:
                print(
                    f"  {g.question_hash[:16]:<16s}  occurred {g.occurrences} times "
                    f"({g.first_seen[:10]} → {g.last_seen[:10]})"
                )
        return 0

    if args.dream_command == "queue":
        gaps = detect_gaps(tlog, min_occurrences=args.gap_min_occurrences)
        if not gaps:
            print(f"No gaps above threshold in {args.telemetry_path}.")
            return 0
        for g in gaps:
            print(_bep(g))
            print("---")
        return 0

    return 1


def _cmd_elicit(args: argparse.Namespace) -> int:
    """Capture / confirm / challenge / list ELICITED facts."""
    import json as _json

    from ..modules.elicit import ElicitStore

    store = ElicitStore.load(args.store)

    if args.elicit_command == "add":
        store.add(name=args.name, fact=args.fact, expert=args.expert)
        store.save(args.store)
        print(
            f"Captured ELICITED fact for {args.name} (expert={args.expert}, "
            f"confidence=0.70). Stored in {args.store}."
        )
        return 0

    if args.elicit_command == "confirm":
        store.confirm(name=args.name, expert=args.expert)
        store.save(args.store)
        f = store.get(args.name)
        print(
            f"{args.expert} confirmed {args.name}. Confidence is now "
            f"{f.confidence:.2f}."
        )
        return 0

    if args.elicit_command == "challenge":
        store.challenge(
            name=args.name, expert=args.expert, reason=args.reason
        )
        store.save(args.store)
        f = store.get(args.name)
        print(
            f"{args.expert} challenged {args.name}. Confidence dropped to "
            f"{f.confidence:.2f}."
        )
        return 0

    if args.elicit_command == "list":
        if getattr(args, "json_output", False):
            payload = {
                "facts": [
                    {
                        "name": f.name,
                        "fact": f.fact,
                        "original_expert": f.original_expert,
                        "confirming_expert": f.confirming_expert,
                        "confidence": f.confidence,
                        "dissenters": f.dissenters,
                    }
                    for f in store.list()
                ]
            }
            print(_json.dumps(payload, indent=2))
            return 0
        if not store.list():
            print(f"No elicited facts in {args.store}.")
            return 0
        print(f"Elicited facts ({len(store)})")
        print("=" * 60)
        for f in store.list():
            confirmer = (
                f", confirmed by {f.confirming_expert}"
                if f.confirming_expert
                else ""
            )
            dissent = (
                f", challenged by {','.join(f.dissenters)}"
                if f.dissenters
                else ""
            )
            print(
                f"  {f.name}  conf={f.confidence:.2f}  "
                f"by {f.original_expert}{confirmer}{dissent}"
            )
            print(f"    {f.fact}")
        return 0

    return 1


def _read_file(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _count_sections(elements) -> int:
    count = 0
    for elem in elements:
        from ..core.model import Section

        if isinstance(elem, Section):
            count += 1
            count += _count_sections(elem.children)
    return count


def _cmd_checkpoint(args: argparse.Namespace) -> int:
    from ..agent.checkpoint import find_live_transcript, run_checkpoint

    transcript = args.transcript
    if not transcript:
        try:
            transcript = find_live_transcript(".", getattr(args, "session", None))
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        print(f"Transcript: {transcript}")

    result = run_checkpoint(transcript, args.out, as_of=args.as_of)
    print(f"Checkpoint: session {result.session_id[:8]} "
          f"({result.turns} turns) -> {result.ctx_path}")
    print(f"  entities: {result.entities}  conflicts: {result.conflicts}  "
          f"gist: {result.gist_bpe} BPE  sha256: {result.ledger_sha256[:12]}")
    return 0


def _cmd_hook(args: argparse.Namespace) -> int:
    """Claude Code hook entry point. Reads the hook event JSON on stdin.

    pre-compact / session-end: run a checkpoint (side effect only).
    session-start: emit additionalContext JSON carrying the latest gist.
    Never fails the hook — a broken ledger must not break the session.
    """
    import io as _io
    import json as _json

    from ..agent.checkpoint import run_checkpoint

    # Per-invocation kill switch: CTXPACK_HOOK_SKIP="stop,session-end"
    # no-ops those events. Used by harnesses that fork probe sessions
    # (CompactBench: a probe fork must not checkpoint itself over the
    # session under test) and for a temporary clean slate in dogfood.
    skip = {s.strip() for s in
            os.environ.get("CTXPACK_HOOK_SKIP", "").split(",") if s.strip()}
    if args.event in skip:
        return 0

    # Read stdin as UTF-8 explicitly: on Windows the default is the locale
    # codec (cp1252), which corrupts non-ASCII transcript paths in the
    # hook payload.
    try:
        raw = _io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8").read()
    except (AttributeError, OSError):
        raw = sys.stdin.read()
    try:
        payload = _json.loads(raw or "{}")
    except _json.JSONDecodeError:
        payload = {}

    # Anchor a relative ledger dir to the project the hook fired in (the
    # payload carries the project cwd), not to the process cwd.
    out_dir = args.out
    if not os.path.isabs(out_dir) and payload.get("cwd"):
        out_dir = os.path.join(str(payload["cwd"]), out_dir)

    if args.event in ("pre-compact", "session-end", "stop"):
        transcript = payload.get("transcript_path", "")
        if transcript and os.path.exists(transcript):
            try:
                # Stop fires every turn — debounce; the other two always pack
                if args.event == "stop":
                    from ..agent.checkpoint import should_checkpoint_on_stop
                    if not should_checkpoint_on_stop(
                            transcript, out_dir,
                            str(payload.get("session_id", ""))):
                        return 0
                result = run_checkpoint(transcript, out_dir)
                print(f"ctxpack checkpoint: {result.entities} entities, "
                      f"{result.turns} turns -> {result.ctx_path}",
                      file=sys.stderr)
            except Exception as e:  # noqa: BLE001 — hooks must not fail the session
                print(f"ctxpack checkpoint failed: {e}", file=sys.stderr)
        return 0

    # session-start: inject the project rollup (cross-session decisions/
    # constraints/failed approaches) + the previous session's gist. This
    # includes /clear — clearing resets the CONTEXT, not the project memory
    # ("compaction is a commit, not a loss event" applies to clears too).
    # A true blank slate = temporarily disable the hooks.
    from ..agent.checkpoint import read_startup_context
    gist = read_startup_context(out_dir)
    if gist:
        print(_json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": gist,
            }
        }))
    return 0


def _cmd_scorecard(args: argparse.Namespace) -> int:
    """Layer-1 aggregation: cohort ledgers → versioned scorecard (+ HTML)."""
    from ..agent.scorecard import (
        build_scorecard,
        load_cohort,
        save_cohort,
        write_scorecard,
    )

    repos = args.repos
    if repos:
        save_cohort(repos, args.out)
    else:
        repos = load_cohort(args.out)
        if not repos:
            print("Error: no --repos given and no saved cohort at "
                  f"{args.out}/cohort.json", file=sys.stderr)
            return 1

    scorecard = build_scorecard(repos)
    json_path, latest = write_scorecard(scorecard, args.out)
    print(f"Scorecard: {json_path}")

    cohort = scorecard["cohort"]
    rate = cohort["read_path"]["raw_fallback_rate"]
    print(f"  repos: {cohort['repos_active']}/{cohort['repos_total']} active"
          f"  sessions: {cohort['sessions']}"
          f"  turns packed: {cohort['turns_packed']:,}")
    print(f"  captured: {cohort['captured']['decisions']} decisions, "
          f"{cohort['captured']['constraints']} constraints, "
          f"{cohort['captured']['failed_approaches']} dead ends")
    print(f"  raw-fallback rate: "
          f"{'n/a (no reads yet)' if rate is None else f'{rate:.0%}'}")
    for r in scorecard["repos"]:
        mark = "*" if r.get("status") == "active" else "-"
        print(f"   {mark} {r['repo']}: {r.get('status')}"
              + (f" ({r.get('sessions')} sessions, "
                 f"{r.get('captured', {}).get('decisions', 0)} decisions)"
                 if r.get("status") == "active" else ""))

    if args.html:
        from ..agent.dashboard import render_dashboard

        html_path = os.path.join(args.out, "dashboard.html")
        with open(html_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(render_dashboard(scorecard))
        print(f"Dashboard: {html_path}")
    return 0


def _cmd_session(args: argparse.Namespace) -> int:
    """Read path over the checkpoint ledger — the CLI twin of the MCP
    session tools, so any agent with a shell can use the ledger."""
    from ..agent.session_reader import (
        LedgerError,
        load_session,
        session_decisions,
        session_literals,
        session_recall,
        session_resume,
        session_stats,
        session_timeline,
        session_why,
    )

    if args.action == "stats":
        try:
            print(json.dumps(session_stats(args.ledger), indent=2))
        except LedgerError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        return 0

    if args.action == "resume":
        try:
            result = session_resume(args.ledger, args.session_id)
        except LedgerError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        gist = result.pop("gist", "")
        print(json.dumps(result, indent=2))
        if gist:
            print()
            print("--- startup gist ---")
            print(gist)
        return 0

    try:
        doc, sid = load_session(args.ledger, args.session_id)
    except LedgerError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.action == "recall":
        result = session_recall(doc, sid, section=args.section,
                                query=args.key)
    elif args.action == "timeline":
        kinds = [k.strip() for k in args.kinds.split(",") if k.strip()]
        result = session_timeline(doc, sid, kinds=kinds or None,
                                  limit=args.limit)
    elif args.action == "decisions":
        result = session_decisions(doc, sid)
    elif args.action == "literals":
        result = session_literals(doc, sid)
    elif args.action == "graph":
        from ..core.entity_graph import EntityGraph

        if not args.key:
            print("Error: `ctxpack session graph <entity>` needs an entity",
                  file=sys.stderr)
            return 1
        result = EntityGraph.from_document(doc).query(
            args.op, args.key, to=args.to, depth=args.depth,
            direction=args.direction)
        result = {"session": sid, **result}
    else:  # why
        if not args.key:
            print("Error: `ctxpack session why <key>` needs a key",
                  file=sys.stderr)
            return 1
        result = session_why(doc, sid, args.key)

    # Prose payloads print as prose; structured payloads as JSON.
    text = result.pop("text", None)
    if text is not None:
        meta = ", ".join(f"{k}={v}" for k, v in result.items())
        print(f"[{meta}]")
        print()
        print(text)
    else:
        print(json.dumps(result, indent=2))
    return 0


# Hook commands run `python -m ctxpack.cli.main` rather than the `ctxpack`
# console script: hooks execute with cwd = the project dir, where the
# package is importable directly — so the hooks work on any machine with
# python on PATH, with no pip install required and no dependence on the
# Scripts directory being on PATH.
# -P (safe path, Python 3.11+): without it, `python -m` prepends the
# project cwd to sys.path, so a repo carrying a vendored/stale ctxpack
# copy shadows the installed one — observed in the wild as an OLD ctxpack
# rejecting the `hook` subcommand and BLOCKING compaction.
_HOOK_CMD = ("python -P -m ctxpack.cli.main hook"
             if sys.version_info >= (3, 11)
             else "python -m ctxpack.cli.main hook")
_CTXPACK_HOOK_MARKERS = ("ctxpack hook", "ctxpack.cli.main hook")

_HOOK_SETTINGS = {
    "PreCompact": [{"hooks": [{"type": "command",
                               "command": f"{_HOOK_CMD} pre-compact"}]}],
    "SessionStart": [{"matcher": "startup|resume|compact|clear",
                      "hooks": [{"type": "command",
                                 "command": f"{_HOOK_CMD} session-start"}]}],
    "SessionEnd": [{"hooks": [{"type": "command",
                               "command": f"{_HOOK_CMD} session-end"}]}],
    # Debounced per-turn checkpoint: shrinks the crash-recovery window to
    # ~CTXPACK_STOP_DEBOUNCE_TURNS turns (default 10) with no manual step
    "Stop": [{"hooks": [{"type": "command",
                         "command": f"{_HOOK_CMD} stop"}]}],
}


def _is_ctxpack_hook(hook: dict) -> bool:
    cmd = str(hook.get("command", ""))
    return any(marker in cmd for marker in _CTXPACK_HOOK_MARKERS)


def _install_hooks_into(project_dir: str) -> "str | None":
    """Merge the checkpoint hooks into <project>/.claude/settings.json.

    Existing ctxpack hook entries are replaced, everything else is
    preserved. Returns the settings path, or None if the existing file is
    unparseable (never overwrite what we can't read).
    """
    import json as _json

    claude_dir = os.path.join(project_dir, ".claude")
    os.makedirs(claude_dir, exist_ok=True)
    settings_path = os.path.join(claude_dir, "settings.json")

    settings: dict = {}
    if os.path.exists(settings_path):
        # utf-8-sig: tolerate a BOM from PowerShell / legacy editors
        with open(settings_path, encoding="utf-8-sig") as f:
            try:
                settings = _json.load(f)
            except _json.JSONDecodeError:
                return None

    hooks = settings.setdefault("hooks", {})
    for event, entries in _HOOK_SETTINGS.items():
        existing = hooks.get(event, [])
        # Remove prior ctxpack hooks at the INNER level: an entry that
        # mixes user hooks with a ctxpack hook keeps the user's hooks.
        kept = []
        for entry in existing:
            remaining = [h for h in entry.get("hooks", [])
                         if not _is_ctxpack_hook(h)]
            if remaining:
                kept.append({**entry, "hooks": remaining})
            elif not entry.get("hooks"):
                kept.append(entry)  # entry with no hooks list — not ours
        hooks[event] = kept + entries

    with open(settings_path, "w", encoding="utf-8", newline="\n") as f:
        _json.dump(settings, f, indent=2)
        f.write("\n")
    return settings_path


def _print_restart_warning() -> None:
    print("IMPORTANT: Claude Code snapshots hook + MCP config at process")
    print("startup — nothing fires until you restart Claude Code (and")
    print("approve the hooks/server when prompted). /clear is not a restart.")


def _cmd_install_hooks(args: argparse.Namespace) -> int:
    settings_path = _install_hooks_into(args.project_dir)
    if settings_path is None:
        print("Refusing to overwrite unparseable .claude/settings.json",
              file=sys.stderr)
        return 1
    print(f"Installed ctxpack hooks into {settings_path}")
    print(f"  PreCompact  -> {_HOOK_CMD} pre-compact   (pack before summarize)")
    print(f"  SessionStart-> {_HOOK_CMD} session-start (re-inject gists)")
    print(f"  SessionEnd  -> {_HOOK_CMD} session-end   (final checkpoint)")
    print(f"  Stop        -> {_HOOK_CMD} stop          (debounced per-turn checkpoint)")
    print("Ledger dir: .claude/ctx/  (commit it to give the repo durable memory)")
    print()
    _print_restart_warning()
    return 0


# ── onboard: the whole session-memory setup in one command ──

_MCP_SERVER_ENTRY = {
    "command": "python",
    "args": ["-m", "ctxpack.integrations.mcp_server"],
}

# Version the conventions block so a re-onboard after upgrading ctxpack
# REFRESHES a stale block in place (v1 repos taught agents a read path
# missing resume/literals/checkpoint) instead of skipping with "already
# present". Bump the version whenever the block content changes.
_CLAUDE_MD_MARKER_PREFIX = "<!-- ctxpack:session-memory:"
_CLAUDE_MD_MARKER = f"{_CLAUDE_MD_MARKER_PREFIX}v3 -->"
_CLAUDE_MD_END = "<!-- /ctxpack:session-memory -->"

_CLAUDE_MD_BLOCK = f"""
{_CLAUDE_MD_MARKER}
## Session memory (ctxpack ledger)

This repo uses CtxPack Checkpoint: hooks pack every compaction and
session end into `.claude/ctx/` (a deterministic ledger — the raw
transcript is never deleted), and each session start re-injects the
previous session's gist. Trust the gist's constraints and decisions.

**Resuming or recalling past-session detail — use the ledger read path
FIRST**; fall back to grepping the raw transcript only if it fails
(fallbacks are tracked):

- One-call resume: `ctx/resume` (MCP) or `ctxpack session resume` —
  gist + decisions + constraints + failed approaches + exact identifiers
- MCP (if connected): `ctx/session_recall`, `ctx/session_timeline`,
  `ctx/session_decisions`, `ctx/session_literals`, `ctx/why`,
  `ctx/graph_query`
- CLI twins: `ctxpack session decisions | timeline | recall | literals |
  why | graph | resume` (`--session <id>` targets older sessions;
  `ctxpack session stats` shows adoption + capture metrics)
- Bank the session BEFORE `/clear` or risky context loss: `ctx/checkpoint`
  (MCP) or bare `ctxpack checkpoint` (both auto-resolve the live
  transcript)

**Decision convention (load-bearing):** state every nontrivial decision
(design choice, root cause, chosen fix, abandoned approach) in your reply
on its own sentence starting with `Decision:` — e.g. `Decision: use
exponential backoff with base 750ms because the vendor limit is 40
req/min.` The deterministic parser extracts these; unmarked decisions in
free prose are often missed. Dead ends the same way: "The X approach
didn't work because ...". Operating rules you set yourself the same way,
sentence-leading: `Constraint: eval results are immutable — write new
versioned files, never overwrite.`

**Incident convention (memory telemetry):** when the ledger visibly helps
or fails you, record it on its own line, sentence-leading:
`ctx-incident: <type> | fact="<the fact involved>" | expected="..." |
got="..." | evidence="..."` — types: saved, missed, stale, wrong,
conflicting, native-better, user-corrected. Only type and fact are
required; include the concrete value so the row is auditable. Examples:
`ctx-incident: stale | fact="CACHE-TTL-S current value" | expected="25"
| got="50"` or `ctx-incident: saved | fact="commit 66cdded scope" |
evidence="session why returned turn 408"`. Report failures as readily as
saves — a missed/stale row is worth more than a flattering one.
{_CLAUDE_MD_END}
"""


def _cmd_onboard(args: argparse.Namespace) -> int:
    """Set up session memory in a repo: hooks + MCP + CLAUDE.md + ledger
    dir. Idempotent — safe to re-run after upgrades."""
    import json as _json

    project = os.path.abspath(args.project_dir)
    done: list[str] = []

    # 1. Hooks (write path)
    settings_path = _install_hooks_into(project)
    if settings_path is None:
        print("Refusing to overwrite unparseable .claude/settings.json",
              file=sys.stderr)
        return 1
    done.append(f"hooks       -> {settings_path}")

    # 2. MCP server (read path)
    mcp_path = os.path.join(project, ".mcp.json")
    mcp_config: dict = {}
    if os.path.exists(mcp_path):
        with open(mcp_path, encoding="utf-8-sig") as f:
            try:
                mcp_config = _json.load(f)
            except _json.JSONDecodeError:
                print(f"Refusing to overwrite unparseable {mcp_path}",
                      file=sys.stderr)
                return 1
    servers = mcp_config.setdefault("mcpServers", {})
    if "ctxpack" not in servers:
        servers["ctxpack"] = dict(_MCP_SERVER_ENTRY)
        with open(mcp_path, "w", encoding="utf-8", newline="\n") as f:
            _json.dump(mcp_config, f, indent=2)
            f.write("\n")
        done.append(f"mcp server  -> {mcp_path}")
    else:
        done.append(f"mcp server  -> {mcp_path} (already present)")

    # 3. CLAUDE.md conventions — marker-guarded, append-only
    claude_md = os.path.join(project, "CLAUDE.md")
    existing_md = ""
    if os.path.exists(claude_md):
        with open(claude_md, encoding="utf-8-sig") as f:
            existing_md = f.read()
    start = existing_md.find(_CLAUDE_MD_MARKER_PREFIX)
    end = existing_md.find(_CLAUDE_MD_END)
    if _CLAUDE_MD_MARKER in existing_md:
        done.append(f"claude.md   -> {claude_md} (block already present)")
    elif start != -1 and end > start:
        # An older-version block: refresh it in place so upgraded repos
        # actually learn the new read/write surfaces.
        updated = (existing_md[:start] + _CLAUDE_MD_BLOCK.strip()
                   + existing_md[end + len(_CLAUDE_MD_END):])
        with open(claude_md, "w", encoding="utf-8", newline="\n") as f:
            f.write(updated)
        done.append(f"claude.md   -> {claude_md} (conventions refreshed to "
                    "current version)")
    elif start != -1:
        # Start marker without end marker — hand-edited; don't guess.
        done.append(f"claude.md   -> {claude_md} (ctxpack block has no end "
                    "marker — update it manually)")
    else:
        with open(claude_md, "a", encoding="utf-8", newline="\n") as f:
            if existing_md and not existing_md.endswith("\n"):
                f.write("\n")
            f.write(_CLAUDE_MD_BLOCK)
        done.append(f"claude.md   -> {claude_md} (conventions appended)")

    # 4. Ledger dir
    ledger = os.path.join(project, ".claude", "ctx")
    os.makedirs(ledger, exist_ok=True)
    done.append(f"ledger dir  -> {ledger}")

    print("ctxpack onboard — session memory wired into this repo:")
    for line in done:
        print(f"  {line}")
    print()
    print("Measure adoption anytime:  ctxpack session stats")
    print()
    _print_restart_warning()
    return 0


if __name__ == "__main__":
    sys.exit(main())
