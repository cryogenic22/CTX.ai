"""CLI entry point for ctxpack.

Commands:
  ctxpack parse <file> [--level 1|2|3] [--json]
  ctxpack validate <file> [--level 1|2|3]
  ctxpack fmt <file> [--ascii] [--inplace] [--natural-language]
  ctxpack pack <corpus-dir> [-o output.ctx] [--domain X] [--scope X] [--author X] [--ascii] [--validate] [--natural-language]
  ctxpack eval [--golden-set PATH] [--skip-fidelity] [--skip-latency] [--skip-human] [--output PATH]
  ctxpack bench [--sizes 1000,5000,10000] [--iterations 10] [--json]
  ctxpack telemetry [path] [--json]
"""

from __future__ import annotations

import argparse
import io
import os
import sys

from ..core.errors import DiagnosticLevel, ParseError
from ..core.json_export import to_json
from ..core.parser import parse
from ..core.serializer import serialize
from ..core.validator import validate


def main(argv: list[str] | None = None) -> int:
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


if __name__ == "__main__":
    sys.exit(main())
