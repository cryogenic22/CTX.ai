#!/usr/bin/env python
"""Assert one version across pyproject, ctxpack.__version__, and tags.

``pyproject.toml`` ``[project].version`` and the ``__version__`` assignment
in ``ctxpack/__init__.py`` must be identical. This script parses both as
text (it does not import the package), so a clean wheel's interpreter can
run it against the source tree.

``--installed`` also requires ``importlib.metadata.version("ctxpack")``
for the interpreter running this script to match. Use that from the
environment that just installed the tree or the wheel.

On a tag checkout (``GITHUB_REF=refs/tags/<tag>``, or ``--tag``), the tag
must name that same version. A single leading ``v`` is accepted
(``v0.5.0rc1`` matches ``0.5.0rc1``).

``--wheel PATH`` checks the built wheel contains
``ctxpack/schemas/telemetry-events.schema.json``. The loader opens that
file from the installed package; a wheel that omits it is a broken
release artifact.
"""

from __future__ import annotations

import argparse
import ast
import importlib.metadata
import os
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_SUFFIX = "ctxpack/schemas/telemetry-events.schema.json"


def _pyproject_version(text: str) -> str:
    """The ``[project]`` version, not a later tool-table key."""
    match = re.search(r"(?ms)^\[project\]\s.*?^version\s*=\s*\"([^\"]+)\"", text)
    if match is None:
        raise SystemExit("pyproject.toml [project] version was not found")
    return match.group(1)


def _source_version(text: str) -> str:
    module = ast.parse(text)
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "__version__":
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    return node.value.value
    raise SystemExit("ctxpack/__init__.py has no __version__ string assignment")


def _tag_version(tag: str, version: str) -> bool:
    bare = tag[1:] if tag.startswith("v") else tag
    return bare == version


def _check_wheel(path: Path) -> None:
    if not path.is_file():
        raise SystemExit(f"wheel not found: {path}")
    with zipfile.ZipFile(path) as zf:
        names = [n.replace("\\", "/") for n in zf.namelist()]
    if not any(n.endswith(SCHEMA_SUFFIX) for n in names):
        raise SystemExit(
            f"{path.name} does not contain {SCHEMA_SUFFIX} "
            "(setuptools package-data omitted the telemetry schema)"
        )
    print(f"wheel schema OK: {path.name} contains {SCHEMA_SUFFIX}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--installed",
        action="store_true",
        help="also require importlib.metadata version('ctxpack') to match",
    )
    parser.add_argument(
        "--tag",
        default="",
        help="tag to check (default: GITHUB_REF when it is refs/tags/*)",
    )
    parser.add_argument(
        "--wheel",
        action="append",
        default=[],
        help="wheel path that must package the telemetry schema (repeatable)",
    )
    args = parser.parse_args(argv)

    pyproject = _pyproject_version((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    source = _source_version((ROOT / "ctxpack" / "__init__.py").read_text(encoding="utf-8"))
    print(f"version: pyproject={pyproject} ctxpack.__version__={source}")
    if pyproject != source:
        print(
            f"VERSION FAIL: pyproject {pyproject!r} != ctxpack.__version__ {source!r}",
            file=sys.stderr,
        )
        return 1

    if args.installed:
        try:
            installed = importlib.metadata.version("ctxpack")
        except importlib.metadata.PackageNotFoundError:
            print("VERSION FAIL: ctxpack is not installed in this interpreter", file=sys.stderr)
            return 1
        print(f"version: installed={installed}")
        if installed != source:
            print(
                f"VERSION FAIL: installed metadata {installed!r} != {source!r}",
                file=sys.stderr,
            )
            return 1

    tag = args.tag
    if not tag:
        ref = os.environ.get("GITHUB_REF", "")
        if ref.startswith("refs/tags/"):
            tag = ref[len("refs/tags/"):]
    if tag:
        print(f"version: tag={tag}")
        if not _tag_version(tag, source):
            print(
                f"VERSION FAIL: tag {tag!r} does not match version {source!r} "
                "(optional leading 'v' only)",
                file=sys.stderr,
            )
            return 1

    for wheel in args.wheel:
        _check_wheel(Path(wheel))

    print("version check OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
