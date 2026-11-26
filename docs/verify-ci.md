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
pin, vocabulary, flag, attestation, and test-evidence checks. See
`ctxpack.agent.contract.TaskContract`. The optional `ctxpack[jev]`
adapter is advisory only and is not part of this exit code.
