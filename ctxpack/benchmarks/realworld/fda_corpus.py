"""FDA Drug Labels corpus download and preprocessing.

Fetches structured product labeling (SPL) data from the openFDA API
for well-documented drugs, and converts to Markdown entity files
suitable for ctxpack packing.

Source: https://api.fda.gov/drug/label.json
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
import time
import urllib.parse
import urllib.request
from typing import Any

# Target drugs — well-documented, multi-section labels
TARGET_DRUGS = [
    ("metformin", "metformin hydrochloride"),
    ("lisinopril", "lisinopril"),
    ("atorvastatin", "atorvastatin calcium"),
    ("omeprazole", "omeprazole"),
    ("sertraline", "sertraline hydrochloride"),
]

# SPL sections to extract (openFDA field names)
SPL_SECTIONS = [
    ("indications_and_usage", "Indications and Usage"),
    ("dosage_and_administration", "Dosage and Administration"),
    ("dosage_forms_and_strengths", "Dosage Forms and Strengths"),
    ("contraindications", "Contraindications"),
    ("warnings_and_precautions", "Warnings and Precautions"),
    ("adverse_reactions", "Adverse Reactions"),
    ("drug_interactions", "Drug Interactions"),
    ("use_in_specific_populations", "Use in Specific Populations"),
    ("clinical_pharmacology", "Clinical Pharmacology"),
    ("mechanism_of_action", "Mechanism of Action"),
    ("pharmacodynamics", "Pharmacodynamics"),
    ("pharmacokinetics", "Pharmacokinetics"),
    ("overdosage", "Overdosage"),
    ("how_supplied_storage_and_handling", "How Supplied / Storage"),
    ("boxed_warning", "Boxed Warning"),
]

OPENFDA_BASE = "https://api.fda.gov/drug/label.json"


def fetch_drug_label(generic_name: str) -> dict[str, Any] | None:
    """Fetch a drug label from openFDA by generic name."""
    try:
        query = urllib.parse.quote(f'openfda.generic_name:"{generic_name}"')
        url = f"{OPENFDA_BASE}?search={query}&limit=1"
        req = urllib.request.Request(url, headers={"User-Agent": "ctxpack-eval/0.3"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            results = data.get("results", [])
            if results:
                return results[0]
    except Exception as e:
        print(f"  WARNING: Failed to fetch {generic_name}: {e}")

    return None


def extract_sections(label: dict[str, Any]) -> dict[str, str]:
    """Extract text sections from an openFDA label result."""
    sections: dict[str, str] = {}
    for field_name, display_name in SPL_SECTIONS:
        content = label.get(field_name, [])
        if content and isinstance(content, list):
            text = "\n".join(content)
            # Clean up excessive whitespace but preserve structure
            text = text.strip()
            if text:
                sections[display_name] = text
    return sections


def label_to_markdown(drug_name: str, label: dict[str, Any]) -> str:
    """Convert an openFDA label to a Markdown entity file."""
    openfda = label.get("openfda", {})
    brand_names = openfda.get("brand_name", [])
    generic_names = openfda.get("generic_name", [])
    manufacturer = openfda.get("manufacturer_name", ["Unknown"])
    route = openfda.get("route", ["oral"])
    pharm_class = openfda.get("pharm_class_epc", [])

    lines = [f"# DRUG: {drug_name.title()}"]
    lines.append("")

    # Metadata section
    lines.append("## Identification")
    if generic_names:
        lines.append(f"- Generic Name: {', '.join(generic_names)}")
    if brand_names:
        lines.append(f"- Brand Names: {', '.join(brand_names[:5])}")
    if manufacturer:
        lines.append(f"- Manufacturer: {manufacturer[0]}")
    if route:
        lines.append(f"- Route: {', '.join(route)}")
    if pharm_class:
        lines.append(f"- Pharmacological Class: {', '.join(pharm_class)}")
    lines.append("")

    # Content sections
    sections = extract_sections(label)
    for section_name, text in sections.items():
        lines.append(f"## {section_name}")
        # Truncate very long sections to keep corpus manageable
        if len(text) > 3000:
            text = text[:3000] + "\n[... truncated for brevity ...]"
        # Convert to bullet points where possible
        paragraphs = text.split("\n")
        for para in paragraphs:
            para = para.strip()
            if para:
                lines.append(f"- {para}" if not para.startswith("-") else para)
        lines.append("")

    return "\n".join(lines)


def create_ctxpack_config(corpus_dir: str, drug_names: list[str]) -> None:
    """Create a ctxpack.yaml configuration file for the FDA corpus."""
    config = f"""domain: healthcare-pharma
scope: FDA drug labels for {', '.join(d.title() for d in drug_names)}
author: openFDA API (public domain)
include:
  - "entities/*.md"
  - "docs/*.md"
