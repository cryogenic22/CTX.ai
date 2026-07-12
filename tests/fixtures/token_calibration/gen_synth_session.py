"""One-off generator: synthetic OWN-REPO session ledger for token
calibration (E-6A follow-through: the frozen real-session fixture
carried raw session history and personal home paths). Deterministic
(seeded); content is fully fabricated — a fictional 'lattice-docs'
documentation-tooling repo owned by a fictional 'dev' user. Mimics the
entity mix/density of a real .ctx session ledger so the ctx-kind
chars/3 estimator calibration stays on representative content.

Output is written next to this file (never an absolute machine path).
"""
import hashlib
import os
import random

import tiktoken

random.seed(20260713)

REPO = r"C:\Users\dev\Projects\lattice-docs"
POSIX = "/c/Users/dev/Projects/lattice-docs"

MODULES = ["renderer", "sitemap", "linkcheck", "frontmatter", "search",
           "toc", "redirects", "snippets", "theme", "publish"]
FILES = ["build.py", "conf.py", "pipeline/render.py", "pipeline/index.py",
         "tests/test_linkcheck.py", "tests/test_redirects.py", "Makefile",
         "docs/authoring.md", "themes/base/layout.html", "ops/deploy.yaml"]
VERBS = ["render", "index", "pin", "redirect", "lint", "publish",
         "invalidate", "snapshot", "rebuild", "verify"]
REQS = [
    "the search index misses every page added after the sitemap split, "
    "figure out why the crawler stops at the old boundary",
    "broken-link checks pass locally but fail in ci, make the base url "
    "handling identical in both",
    "add a redirects table so renamed pages keep their inbound links "
    "instead of 404ing",
    "the theme rebuild takes eleven minutes, cache the unchanged "
    "templates and get it under two",
    "frontmatter dates render in three different formats across the "
    "site, normalize them at parse time not in the templates",
    "publishing overwrote the previous snapshot before verification "
    "passed, make the swap atomic",
    "code snippets drift from the source files they quote, pull them at "
    "build time with line anchors",
    "the toc generator double-nests when a heading skips a level, fix "
    "the level clamp",
]
DECISIONS = [
    "Decision: snippets are pulled at build time by line anchor instead "
    "of pasted, because every pasted block in the audit had drifted from "
    "its source — the anchor fails the build when the source moves.",
    "Decision: the publish swap is two-phase (stage + atomic symlink "
    "flip) because a half-copied deploy served mixed versions for nine "
    "minutes — verification gates the flip, never the copy.",
    "Decision: redirects live in one committed table validated at build, "
    "not in server config, because the ops copy silently diverged and "
    "renamed pages 404ed for a week.",
    "Decision: the link checker resolves against the STAGED site root, "
    "not the production host, because ci and local disagreed only on the "
    "base url — same tree, same verdict, everywhere.",
    "Decision: template cache keys are content hashes not mtimes, "
    "because the ci checkout resets mtimes and forced full rebuilds on "
    "every run.",
    "Decision: frontmatter dates normalize at parse time to a single "
    "ISO form because template-side formatting produced three variants "
    "and broke the sitemap lastmod ordering.",
]
ERRORS = [
    "Exit code 1 FAILED tests/test_linkcheck.py::test_staged_root - "
    "AssertionError: 404 for /guides/quickstart/ under base /preview/",
    "jinja2.exceptions.TemplateNotFound: partials/nav_v2.html — referenced "
    "by themes/base/layout.html line 44 after the theme split",
    "Exit code 2 make: *** [Makefile:29: linkcheck] Error 1 — 17 broken "
    "internal links after the sitemap split",
    "FileNotFoundError: snippets/anchors.json missing — snippet pull ran "
    "before the index step in the parallel build",
]
CONSTRAINTS = [
    "Constraint: the production symlink flips only after linkcheck and "
    "search-index verification both pass on the staged tree.",
    "Constraint: the redirects table is append-only — a removed redirect "
    "needs a linked deprecation note in the same change.",
    "Constraint: never edit rendered output in place; every fix goes "
    "through a source rebuild, the artifact tree is disposable.",
]


def sha():
    return hashlib.sha1(str(random.random()).encode()).hexdigest()[:random.choice([7, 7, 12])]


def eid():
    return hashlib.sha1(str(random.random()).encode()).hexdigest()[:8].upper()


