# ctxpack Constraints and Invariants

## Immutable AST

The CTXDocument and all child nodes (Header, Section, KeyValue, etc.) are frozen dataclasses.
Once parsed, the AST cannot be modified. Any transformation produces a new AST.

## No LLM in Packer

The packer pipeline is entirely deterministic with zero LLM or ML dependencies.
This includes L3 gist generation, which uses algorithmic extraction rather than summarization.
The only LLM usage is in the eval framework for fidelity measurement (LLM-as-judge).

## Deterministic Output

Given the same corpus directory and configuration, the packer always produces identical .ctx output.
This enables reproducible builds and diff-based versioning.

## File-Based Codec

ctxpack is a file-based compression codec. It processes static file corpora from disk.
It has no database, no REST API, no streaming ingestion, and no real-time processing capabilities.
Input is a directory of YAML, Markdown, and JSON files. Output is .ctx text files.

## License

ctxpack is released under Apache-2.0 (open-core model).

## Parser Scope

The .ctx parser handles only .ctx format files — line-oriented, section-based text.
It cannot parse arbitrary Python files, YAML files, or other formats.
The packer has separate parsers (yaml_parser, md_parser, json_parser) for input formats.