"""
    path = os.path.join(corpus_dir, "ctxpack.yaml")
    with open(path, "w", encoding="utf-8") as f:
        f.write(config)


def create_supplementary_docs(corpus_dir: str, drug_names: list[str]) -> None:
    """Create supplementary Markdown docs for cross-drug relationships."""
    docs_dir = os.path.join(corpus_dir, "docs")
    os.makedirs(docs_dir, exist_ok=True)

    # Cross-drug interaction reference
    interactions_md = textwrap.dedent("""\
    # Cross-Drug Interaction Reference

    ## General Principles
    - Always check for CYP enzyme interactions before co-prescribing
    - Renal function must be monitored for drugs cleared by kidneys
    - Hepatic function affects metabolism of CYP3A4 substrates

    ## Known Safe Combinations
    - Metformin + Lisinopril: commonly co-prescribed for diabetic patients with hypertension
    - Atorvastatin + Lisinopril: standard cardiovascular risk reduction

    ## Caution Combinations
    - Atorvastatin + strong CYP3A4 inhibitors: risk of rhabdomyolysis
    - Sertraline + drugs affecting serotonin: risk of serotonin syndrome
    - Omeprazole + clopidogrel: reduced antiplatelet effect (CYP2C19 interaction)

    ## Monitoring Requirements
    - Metformin: monitor renal function (eGFR), hold before contrast procedures
    - Lisinopril: monitor potassium, renal function, blood pressure
    - Atorvastatin: monitor liver enzymes, CK if muscle symptoms
    - Omeprazole: monitor magnesium with long-term use (>1 year)
    - Sertraline: monitor for suicidal ideation (black box warning for age <25)
    """)

    with open(os.path.join(docs_dir, "cross-drug-interactions.md"), "w", encoding="utf-8") as f:
        f.write(interactions_md)

    # Regulatory context
    regulatory_md = textwrap.dedent("""\
    # FDA Regulatory Context

    ## Black Box Warnings
    - Black box warnings are the strongest FDA safety warning
    - Required when serious adverse effects or death risk exists
    - Sertraline (and all SSRIs): suicidality risk in patients under 25
    - ACE inhibitors (lisinopril): fetal toxicity in pregnancy

    ## Drug Scheduling
    - None of the drugs in this corpus are DEA scheduled
    - All are prescription-only (Rx)
    - Omeprazole also available OTC at lower doses (20mg)

    ## Generic Availability
    - All five drugs have generic versions available
    - Metformin: generic since 2002
    - Lisinopril: generic since 2002
    - Atorvastatin: generic since 2011 (Lipitor patent expiry)
    - Omeprazole: generic since 2001
    - Sertraline: generic since 2006 (Zoloft patent expiry)
    """)

    with open(os.path.join(docs_dir, "regulatory-context.md"), "w", encoding="utf-8") as f:
        f.write(regulatory_md)


def download_fda_corpus(output_dir: str | None = None) -> dict[str, Any]:
    """Download and preprocess the FDA drug labels corpus.

    Returns:
        Summary dict with file counts, token estimates, and drug names.
    """
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(__file__), "fda", "corpus")

    entities_dir = os.path.join(output_dir, "entities")
    os.makedirs(entities_dir, exist_ok=True)

    downloaded: list[str] = []
    total_tokens = 0

    for drug_key, generic_name in TARGET_DRUGS:
        print(f"  Fetching: {drug_key} ({generic_name})...", end=" ", flush=True)

        label = fetch_drug_label(generic_name)
        if not label:
            print("FAILED")
            continue

        md_text = label_to_markdown(drug_key, label)
        tokens = len(md_text.split())
        total_tokens += tokens

        path = os.path.join(entities_dir, f"{drug_key}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(md_text)

        sections = extract_sections(label)
        print(f"OK ({tokens} tokens, {len(sections)} sections)")
        downloaded.append(drug_key)

        # Rate limit courtesy
        time.sleep(0.5)

    # Create config and supplementary docs
    create_ctxpack_config(output_dir, downloaded)
    create_supplementary_docs(output_dir, downloaded)

    # Count supplementary doc tokens
    docs_dir = os.path.join(output_dir, "docs")
    for fname in os.listdir(docs_dir):
        with open(os.path.join(docs_dir, fname), encoding="utf-8") as f:
            total_tokens += len(f.read().split())

    summary = {
        "corpus": "fda-drug-labels",
        "drugs_downloaded": downloaded,
        "drugs_failed": [d[0] for d in TARGET_DRUGS if d[0] not in downloaded],
        "total_files": len(downloaded) + 2,  # entities + 2 docs
        "estimated_tokens": total_tokens,
        "output_dir": output_dir,
    }

    print(f"\n  FDA corpus: {len(downloaded)} drugs, ~{total_tokens} tokens")
    print(f"  Output: {output_dir}")

    return summary


def main():
    print("=" * 50)
    print("  FDA Drug Labels Corpus Download")
    print("=" * 50)
    summary = download_fda_corpus()
    print(f"\nSummary: {json.dumps(summary, indent=2)}")


if __name__ == "__main__":
    main()
