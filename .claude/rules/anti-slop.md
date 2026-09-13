---
description: Anti-drift rules — known utilities, patterns, imports
alwaysApply: true
---
# Known Utilities — DO NOT recreate

Before writing new helpers, check these existing utilities:

- `ctxpack/core/artifact_privacy.py`: scan_artifact_string, artifact_categories, is_safe_identity (THE strict machine-path/owner-identity matcher — do NOT write a second one; scorecard + fork_cluster both use this)
- `ctxpack/core/confidence.py`: ConfidenceRecord, ConfidenceTracker
- `ctxpack/core/diff.py`: DiffEntry, DiffResult, diff_documents, format_diff
- `ctxpack/core/entity_graph.py`: EntityGraph
- `ctxpack/core/errors.py`: Span, DiagnosticLevel, Diagnostic, ParseError
- `ctxpack/core/factid.py`: FactBasis, SourceRole, Authority, derive_authority (+2 more)
- `ctxpack/core/hydration_protocol.py`: build_system_prompt, build_hydration_tool_schema, build_hydration_tool_schema
- `ctxpack/core/hydrator.py`: HydrationResult, hydrate_by_name, hydrate_by_query, list_sections (+1 more)
- `ctxpack/core/json_export.py`: to_dict, to_json
- `ctxpack/core/layers.py`: ContextLayer
- `ctxpack/core/model.py`: Layer, OperatorKind, PlainLine, KeyValue (+9 more)
- `ctxpack/core/operators.py`: extract_operators, extract_crossrefs, extract_operators_from_doc
- `ctxpack/core/parser.py`: parse
- `ctxpack/core/rank.py`: resolve_policy, load_events, prior_for, fold_events
- `ctxpack/core/redaction.py`: redact, scan, redact_tree
- `ctxpack/core/serializer.py`: serialize, serialize_iter, serialize_section
- `ctxpack/core/states.py`: Lifecycle, Freshness, Delivery, describes_use (+5 more)
- `ctxpack/core/supersession_dag.py`: SupersessionEdge, Conflict, SupersessionGraph, edges_from_events (+2 more)
- `ctxpack/core/telemetry.py`: HydrationEvent, TelemetryLog
- `ctxpack/core/tokens.py`: estimator_label, estimate_tokens
- `ctxpack/core/validator.py`: validate

# Route Pattern

New route files MUST follow this structure:

  File: tests/code/fixtures/py_fastapi_min/app.py

# Common Imports

Most-used packages (prefer these over new dependencies):

- `pytest` (81 files)
- `time` (36 files)
- `ctxpack.core.serializer` (23 files)
- `ctxpack.core.packer.ir` (22 files)
- `ctxpack.core.model` (21 files)
- `hashlib` (20 files)
- `ctxpack.agent.checkpoint` (17 files)
- `ctxpack.core.packer` (16 files)
- `tempfile` (14 files)
- `ctxpack.benchmarks.metrics.fidelity` (14 files)
