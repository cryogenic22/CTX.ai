"""Twilio Video API Spec corpus download and preprocessing.

Fetches the Twilio Video v1 OpenAPI spec from GitHub and converts
resource definitions into Markdown entity files for ctxpack packing.

Source: https://raw.githubusercontent.com/twilio/twilio-oai/main/spec/json/twilio_video_v1.json
"""

from __future__ import annotations

import json
import os
import re
import sys
import textwrap
import urllib.request
from typing import Any

TWILIO_SPEC_URL = (
    "https://raw.githubusercontent.com/twilio/twilio-oai/main/spec/json/twilio_video_v1.json"
)


def fetch_openapi_spec() -> dict[str, Any] | None:
    """Fetch the Twilio Video v1 OpenAPI spec JSON."""
    try:
        req = urllib.request.Request(
            TWILIO_SPEC_URL,
            headers={"User-Agent": "ctxpack-eval/0.3"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  WARNING: Failed to fetch Twilio spec: {e}")
        return None


def _extract_resource_name(path: str) -> str:
    """Extract resource name from an OpenAPI path.

    Example: /v1/Rooms/{RoomSid}/Participants → Participants
    """
    parts = [p for p in path.split("/") if p and not p.startswith("{") and p != "v1"]
    return parts[-1] if parts else "Unknown"


def _extract_sid_pattern(properties: dict[str, Any]) -> str | None:
    """Extract SID pattern from a 'sid' property description."""
    sid_prop = properties.get("sid", {})
    desc = sid_prop.get("description", "")
    # Look for patterns like "RM + 32 hex chars"
    pattern_match = re.search(r"[A-Z]{2}\d{0,2}", desc)
    if pattern_match:
        return pattern_match.group()
    return None


def _schema_type_str(prop: dict[str, Any]) -> str:
    """Convert a JSON Schema property to a readable type string."""
    t = prop.get("type", "")
    fmt = prop.get("format", "")
    enum = prop.get("enum", [])

    if enum:
        return f"enum [{', '.join(str(e) for e in enum)}]"
    if fmt:
        return f"{t} ({fmt})"
    if t:
        return t
    # $ref
    ref = prop.get("$ref", "")
    if ref:
        return ref.split("/")[-1]
    return "any"


def _group_paths_by_resource(paths: dict[str, Any]) -> dict[str, list[tuple[str, str, dict]]]:
    """Group paths by their resource name.

    Returns dict of resource_name → [(path, method, operation_dict), ...]
    """
    groups: dict[str, list[tuple[str, str, dict]]] = {}
    for path, methods in paths.items():
        resource = _extract_resource_name(path)
        for method, operation in methods.items():
            if isinstance(operation, dict):
                groups.setdefault(resource, []).append((path, method.upper(), operation))
    return groups


def resource_to_markdown(
    resource_name: str,
    operations: list[tuple[str, str, dict]],
    schemas: dict[str, Any],
) -> str:
    """Convert a Twilio resource to a Markdown entity file."""
    lines = [f"# RESOURCE: {resource_name}"]
    lines.append("")

    # Find the schema for this resource
    schema_name = f"video.v1.room" if resource_name == "Rooms" else None
    # Try to find matching schema
    for sname, sdef in schemas.items():
        if resource_name.lower().rstrip("s") in sname.lower():
            schema_name = sname
            break

    # Fields from schema
    if schema_name and schema_name in schemas:
        schema = schemas[schema_name]
        properties = schema.get("properties", {})
        if properties:
            lines.append("## Fields")
            for prop_name, prop_def in properties.items():
                type_str = _schema_type_str(prop_def)
                desc = prop_def.get("description", "")
                nullable = prop_def.get("nullable", False)
                line = f"- {prop_name}: {type_str}"
                if nullable:
                    line += " (nullable)"
                if desc:
                    # Truncate long descriptions
                    desc_short = desc[:150].replace("\n", " ")
                    if len(desc) > 150:
                        desc_short += "..."
                    line += f" — {desc_short}"
                lines.append(line)
            lines.append("")

    # Endpoints
    lines.append("## Endpoints")
    for path, method, operation in operations:
        summary = operation.get("summary", operation.get("operationId", ""))
        desc = operation.get("description", "")
        lines.append(f"- {method} {path}")
        if summary:
            lines.append(f"  Summary: {summary}")

        # Parameters
        params = operation.get("parameters", [])
        if params:
            for p in params:
                p_name = p.get("name", "")
                p_in = p.get("in", "")
                p_schema = p.get("schema", {})
                p_type = _schema_type_str(p_schema)
                lines.append(f"  - Param: {p_name} ({p_in}, {p_type})")
    lines.append("")

    # Relationships — inferred from path nesting
    parent_resources = set()
    child_resources = set()
    for path, _, _ in operations:
        parts = [p for p in path.split("/") if p and not p.startswith("{") and p != "v1"]
        if len(parts) > 1:
            parent_resources.add(parts[0])
            for i in range(1, len(parts)):
                child_resources.add(parts[i])

    if parent_resources or child_resources:
        lines.append("## Relationships")
        if resource_name in [p for p in parent_resources]:
            pass  # This IS the parent
        for parent in parent_resources:
            if parent != resource_name:
                lines.append(f"- belongs_to: {parent}")
        for child in child_resources:
            if child != resource_name:
                lines.append(f"- has_many: {child}")
        lines.append("")

    return "\n".join(lines)


def create_ctxpack_config(corpus_dir: str) -> None:
    """Create a ctxpack.yaml configuration file for the Twilio corpus."""
    config = """domain: communications-api
scope: Twilio Video v1 API resource definitions
author: Twilio OpenAPI spec (public)
include:
  - "entities/*.md"
  - "docs/*.md"
"""
    path = os.path.join(corpus_dir, "ctxpack.yaml")
    with open(path, "w", encoding="utf-8") as f:
        f.write(config)


def create_supplementary_docs(corpus_dir: str, resource_names: list[str]) -> None:
    """Create supplementary docs for cross-resource relationships."""
    docs_dir = os.path.join(corpus_dir, "docs")
    os.makedirs(docs_dir, exist_ok=True)

    arch_md = textwrap.dedent("""\
    # Twilio Video Architecture

    ## Resource Hierarchy
    - Room is the top-level container for video sessions
    - Participants join Rooms and produce media tracks
    - Recordings capture media from individual tracks or the entire room
    - Compositions combine multiple recordings into a single media file
    - Recording Rules control which tracks are recorded

    ## SID Pattern Convention
    - All Twilio resources use SID (String Identifier) patterns
    - Format: 2-letter prefix + 32 hexadecimal characters
    - Prefixes are unique per resource type for quick identification

    ## Status Lifecycle
    - Rooms: in-progress → completed (or failed)
    - Participants: connected → disconnected
    - Recordings: processing → completed (or failed/deleted)
    - Compositions: enqueued → processing → completed (or failed/deleted)

    ## Media and Codecs
    - Video codecs: VP8, H264
    - Audio codecs: opus, PCMU
    - Recording formats: mka (audio), mkv (video), mp4 (composition)
    - Max participants varies by room type (peer-to-peer: 10, group: 50)

    ## Room Types
    - go: basic rooms for small meetings
    - peer-to-peer: direct P2P connections, no media server
    - group: server-routed, supports recording and composition
    - group-small: optimized group rooms for up to 4 participants
    """)

    with open(os.path.join(docs_dir, "architecture.md"), "w", encoding="utf-8") as f:
        f.write(arch_md)

    rules_md = textwrap.dedent("""\
    # Twilio Video Business Rules

    ## Recording Rules
    - Recording is only available for group and group-small room types
    - Peer-to-peer rooms do not support server-side recording
    - Recording rules can be set per-room or per-participant
    - Rules use include/exclude lists with track type and publisher SID

    ## Composition Rules
    - Compositions can only be created from completed rooms
    - A room must have at least one recording to create a composition
    - Composition resolution and format are configurable
    - Trim time allows excluding portions at the start/end

    ## Participant Limits
    - go rooms: max 2 participants
    - peer-to-peer rooms: max 10 participants
    - group-small rooms: max 4 participants
    - group rooms: max 50 participants (configurable)

    ## Webhook Events
    - room-created, room-ended
    - participant-connected, participant-disconnected
    - recording-started, recording-completed, recording-failed
    - composition-completed, composition-failed
    """)

    with open(os.path.join(docs_dir, "business-rules.md"), "w", encoding="utf-8") as f:
        f.write(rules_md)


def download_twilio_corpus(output_dir: str | None = None) -> dict[str, Any]:
    """Download and preprocess the Twilio Video API spec corpus.

    Returns:
        Summary dict with resource counts, token estimates, and resource names.
    """
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(__file__), "twilio", "corpus")

    entities_dir = os.path.join(output_dir, "entities")
    os.makedirs(entities_dir, exist_ok=True)

    print("  Fetching Twilio Video v1 OpenAPI spec...", end=" ", flush=True)
    spec = fetch_openapi_spec()
    if not spec:
        print("FAILED")
        return {"corpus": "twilio-video", "error": "Failed to fetch spec"}

    print("OK")

    paths = spec.get("paths", {})
    schemas = {}
    # Extract schemas from components
    components = spec.get("components", {})
    if components:
        schemas = components.get("schemas", {})

    # Group paths by resource
    resource_groups = _group_paths_by_resource(paths)

    total_tokens = 0
    resources_created: list[str] = []

    for resource_name, operations in sorted(resource_groups.items()):
        md_text = resource_to_markdown(resource_name, operations, schemas)
        tokens = len(md_text.split())
        total_tokens += tokens

        # Sanitize filename
        safe_name = resource_name.lower().replace(" ", "_")
        path = os.path.join(entities_dir, f"{safe_name}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(md_text)

        print(f"  Resource: {resource_name} ({tokens} tokens, {len(operations)} endpoints)")
        resources_created.append(resource_name)

    # Create config and supplementary docs
    create_ctxpack_config(output_dir)
    create_supplementary_docs(output_dir, resources_created)

    # Count supplementary doc tokens
    docs_dir = os.path.join(output_dir, "docs")
    for fname in os.listdir(docs_dir):
        with open(os.path.join(docs_dir, fname), encoding="utf-8") as f:
            total_tokens += len(f.read().split())

    summary = {
        "corpus": "twilio-video",
        "resources_created": resources_created,
        "total_files": len(resources_created) + 2,  # entities + 2 docs
        "estimated_tokens": total_tokens,
        "output_dir": output_dir,
    }

    print(f"\n  Twilio corpus: {len(resources_created)} resources, ~{total_tokens} tokens")
    print(f"  Output: {output_dir}")

    return summary


def main():
    print("=" * 50)
    print("  Twilio Video API Corpus Download")
    print("=" * 50)
    summary = download_twilio_corpus()
    print(f"\nSummary: {json.dumps(summary, indent=2)}")


if __name__ == "__main__":
    main()
