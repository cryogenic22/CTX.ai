#!/usr/bin/env python
"""CI assertion: one version, three places, and the git tag on tag pushes.

``pyproject.toml`` ``[project].version`` and ``ctxpack.__version__`` must
be identical. When the distribution is installed, its metadata version
must match both. On a tag push (``GITHUB_REF_TYPE=tag`` /
``refs/tags/…``, or ``CTXPACK_GIT_TAG`` for a local check) the tag must
be the same public version. ``v0.5.0-rc1`` and ``0.5.0rc1`` compare equal.

Stdlib only.
"""
from __future__ import annotations

import os
import re
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_PRE = {
    "alpha": "a",
    "beta": "b",
    "rc": "rc",
    "preview": "rc",
    "a": "a",
    "b": "b",
    "c": "rc",
}


def project_version(pyproject_text: str) -> str:
    """The ``[project]`` table's ``version`` string."""
    match = re.search(r"(?ms)^\[project\]\s*(.*?)^\[", pyproject_text)
    block = match.group(1) if match else pyproject_text
    found = re.search(r'(?m)^version\s*=\s*"([^"]+)"', block)
    if not found:
        raise ValueError("pyproject [project].version not found")
    return found.group(1)


def normalize_version(value: str) -> str:
    """PEP 440 public form for tags and release names.

    Strips a leading ``v`` and the optional separator before a pre-release
    (``0.5.0-rc1`` and ``v0.5.0rc1`` both become ``0.5.0rc1``).
    """
    text = value.strip()
    if text[:1] in "vV":
        text = text[1:]

    def _pre(match: re.Match[str]) -> str:
        return _PRE[match.group(1)] + match.group(2)

    return re.sub(
        r"[-_.]?(alpha|beta|rc|preview|a|b|c)[-_.]?(\d+)",
        _pre,
        text,
        count=1,
    )


def git_tag() -> str | None:
    """The tag this CI run is building, if it is a tag push."""
    if os.environ.get("GITHUB_REF_TYPE") == "tag":
        name = os.environ.get("GITHUB_REF_NAME", "").strip()
        if name:
            return name
    ref = os.environ.get("GITHUB_REF", "")
    if ref.startswith("refs/tags/"):
        return ref[len("refs/tags/"):]
    override = os.environ.get("CTXPACK_GIT_TAG", "").strip()
    return override or None


def installed_version() -> str | None:
    try:
        return metadata.version("ctxpack")
    except metadata.PackageNotFoundError:
        return None


def main() -> int:
    pyproject_path = ROOT / "pyproject.toml"
    declared = project_version(pyproject_path.read_text(encoding="utf-8"))
    sys.path.insert(0, str(ROOT))
    import ctxpack
    runtime = ctxpack.__version__
    errors: list[str] = []
    if declared != runtime:
        errors.append(
            f"pyproject version {declared!r} != ctxpack.__version__ {runtime!r}"
        )
    installed = installed_version()
    if installed is None:
        print("version check: distribution not installed; "
              "metadata comparison skipped")
    elif installed != runtime:
        errors.append(
            f"installed metadata {installed!r} != ctxpack.__version__ {runtime!r}"
        )
    tag = git_tag()
    if tag is not None and normalize_version(tag) != normalize_version(runtime):
        errors.append(
            f"git tag {tag!r} != runtime version {runtime!r} "
            f"(normalized {normalize_version(tag)!r} vs "
            f"{normalize_version(runtime)!r})"
        )
    if errors:
        print("version check: FAIL")
        for err in errors:
            print(f"  {err}")
        return 1
    tag_note = f", tag {tag}" if tag else ""
    installed_note = installed if installed is not None else "not-installed"
    print(f"version check: pyproject={declared} runtime={runtime} "
          f"installed={installed_note}{tag_note} (ok)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
