# `ctxpack verify` in CI

`ctxpack verify` checks a pull request range against the session ledger
and an optional task contract. The default is report-only: the process
exits 0 unless a finding code is listed in `--block`, in
`ctxpack.toml` under `[verify] block`, or in the contract's
`blocking_codes`.

JSON output uses sorted keys and `\n` newlines. The same range, body,
contract, and ledger produce the same bytes on every operating system.

```yaml
- name: Ledger and contract check
  run: |
    git fetch --no-tags origin "${{ github.event.pull_request.base.sha }}"
    python - <<'PY'
    import os
    from pathlib import Path
    Path("pr_body.md").write_text(os.environ["PR_BODY"], encoding="utf-8")
    PY
    ctxpack verify \
      --range "${{ github.event.pull_request.base.sha }}..${{ github.event.pull_request.head.sha }}" \
      --pr-body pr_body.md \
      --format json
  env:
    PR_BODY: ${{ github.event.pull_request.body }}
```

To fail the job on selected codes, add `--block UNRECORDED_MARKER,CONTRACT_RULE_VIOLATION`
or commit a `ctxpack.toml`:

```toml
[verify]
block = ["UNRECORDED_MARKER", "CONTRACT_RULE_VIOLATION"]
```

A task contract (`--contract path.json` or `.toml`) adds path, version
pin, vocabulary, flag, attestation, test-evidence, verifier-evidence,
and one-way-path checks. See `ctxpack.agent.contract.TaskContract`.
The optional `ctxpack[jev]` adapter is advisory only and is not part
of this exit code.

## Verifier evidence

`require_verifier_evidence = true` asks the PR body for an unfenced
attestation. The label is case-insensitive. A passing status is
`pass`, `ok`, `passed`, or `green`. Accepted forms:

```text
verifier: <command> | pass | <sha>
verifier: <command> pass @ <sha>
verifier: <command> pass (<sha>)
verifier: pass <sha>
verifier-cmd: <command>
verifier-result: pass
```

A SHA is optional. When one is present it must be at least 7 hex
characters and a prefix of the head commit. When `verifier_command`
is set, that command or label must appear on the attestation. Lines
that still contain `<` or `>` are template placeholders and are not
attestations. A miss emits `VERIFIER_EVIDENCE_MISSING` with severity
`error`. The code blocks only when it is in the blocking list.
Omitting the PR body fails closed (the finding is `missing`).

## One-way paths

`one_way_paths` is a list of globs for irreversible surfaces
(`migrations/**`, `schema/**`, `**/drop_*.sql`). `ctxpack verify`
compares them to the merge-base diff. A match emits
`ONE_WAY_PATH_TOUCHED` with severity `error`.

That code blocks even in report-only mode (an empty blocking list, or
a list that names other codes). It stops blocking only when the PR
body has both an unfenced `one-way-ack: <reason>` line and a
`verified-sha:` of at least 7 hex characters that prefixes head. The
finding stays in the report; the acknowledgement removes the block.

Globs strip one leading `./` and nothing else. `.github/**` matches
`.github/workflows/ci.yml` and does not match `github/x.yml`.

`ctxpack onboard` creates or appends this block to
`.github/pull_request_template.md`. A re-run sees the markers and
does not duplicate them or replace other template text:

```markdown
<!-- ctxpack:attestation:start -->
verified-sha: <7+ char head sha>
verifier: <command> | pass | <head sha>
<!-- ctxpack:attestation:end -->
```