blocks = []
turn = 0


def add(kind, body_lines, factid=False):
    global turn
    turn += random.randint(1, 9)
    lines = [f"±ENTITY-{kind}-{eid()}"] + body_lines
    if factid:
        lines += [f"FACT-ID:{hashlib.sha1(str(random.random()).encode()).hexdigest()[:16]}",
                  f"BASIS:{random.choice(['marker_stated', 'structural', 'literal_extractor'])}",
                  "STATUS:current", "EXTRACTOR:tp/1.1"]
    lines += [f"TURN:{turn}", f"SRC:session:3c9d41aa#turn{turn}"]
    blocks.append("\n".join(lines))


for round_ in range(3):
    add("USER-REQUEST", [
        f"REQUEST:{random.choice(REQS)} — context: the docs team hit this "
        f"during the release-notes push and worked around it by hand, so "
        f"fix the pipeline before the next release train"],
        factid=True)
    for _ in range(4):
        mod, f = random.choice(MODULES), random.choice(FILES)
        cmd = random.choice([
            f"cd {POSIX} && python -m pytest tests/test_{mod}.py -q 2>&1 | tail -8; echo exit: $?",
            f"cd {POSIX} && grep -nE 'def (render|resolve|flip)|redirect|anchor' {f} | head -20",
            f"R=\"{POSIX}\" git -C \"$R\" log --oneline -12 -- {mod}/ && git -C \"$R\" diff --stat HEAD~3",
            f"cd {POSIX} && python build.py --stage-only --module {mod} 2>&1 | head -15",
            f"cd {POSIX} && make linkcheck && echo OK || echo BROKEN",
        ])
        add(f"TOOL-BASH-{random.randint(1, 99):04d}"[:14],
            [f"RAN:{random.choice(VERBS)} {mod} check", f"COMMAND:{cmd}"])
    for _ in range(2):
        val = random.choice([
            REPO + "\\" + random.choice(FILES).replace("/", "\\"),
            sha(),
            f"{random.randint(0, 4)}.{random.randint(0, 12)}.{random.randint(0, 30)}",
            f"/guides/section-{random.randint(1, 9)}/",
            f"https://docs.example.test/preview/{random.randint(100, 999)}/",
        ])
        kind = "path" if ("\\" in val or val.startswith("/")) else (
            "url" if val.startswith("http") else (
                "version" if val.count(".") == 2 else "git_sha"))
        add("LITERAL", [f"VALUE:{val}", f"KIND:{kind}"], factid=True)
    add("DECISION", [f"DECISION:{random.choice(DECISIONS)}"], factid=True)
    add("DECISION", [
        f"DECISION:{random.choice(DECISIONS)} The alternative we walked "
        f"away from was {random.choice(VERBS)}ing the {random.choice(MODULES)} "
        f"module first, which looked cheaper but left the staged tree "
        f"unverified through the release train."],
        factid=True)
    if round_ % 2 == 0:
        add("ERROR", [f"MESSAGE:{random.choice(ERRORS)}"], factid=True)
    add("CONSTRAINT", [f"CONSTRAINT:{random.choice(CONSTRAINTS)}"],
        factid=True)
    add("TASK", [f"TASK:{random.choice(VERBS).capitalize()} "
                 f"{random.choice(MODULES)} per the release retro, then "
                 f"update the authoring guide section that describes the "
                 f"staged-preview flow so writers stop publishing from "
                 f"local trees"])

header = ("§CTX v1.0 L2 DOMAIN:session-3c9d41aa\n"
          "COMPRESSED:2026-07-12 SOURCE_TOKENS:~3300 CTX_TOKENS:~3400 "
          "RATIO:~1.0x\n\n")
text = header + "\n".join(blocks) + "\n"

enc = tiktoken.get_encoding("cl100k_base")
tokens = len(enc.encode(text))
est = round(len(text) / 3)
print(f"chars={len(text)} cl100k={tokens} chars/3={est} "
      f"err={100 * (est - tokens) / tokens:+.2f}%")

out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "ctx_session_frozen.ctx")
with open(out, "w", encoding="utf-8", newline="\n") as fh:
    fh.write(text)
raw = open(out, "rb").read()
print("sha256:", hashlib.sha256(raw).hexdigest())
print("wrote", out)
