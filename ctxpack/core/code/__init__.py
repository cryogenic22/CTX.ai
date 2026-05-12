"""Code-packer producer.

Sibling to ``ctxpack.core.packer`` (the prose-domain producer). Same
``IREntity`` / ``IRField`` / hydrator / ContextGuard / telemetry, but
the input is source code instead of structured prose. See
``paper/code-packer-v0-rfc.md`` for the design.

Empty at CP-001 (scaffold only). CP-002 lands the tree-sitter parser
wrapper; CP-003+ build the symbol extractor, ranker, and MCP surface
on top.
"""
