"""CLI entry point for ctxpack.

Commands:
  ctxpack parse <file> [--level 1|2|3] [--json]
  ctxpack validate <file> [--level 1|2|3]
  ctxpack fmt <file> [--ascii] [--inplace]
  ctxpack pack <corpus-dir> [-o output.ctx] [--domain X] [--scope X] [--author X] [--ascii] [--validate]
  ctxpack eval [--golden-set PATH] [--skip-fidelity] [--skip-latency] [--skip-human] [--output PATH]
"""

from __future__ import annotations

import argparse
import io
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
    output = serialize(doc, ascii_mode=args.ascii)

    if args.inplace:
        with open(args.file, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Formatted {args.file}")
    else:
        print(output, end="")

    return 0


def _cmd_pack(args: argparse.Namespace) -> int:
    from ..core.packer import pack

    result = pack(
        args.corpus_dir,
        domain=args.domain,
        scope=args.scope,
        author=args.author,
    )

    output_text = serialize(result.document, ascii_mode=args.ascii)

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
        print(f"  Entities: {result.entity_count}")
        print(f"  Source tokens: ~{result.source_token_count}")
        print(f"  Warnings: {result.warning_count}")
    else:
        print(output_text, end="")

    return 0


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
        print(f"  {name:20s}  tokens={tokens:>6}  ratio={ratio:>6}  cost={cost}  fidelity={fidelity}")

    if "conflict_detection" in results:
        cd = results["conflict_detection"]
        print(f"\n  Conflict detection: planted={cd['planted']} found={cd['found']} "
              f"P={cd['precision']} R={cd['recall']}")

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
