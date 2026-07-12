"""One-off generator: synthetic unrelated-repo session ledger for token
calibration (Q2-4 privacy fix). Deterministic (seeded); content is fully
fabricated — a fictional 'meridian-etl' data-pipeline repo owned by a
fictional 'dev' user. Mimics the entity mix/density of a real .ctx
session ledger so the ctx-kind chars/3 estimator calibration stays on
representative content.
"""
import hashlib
import os
import random

import tiktoken

random.seed(20260712)

REPO = r"C:\Users\dev\Projects\meridian-etl"
POSIX = "/c/Users/dev/Projects/meridian-etl"

MODULES = ["ingest", "dedupe", "schema_guard", "loader", "backfill",
           "watermark", "quarantine", "manifest", "partitioner", "vacuum"]
FILES = ["pipeline.py", "config.py", "runners/batch.py", "runners/stream.py",
         "tests/test_watermark.py", "tests/test_dedupe.py", "Makefile",
         "docs/runbook.md", "schemas/orders_v3.json", "ops/alerts.yaml"]
VERBS = ["wire", "gate", "backfill", "quarantine", "re-partition", "pin",
         "de-dupe", "checkpoint", "rotate", "vacuum"]
REQS = [
    "can you check why the nightly backfill is double counting orders "
    "from the eu region and fix the dedupe key",
    "add a schema drift gate so a renamed column fails loudly instead of "
    "silently nulling the field",
    "the watermark file got corrupted after the spot instance died, make "
    "recovery not depend on it",
    "write a runbook section for on-call covering quarantine replay and "
    "the manifest repair script",
    "why does the stream runner fall behind every monday morning, look at "
    "the partition sizes",
    "make the loader idempotent so a retried batch never inserts twice",
    "tighten the alerts so we page on lag over twenty minutes not on "
    "every transient spike",
    "migrate the orders schema to v3 without breaking the two downstream "
    "consumers that still read v2",
]
DECISIONS = [
    "Decision: dedupe on (order_id, region, event_ts) instead of the "
    "composite hash because the hash silently collided on re-exported "
    "batches — the tuple is stable across re-exports.",
    "Decision: the watermark moves to a two-phase commit (tmp + atomic "
    "rename) because a torn write during spot reclaim corrupted it — "
    "recovery now replays from the manifest, never trusts a partial file.",
    "Decision: schema drift fails the batch at ingest, not at load, "
    "because a nulled column that reaches the warehouse is unrecoverable "
    "without a backfill — loud beats late.",
    "Decision: quarantine replay is manual-only with a --confirm flag "
    "because an automated replay loop re-quarantined the same poison "
    "batch 40 times overnight.",
    "Decision: partitions are sized by row count not by day because "
    "monday batches are 6x weekend batches and the stream runner starves "
    "on the skew.",
    "Decision: the loader writes an idempotency ledger row before the "
    "insert because retry-after-timeout was the only source of "
    "duplicates in the incident review.",
]
ERRORS = [
    "Exit code 1 FAILED tests/test_watermark.py::test_recovery_replays_"
    "manifest - AssertionError: watermark 2026-03-14T02:00:00 != manifest "
    "head 2026-03-14T02:15:00",
    "psycopg2.errors.UniqueViolation: duplicate key value violates unique "
    "constraint orders_pkey DETAIL: Key (order_id)=(ORD-88213-EU) already "
    "exists.",
    "Exit code 2 make: *** [Makefile:41: schema-check] Error 1 — column "
    "customer_ref renamed to customer_id in orders_v3.json",
    "TimeoutError: stream runner heartbeat missed 3 intervals; last "
    "offset 1842273 partition orders-eu-7",
]
CONSTRAINTS = [
    "Constraint: never mutate a quarantined batch in place — replay "
    "copies into a fresh staging table, the original is evidence.",
    "Constraint: the idempotency ledger is append-only; a delete there "
    "needs a signed-off incident ticket.",
    "Constraint: schema changes ship behind a dual-read window of at "
    "least one full weekly cycle.",
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
    lines += [f"TURN:{turn}", f"SRC:session:7f3a2b9e#turn{turn}"]
    blocks.append("\n".join(lines))


for round_ in range(9):
    add("USER-REQUEST", [
        f"REQUEST:{random.choice(REQS)} — context: this bit us during the "
        f"last weekly close and the finance team noticed before we did, "
        f"so treat the fix as the priority over the refactor work"],
        factid=True)
    for _ in range(4):
        mod, f = random.choice(MODULES), random.choice(FILES)
        cmd = random.choice([
            f"cd {POSIX} && python -m pytest tests/test_{mod}.py -q 2>&1 | tail -8; echo exit: $?",
            f"cd {POSIX} && grep -nE 'def (load|replay|commit)|watermark|manifest' {f} | head -20",
            f"R=\"{POSIX}\" git -C \"$R\" log --oneline -12 -- {mod}/ && git -C \"$R\" diff --stat HEAD~3",
            f"cd {POSIX} && python ops/manifest_repair.py --dry-run --partition orders-eu-{random.randint(0, 9)} 2>&1 | head -15",
            f"cd {POSIX} && make schema-check && echo OK || echo DRIFT",
        ])
        add(f"TOOL-BASH-{random.randint(1, 99):04d}"[:14],
            [f"RAN:{random.choice(VERBS)} {mod} check", f"COMMAND:{cmd}"])
    for _ in range(2):
        val = random.choice([
            REPO + "\\" + random.choice(FILES).replace("/", "\\"),
            sha(),
            f"{random.randint(0, 4)}.{random.randint(0, 12)}.{random.randint(0, 30)}",
            f"orders-eu-{random.randint(0, 9)}",
            f"s3://meridian-lake/curated/orders/v{random.randint(1, 3)}/dt=2026-0{random.randint(1, 6)}-1{random.randint(0, 9)}",
        ])
        kind = "path" if ("\\" in val or val.startswith("s3://")) else (
            "version" if val.count(".") == 2 else "git_sha")
        add("LITERAL", [f"VALUE:{val}", f"KIND:{kind}"], factid=True)
    add("DECISION", [f"DECISION:{random.choice(DECISIONS)}"], factid=True)
    add("DECISION", [
        f"DECISION:{random.choice(DECISIONS)} The alternative we walked "
        f"away from was {random.choice(VERBS)}ing the {random.choice(MODULES)} "
        f"module first, which looked cheaper but would have left the "
        f"on-call runbook out of date through the weekly cycle."],
        factid=True)
    if round_ % 2 == 0:
        add("ERROR", [f"MESSAGE:{random.choice(ERRORS)}"], factid=True)
    if round_ % 3 == 0:
        add("CONSTRAINT", [f"CONSTRAINT:{random.choice(CONSTRAINTS)}"],
            factid=True)
    add("TASK", [f"TASK:{random.choice(VERBS).capitalize()} "
                 f"{random.choice(MODULES)} per incident review, then "
                 f"update the runbook section that describes the manual "
                 f"replay steps so on-call does not have to read the "
                 f"source to recover"])

header = ("§CTX v1.0 L2 DOMAIN:session-7f3a2b9e\n"
          "COMPRESSED:2026-07-12 SOURCE_TOKENS:~3400 CTX_TOKENS:~4600 "
          "RATIO:~0.9x\n\n")
text = header + "\n".join(blocks) + "\n"

enc = tiktoken.get_encoding("cl100k_base")
tokens = len(enc.encode(text))
est = round(len(text) / 3)
print(f"chars={len(text)} cl100k={tokens} chars/3={est} "
      f"err={100 * (est - tokens) / tokens:+.2f}%")

# output lands next to this file — never an absolute machine path
# (re-review finding 4)
out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "ctx_cohort_synth_frozen.ctx")
with open(out, "w", encoding="utf-8", newline="\n") as fh:
    fh.write(text)
raw = open(out, "rb").read()
print("sha256:", hashlib.sha256(raw).hexdigest())
print("wrote", out)
