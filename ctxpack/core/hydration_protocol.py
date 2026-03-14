"""LLM-as-Router protocol for progressive hydration.

Builds ultra-lean system prompts that list available sections and instruct
the LLM to call ctx/hydrate when it needs detail. The LLM IS the query
router — no TF-IDF, no embeddings, no statefulness needed.

The L3 prompt is a DIRECTORY INDEX, not a document. It contains:
  - Entity names + primary identifiers (one line each)
  - Section names available for hydration
  - Tool-use instructions

Target: <500 BPE tokens regardless of corpus size.
"""

from __future__ import annotations

from typing import Any, Optional

from .hydrator import list_sections
from .model import CTXDocument, Section, KeyValue
from .serializer import serialize


def build_system_prompt(
    doc: CTXDocument,
    *,
    hydration_instructions: bool = True,
) -> str:
    """Build an ultra-lean system prompt for LLM-as-router hydration.

    This is a DIRECTORY INDEX — entity names + IDs only. No descriptions,
    no field details, no relationship trees. The LLM reads the index,
    decides which section to hydrate, and calls ctx/hydrate.

    Args:
        doc: The CTXDocument (L2) to build an index from.
        hydration_instructions: Include tool-use instructions for ctx/hydrate.

    Returns:
        System prompt text (<500 BPE tokens target).
    """
    parts: list[str] = []

    # Header — minimal
    parts.append("You have a domain knowledge base. Use ctx/hydrate(section=NAME) to retrieve details.")
    parts.append("")

    # Build ultra-lean entity index from the document
    sections = list_sections(doc)
    entity_sections = []
    other_sections = []

    for s in sections:
        if s["name"].startswith("ENTITY-"):
            entity_sections.append(s)
        else:
            other_sections.append(s)

    # Entity directory — one line per entity with identifier if available
    if entity_sections:
        parts.append("Entities:")
        for s in entity_sections:
            name = s["name"]
            # Extract identifier from the section's first IDENTIFIER KV
            identifier = _extract_identifier(doc, name)
            if identifier:
                parts.append(f"  {name} (id: {identifier})")
            else:
                parts.append(f"  {name}")

    # Other sections — just names
    if other_sections:
        parts.append("Other sections:")
        for s in other_sections:
            parts.append(f"  {s['name']}")

    parts.append("")

    # Hydration instructions — concise
    if hydration_instructions:
        parts.append("To answer questions, hydrate the relevant section(s):")
        parts.append('  ctx/hydrate(section="ENTITY-X")')
        parts.append("Only hydrate what you need. Say 'not found' if no section is relevant.")

    return "\n".join(parts)


def _extract_identifier(doc: CTXDocument, section_name: str) -> str:
    """Extract the IDENTIFIER value from a section, if present."""
    for elem in doc.body:
        if isinstance(elem, Section) and elem.name == section_name:
            for child in elem.children:
                if isinstance(child, KeyValue) and child.key == "IDENTIFIER":
                    return child.value
    return ""


def build_hydration_tool_schema() -> dict[str, Any]:
    """Return the MCP tool schema for ctx/hydrate.

    Suitable for injection into system prompts or tool definitions
    when using non-MCP tool-calling interfaces (e.g., OpenAI function calling).
    """
    return {
        "name": "ctx/hydrate",
        "description": (
            "Retrieve detailed sections from the domain knowledge base. "
            "Provide the section name from the domain map to get full details."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "description": (
                        "Section name to hydrate (e.g. 'ENTITY-CUSTOMER'). "
                        "Use comma-separated names for multiple sections."
                    ),
                },
            },
            "required": ["section"],
        },
    }


def build_hydration_tool_schema() -> dict[str, Any]:
    """Return the MCP tool schema for ctx/hydrate.

    Suitable for injection into system prompts or tool definitions
    when using non-MCP tool-calling interfaces (e.g., OpenAI function calling).
    """
    return {
        "name": "ctx/hydrate",
        "description": (
            "Retrieve detailed sections from the domain knowledge base. "
            "Provide the section name from the domain map to get full details."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "description": (
                        "Section name to hydrate (e.g. 'ENTITY-CUSTOMER'). "
                        "Use comma-separated names for multiple sections."
                    ),
                },
            },
            "required": ["section"],
        },
    }
