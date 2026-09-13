# Deployment notes — international rollout (frozen calibration sample)

This document is a frozen calibration fixture. It mirrors the kind of
prose the estimator meets in real repositories: English-dominant
technical writing with embedded non-ASCII content — contributor names,
localized strings, paths, emoji, and typographic punctuation. Do not
edit it: its cl100k token count is committed alongside in
`expected_cl100k.json`, and any change must re-measure and re-commit
both together.

## Contributors and reviewers

The localization review was led by Zoë Núñez and José Müller, with
sign-off from Søren Ångström and François Lefèvre. The Kyiv team
(Олена Шевченко, Дмитро Коваль) validated the Cyrillic rendering path,
and the Tokyo office confirmed the CJK line-breaking behaviour. Their
verdict, verbatim: 「改行処理は問題ありません。全角文字も正しく計測されました。」
The Beijing QA pass added: 中文界面的所有字符串均已通过验证。

## Localized UI strings under test

- Greeting banner: "Willkommen zurück, Ihre Sitzung wurde
  wiederhergestellt" (de-DE)
- Error toast: «Не удалось сохранить файл — повторите попытку» (ru-RU)
- Confirmation dialog: "¿Seguro que quieres eliminar el archivo?"
  (es-ES)
- Status chip: 保存済み (ja-JP) and 已保存 (zh-CN)
- Currency formats: €1.234,56 — ¥12,345 — £999.99 — ₹1,00,000

## Symbols, emoji, and punctuation coverage

Status legend: ✅ passed, ⚠️ flaky, ❌ failed, 🚀 shipped, 🔥 hotfix.
Math notation appears in the capacity model — λ ≈ 0.73, σ² ≤ 1.5,
Δt → 0, and the invariant ∀x ∈ S: f(x) ≠ ∅ — as well as arrows (→, ⇒),
dashes (– and —), curly quotes ("like these" and 'these'), and the
ellipsis character… The path fixtures include
`C:\Users\Müller\Документы\プロジェクト\readme.md` and
`/home/zoë/工作/notes-№42.txt`.

## Why this mix

Pure non-Latin text is out of the estimator's calibration domain — a
chars-per-token divisor tuned on English-dominant artifacts
underestimates CJK-heavy content badly, and that limitation is
disclosed wherever the label appears. What the estimator MUST handle
without blowing past the kill threshold is exactly this file: mostly
English prose, salted with the multilingual fragments, emoji, and
typographic characters that real repositories accumulate. The
remainder of this section pads the sample toward a realistic length
with ordinary operational prose: the rollout proceeds region by
region, canary first, with automatic rollback armed on error-budget
burn; dashboards track p95 latency, apdex, and the localization
fallback rate; a failed canary freezes promotion and pages the on-call
rotation; translations are pulled from the TMS nightly, validated
against the string schema, and diffed against the previous bundle
before publish; screenshots are re-captured for every locale whose
strings changed, and reviewers confirm truncation, bidi behaviour, and
font fallback on the four reference devices before the bundle is
promoted to production.
