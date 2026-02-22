"""Generate synthetic domain corpora at various token sizes for scaling experiments.

Each corpus is self-consistent: entities reference each other, rules apply to
the entities present, docs describe the domain, and questions test facts that
are actually in the generated corpus.
"""

from __future__ import annotations

import os
import random
from typing import Any

# ── Domain entity templates ──
# Each template produces a valid YAML entity the packer recognizes.
# Templates are drawn from different industries for variety.

ENTITY_TEMPLATES: list[dict[str, Any]] = [
    # ── E-commerce / Retail ──
    {
        "entity": "CUSTOMER",
        "description": "Customer master entity, one per account",
        "aliases": ["client", "buyer"],
        "golden_source": "CRM (Salesforce)",
        "identifier": {"name": "customer_id", "type": "UUID", "immutable": True},
        "match_rules": [
            {"field": "email", "method": "exact match", "options": {"case_sensitive": False, "trim": True}},
            {"field": "phone", "method": "normalise", "options": {"format": "E.164"}},
            {"field": "name+address", "method": "fuzzy match", "options": {"algorithm": "Jaro-Winkler", "threshold": 0.92, "review": "manual"}},
        ],
        "pii": ["name", "email", "phone", "address"],
        "pii_classification": "RESTRICTED",
        "retention": {"active": "indefinite", "churned": {"months": 36, "action": "anonymise"}},
        "questions": [
            {"q": "What is the golden source for {entity} data?", "a": "CRM (Salesforce)", "d": "easy"},
            {"q": "What type is the {id_field} field?", "a": "UUID", "d": "easy"},
            {"q": "Is the {id_field} field mutable?", "a": "No, it is immutable", "d": "easy"},
            {"q": "What matching algorithm is used for name+address in {entity}?", "a": "Jaro-Winkler with threshold > 0.92", "d": "medium"},
            {"q": "What PII classification level applies to {entity} email?", "a": "RESTRICTED", "d": "medium"},
            {"q": "What happens to churned {entity} data after 36 months?", "a": "anonymise", "d": "medium"},
        ],
    },
    {
        "entity": "ORDER",
        "description": "Order transaction entity",
        "aliases": ["purchase", "transaction"],
        "golden_source": "OMS (OrderHub)",
        "identifier": {"name": "order_id", "type": "UUID", "immutable": True},
        "belongs_to": {"entity": "CUSTOMER", "field": "customer_id", "mandatory": True},
        "status_flow": ["draft", "submitted", "processing", "shipped", "delivered"],
        "terminal_states": ["cancelled", "returned"],
        "immutable_after": "submitted",
        "financial_fields": {"fields": ["subtotal", "tax", "shipping_cost", "total"], "type": "DECIMAL(19,4)"},
        "retention": {"active": "indefinite", "completed": {"months": 84, "action": "archive"}},
        "questions": [
            {"q": "What is the {entity} status flow?", "a": "draft -> submitted -> processing -> shipped -> delivered", "d": "medium"},
            {"q": "After which status can {entity} line items no longer be edited?", "a": "submitted", "d": "medium"},
            {"q": "What decimal precision should be used for {entity} financial fields?", "a": "DECIMAL(19,4)", "d": "easy"},
            {"q": "What entity does {entity} belong to?", "a": "CUSTOMER (via customer_id)", "d": "easy"},
        ],
    },
    {
        "entity": "PRODUCT",
        "description": "Product catalog entity, one per merchant",
        "aliases": ["item", "SKU"],
        "golden_source": "PIM (Akeneo)",
        "identifier": {"name": "sku", "type": "string", "unique": True},
        "catalog_status": ["active", "discontinued", "seasonal", "pre-order"],
        "price_rules": {"base": "merchant-sets-base-price", "platform_applies": ["promotions", "bulk-discounts", "regional-pricing"]},
        "inventory": {"sync": "real-time", "source": "warehouse-API", "method": "webhook + 5min poll fallback"},
        "known_issues": ["SKU format inconsistency across merchants", "Normalisation pipeline required"],
        "questions": [
            {"q": "What is the SKU identifier type for {entity}?", "a": "string, unique per merchant", "d": "easy"},
            {"q": "How is {entity} inventory data synced?", "a": "Real-time via warehouse API (webhook + 5min poll fallback)", "d": "medium"},
        ],
    },
    {
        "entity": "PAYMENT",
        "description": "Payment transaction entity",
        "aliases": ["charge", "settlement"],
        "golden_source": "Payment Gateway (Stripe)",
        "identifier": {"name": "payment_id", "type": "UUID", "immutable": True},
        "belongs_to": {"entity": "ORDER", "field": "order_id", "mandatory": True},
        "methods": ["credit_card", "debit_card", "bank_transfer", "digital_wallet"],
        "currency_handling": {"storage": "original + USD equivalent", "exchange_rate": "daily ECB rate"},
        "pii": ["card_number", "bank_account"],
        "pii_classification": "HIGHLY-RESTRICTED",
        "retention": {"all": {"months": 84, "action": "archive"}},
        "questions": [
            {"q": "What is the PII classification for {entity} card numbers?", "a": "HIGHLY-RESTRICTED", "d": "medium"},
            {"q": "Can a {entity} exist without an associated ORDER?", "a": "No, order_id is mandatory ({entity} belongs to ORDER)", "d": "hard"},
        ],
    },
    # ── Logistics / Supply Chain ──
    {
        "entity": "SHIPMENT",
        "description": "Shipment tracking entity, one per carrier booking",
        "aliases": ["delivery", "consignment"],
        "golden_source": "TMS (ShipStation)",
        "identifier": {"name": "tracking_number", "type": "string", "unique": True},
        "belongs_to": {"entity": "ORDER", "field": "order_id", "mandatory": True},
        "status_flow": ["label-created", "picked-up", "in-transit", "out-for-delivery", "delivered"],
        "terminal_states": ["returned-to-sender", "lost"],
        "carrier_fields": {"carrier": "string", "service_level": "string", "estimated_delivery": "datetime"},
        "retention": {"active": "indefinite", "delivered": {"months": 24, "action": "archive"}},
        "questions": [
            {"q": "What is the {entity} status flow?", "a": "label-created -> picked-up -> in-transit -> out-for-delivery -> delivered", "d": "medium"},
            {"q": "What is the golden source for {entity} data?", "a": "TMS (ShipStation)", "d": "easy"},
            {"q": "How long are delivered {entity} records retained?", "a": "24 months then archived", "d": "medium"},
        ],
    },
    {
        "entity": "WAREHOUSE",
        "description": "Warehouse location entity, one per facility",
        "aliases": ["facility", "distribution-center", "DC"],
        "golden_source": "WMS (Manhattan Associates)",
        "identifier": {"name": "warehouse_id", "type": "string", "unique": True},
        "capacity": {"unit": "pallets", "max": 50000, "alert_threshold": "90%"},
        "operating_hours": {"weekday": "06:00-22:00", "weekend": "08:00-18:00"},
        "zones": ["receiving", "storage", "picking", "packing", "shipping"],
        "retention": {"active": "indefinite", "decommissioned": {"months": 60, "action": "archive"}},
        "questions": [
            {"q": "What is the capacity alert threshold for {entity}?", "a": "90% of max pallets", "d": "medium"},
            {"q": "What zones does a {entity} have?", "a": "receiving, storage, picking, packing, shipping", "d": "easy"},
        ],
    },
    # ── Healthcare / Pharma ──
    {
        "entity": "PATIENT",
        "description": "Patient demographic entity, one per healthcare system",
        "aliases": ["subject", "enrollee"],
        "golden_source": "EHR (Epic)",
        "identifier": {"name": "mrn", "type": "string", "unique": True},
        "match_rules": [
            {"field": "ssn_last4+dob", "method": "exact match", "options": {"both_required": True}},
            {"field": "name+dob", "method": "fuzzy match", "options": {"algorithm": "Soundex", "threshold": 0.85}},
        ],
        "pii": ["name", "ssn", "dob", "address", "phone", "insurance_id"],
        "pii_classification": "HIGHLY-RESTRICTED",
        "retention": {"active": "indefinite", "deceased": {"months": 120, "action": "archive"}},
        "questions": [
            {"q": "What is the golden source for {entity} data?", "a": "EHR (Epic)", "d": "easy"},
            {"q": "What PII classification applies to {entity} data?", "a": "HIGHLY-RESTRICTED", "d": "medium"},
            {"q": "How long are deceased {entity} records retained?", "a": "120 months (10 years) then archived", "d": "medium"},
            {"q": "What matching algorithm is used for name+dob in {entity}?", "a": "Soundex with threshold > 0.85", "d": "medium"},
        ],
    },
    {
        "entity": "PROVIDER",
        "description": "Healthcare provider entity, one per NPI",
        "aliases": ["HCP", "physician", "clinician"],
        "golden_source": "Credentialing (CAQH)",
        "identifier": {"name": "npi", "type": "string", "unique": True},
        "specialties": ["primary-care", "cardiology", "oncology", "neurology", "pediatrics"],
        "credential_status": ["active", "suspended", "expired", "revoked"],
        "affiliation": {"entity": "FACILITY", "field": "facility_id", "mandatory": False},
        "retention": {"active": "indefinite", "revoked": {"months": 84, "action": "archive"}},
        "questions": [
            {"q": "What is the identifier for {entity}?", "a": "NPI (string, unique)", "d": "easy"},
            {"q": "What are the credential statuses for {entity}?", "a": "active, suspended, expired, revoked", "d": "medium"},
        ],
    },
    # ── Fintech / Banking ──
    {
        "entity": "ACCOUNT",
        "description": "Financial account entity, one per customer per type",
        "aliases": ["deposit-account", "ledger"],
        "golden_source": "Core Banking (Temenos)",
        "identifier": {"name": "account_number", "type": "string", "unique": True},
        "belongs_to": {"entity": "CUSTOMER", "field": "customer_id", "mandatory": True},
        "account_types": ["checking", "savings", "money-market", "CD"],
        "balance_rules": {"precision": "DECIMAL(19,4)", "currency": "USD", "negative_allowed": False},
        "pii": ["account_number", "routing_number"],
        "pii_classification": "HIGHLY-RESTRICTED",
        "retention": {"active": "indefinite", "closed": {"months": 84, "action": "archive"}},
        "questions": [
            {"q": "What precision should {entity} balances use?", "a": "DECIMAL(19,4)", "d": "easy"},
            {"q": "Can {entity} balances go negative?", "a": "No, negative balances are not allowed", "d": "medium"},
            {"q": "What is the golden source for {entity}?", "a": "Core Banking (Temenos)", "d": "easy"},
        ],
    },
    {
        "entity": "TRANSACTION",
        "description": "Financial transaction entity",
        "aliases": ["transfer", "movement"],
        "golden_source": "Payment Processor (FIS)",
        "identifier": {"name": "txn_id", "type": "UUID", "immutable": True},
        "belongs_to": {"entity": "ACCOUNT", "field": "account_number", "mandatory": True},
        "status_flow": ["initiated", "pending", "cleared", "settled"],
        "terminal_states": ["reversed", "failed"],
        "amount_rules": {"precision": "DECIMAL(19,4)", "min": 0.01, "max_single": 250000, "daily_limit": 1000000},
        "fraud_checks": {"velocity": "max 10 txns per hour", "geo": "flag if >500km from last txn", "amount": "flag if >$10000"},
        "retention": {"all": {"months": 84, "action": "archive"}},
        "questions": [
            {"q": "What is the daily transaction limit for {entity}?", "a": "$1,000,000", "d": "medium"},
            {"q": "What fraud velocity check applies to {entity}?", "a": "max 10 transactions per hour", "d": "medium"},
            {"q": "What is the {entity} status flow?", "a": "initiated -> pending -> cleared -> settled", "d": "medium"},
        ],
    },
    # ── HR / People ──
    {
        "entity": "EMPLOYEE",
        "description": "Employee master entity, one per organization",
        "aliases": ["staff", "worker", "team-member"],
        "golden_source": "HRIS (Workday)",
        "identifier": {"name": "employee_id", "type": "string", "unique": True},
        "pii": ["name", "ssn", "dob", "salary", "bank_details"],
        "pii_classification": "HIGHLY-RESTRICTED",
        "employment_status": ["active", "on-leave", "terminated", "retired"],
        "retention": {"active": "indefinite", "terminated": {"months": 84, "action": "anonymise"}},
        "questions": [
            {"q": "What is the golden source for {entity} data?", "a": "HRIS (Workday)", "d": "easy"},
            {"q": "What PII classification applies to {entity} salary data?", "a": "HIGHLY-RESTRICTED", "d": "medium"},
            {"q": "What happens to terminated {entity} data after 84 months?", "a": "anonymise", "d": "medium"},
        ],
    },
    {
        "entity": "DEPARTMENT",
        "description": "Organizational department entity",
        "aliases": ["team", "division", "business-unit"],
        "golden_source": "Org Chart (Workday)",
        "identifier": {"name": "dept_code", "type": "string", "unique": True},
        "hierarchy": {"parent": "department", "max_depth": 5},
        "budget_rules": {"fiscal_year": "calendar", "approval_threshold": 50000, "over_budget_action": "escalate to VP"},
        "retention": {"active": "indefinite", "dissolved": {"months": 36, "action": "archive"}},
        "questions": [
            {"q": "What is the budget approval threshold for {entity}?", "a": "$50,000", "d": "medium"},
            {"q": "What happens when {entity} exceeds budget?", "a": "escalate to VP", "d": "medium"},
        ],
    },
    # ── Marketing / CRM ──
    {
        "entity": "CAMPAIGN",
        "description": "Marketing campaign entity",
        "aliases": ["promotion", "initiative"],
        "golden_source": "MAP (Marketo)",
        "identifier": {"name": "campaign_id", "type": "UUID", "immutable": True},
        "status_flow": ["draft", "scheduled", "active", "paused", "completed"],
        "terminal_states": ["cancelled"],
        "budget": {"currency": "USD", "precision": "DECIMAL(12,2)", "approval_required_above": 25000},
        "channels": ["email", "social", "paid-search", "display", "direct-mail"],
        "retention": {"active": "indefinite", "completed": {"months": 60, "action": "archive"}},
        "questions": [
            {"q": "What is the {entity} status flow?", "a": "draft -> scheduled -> active -> paused -> completed", "d": "medium"},
            {"q": "Above what amount does {entity} budget require approval?", "a": "$25,000", "d": "medium"},
        ],
    },
    {
        "entity": "LEAD",
        "description": "Sales lead entity, one per prospect interaction",
        "aliases": ["prospect", "opportunity"],
        "golden_source": "CRM (HubSpot)",
        "identifier": {"name": "lead_id", "type": "UUID", "immutable": True},
        "belongs_to": {"entity": "CAMPAIGN", "field": "campaign_id", "mandatory": False},
        "scoring": {"model": "BANT", "threshold_mql": 60, "threshold_sql": 80},
        "status_flow": ["new", "contacted", "qualified", "proposal", "negotiation", "closed-won"],
        "terminal_states": ["closed-lost", "disqualified"],
        "retention": {"active": "indefinite", "closed-lost": {"months": 24, "action": "anonymise"}},
        "questions": [
            {"q": "What scoring model is used for {entity}?", "a": "BANT", "d": "easy"},
            {"q": "What is the MQL threshold for {entity}?", "a": "score of 60", "d": "medium"},
            {"q": "What is the golden source for {entity}?", "a": "CRM (HubSpot)", "d": "easy"},
        ],
    },
]

# ── Rule templates ──

RULE_TEMPLATES: list[dict[str, Any]] = [
    {
        "name": "data-quality",
        "null_policies": [
            {"field": "{id_field}", "policy": "never-null"},
            {"field": "email", "policy": "never-null-for-active"},
            {"field": "phone", "policy": "nullable"},
        ],
        "freshness": [
            {"data": "customer-data", "max_stale": "24 hours"},
            {"data": "inventory", "max_stale": "5 minutes"},
            {"data": "transactions", "max_stale": "real-time"},
        ],
        "dedup": {"batch": "daily", "realtime": "on-new-registration"},
        "anomaly_detection": [
            {"condition": "amount > $10,000", "action": "flag for review"},
            {"condition": "amount > $50,000", "action": "auto-hold + alert"},
        ],
        "questions": [
            {"q": "What is the maximum staleness allowed for inventory data?", "a": "5 minutes", "d": "medium"},
            {"q": "What happens when a transaction exceeds $50,000?", "a": "auto-hold and alert", "d": "medium"},
        ],
    },
    {
        "name": "transformation",
        "timezone": {"storage": "UTC", "display": "customer-locale"},
        "currency": {"storage": "original + USD equivalent", "rate": "daily ECB"},
        "address_normalization": {
            "api": "SmartyStreets",
            "format_us": "USPS",
            "format_uk": "Royal-Mail",
        },
        "name_normalization": "none - preserve original case and diacritics",
        "questions": [
            {"q": "How are timestamps stored and displayed?", "a": "Stored in UTC, displayed in customer locale", "d": "easy"},
            {"q": "What is the UK address format standard used for normalisation?", "a": "Royal Mail", "d": "hard"},
            {"q": "How are US addresses normalised?", "a": "Via SmartyStreets API, USPS format", "d": "medium"},
        ],
    },
]

# ── Doc templates (Markdown) ──

DOC_TEMPLATES: list[dict[str, Any]] = [
    {
        "name": "business-rules",
        "template": """# Business Rules

## {entity1} Matching Rules

{entity1} records are matched using multiple strategies:
- **Email**: exact match, case-insensitive, trimmed whitespace
- **Phone**: normalised to E.164 format before comparison
- **Name + Address**: Jaro-Winkler similarity > 0.92 triggers manual review

All {entity1_lower}s must have at least one communication channel. Default channel is email.

## {entity2} Financial Rules

All monetary values must use DECIMAL(19,4). Never use FLOAT for financial data.

### Status Flow
{entity2} follows: draft → submitted → processing → shipped → delivered.
Terminal states: cancelled, returned.

Once an {entity2_lower} reaches submitted status, line items cannot be edited.
""",
    },
    {
        "name": "regulatory",
        "template": """# Regulatory Compliance

## Data Retention
- Financial transaction data must be retained for a minimum of **7 years** (84 months)
- This regulatory requirement **overrides** any shorter entity-specific retention policies
- All retention policies must be auditable

## PII Handling
- All PII fields must be encrypted at rest and in transit
- HIGHLY-RESTRICTED data (payment card numbers, bank accounts) requires additional authorization
- Access to PII must be logged in the audit trail

## Audit Trail Requirements
Every change to {entity1} or {entity2} data must log:
- Timestamp (UTC)
- User or system that made the change
- Before and after values
- Reason for the change
""",
    },
    {
        "name": "tribal-knowledge",
        "template": """# Tribal Knowledge & Known Issues

## Known Data Quality Issues
- SKU format is inconsistent across merchants; normalisation pipeline required
- "{entity1_alias}" and "{entity1_lower}" are synonyms; canonical term is {entity1}
- Legacy systems may use deprecated field names

## Retention Gotchas
> **Warning:** The 36-month anonymisation rule for churned {entity1_lower}s must NOT be applied
> to {entity1_lower}s with financial records. The 7-year regulatory retention overrides.

## Seasonal {entity3}
- Seasonal {entity3_lower}s are auto-deactivated at end of season
- Reactivation requires manual review by merchandising team
- Pre-order {entity3_lower}s have different pricing rules
""",
    },
]


def _entity_to_yaml(entity: dict[str, Any]) -> str:
    """Convert an entity template to YAML text."""
    lines = []
    lines.append(f"entity: {entity['entity']}")
    if "description" in entity:
        lines.append(f"description: {entity['description']}")
    lines.append("")

    if "aliases" in entity:
        lines.append("aliases:")
        for a in entity["aliases"]:
            lines.append(f"  - {a}")
        lines.append("")

    if "golden_source" in entity:
        lines.append(f"golden_source: {entity['golden_source']}")
        lines.append("")

    if "identifier" in entity:
        ident = entity["identifier"]
        lines.append("identifier:")
        lines.append(f"  name: {ident['name']}")
        lines.append(f"  type: {ident['type']}")
        for flag in ("immutable", "unique", "required"):
            if ident.get(flag):
                lines.append(f"  {flag}: true")
        lines.append("")

    if "belongs_to" in entity:
        bt = entity["belongs_to"]
        lines.append("belongs_to:")
        lines.append(f"  entity: {bt['entity']}")
        lines.append(f"  field: {bt['field']}")
        lines.append(f"  mandatory: {'true' if bt.get('mandatory') else 'false'}")
        lines.append("")

    if "match_rules" in entity:
        lines.append("match_rules:")
        for rule in entity["match_rules"]:
            lines.append(f"  - field: {rule['field']}")
            lines.append(f"    method: {rule['method']}")
            if "options" in rule:
                lines.append("    options:")
                for k, v in rule["options"].items():
                    lines.append(f"      {k}: {v}")
        lines.append("")

    if "status_flow" in entity:
        lines.append("status_flow:")
        for s in entity["status_flow"]:
            lines.append(f"  - {s}")
        if "terminal_states" in entity:
            lines.append("terminal_states:")
            for s in entity["terminal_states"]:
                lines.append(f"  - {s}")
        lines.append("")

    if "immutable_after" in entity:
        lines.append(f"immutable_after: {entity['immutable_after']}")
        lines.append("")

    if "financial_fields" in entity:
        ff = entity["financial_fields"]
        lines.append("financial_fields:")
        lines.append("  fields:")
        for f in ff["fields"]:
            lines.append(f"    - {f}")
        lines.append(f"  type: {ff['type']}")
        lines.append("")

    if "pii" in entity:
        lines.append("pii:")
        for p in entity["pii"]:
            lines.append(f"  - {p}")
        if "pii_classification" in entity:
            lines.append(f"pii_classification: {entity['pii_classification']}")
        lines.append("")

    # Generic dict/list fields
    for key in ("catalog_status", "methods", "account_types", "channels",
                "employment_status", "credential_status", "specialties", "zones"):
        if key in entity:
            lines.append(f"{key}:")
            for item in entity[key]:
                lines.append(f"  - {item}")
            lines.append("")

    for key in ("price_rules", "inventory", "currency_handling", "capacity",
                "operating_hours", "balance_rules", "budget", "scoring",
                "hierarchy", "carrier_fields", "amount_rules", "fraud_checks",
                "budget_rules", "affiliation"):
        if key in entity:
            val = entity[key]
            if isinstance(val, dict):
                lines.append(f"{key}:")
                for k, v in val.items():
                    if isinstance(v, list):
                        lines.append(f"  {k}:")
                        for item in v:
                            lines.append(f"    - {item}")
                    elif isinstance(v, bool):
                        lines.append(f"  {k}: {'true' if v else 'false'}")
                    else:
                        lines.append(f"  {k}: {v}")
                lines.append("")

    if "known_issues" in entity:
        lines.append("known_issues:")
        for issue in entity["known_issues"]:
            lines.append(f"  - {issue}")
        lines.append("")

    if "retention" in entity:
        lines.append("retention:")
        for k, v in entity["retention"].items():
            if isinstance(v, dict):
                lines.append(f"  {k}:")
                for rk, rv in v.items():
                    lines.append(f"    {rk}: {rv}")
            else:
                lines.append(f"  {k}: {v}")
        lines.append("")

    return "\n".join(lines)


def _rules_to_yaml(rule: dict[str, Any]) -> str:
    """Convert a rules template to YAML text."""
    lines = [f"# {rule['name']} rules", ""]
    for key, val in rule.items():
        if key in ("name", "questions"):
            continue
        if isinstance(val, list):
            lines.append(f"{key}:")
            for item in val:
                if isinstance(item, dict):
                    first = True
                    for k, v in item.items():
                        prefix = "  - " if first else "    "
                        lines.append(f"{prefix}{k}: {v}")
                        first = False
                else:
                    lines.append(f"  - {item}")
            lines.append("")
        elif isinstance(val, dict):
            lines.append(f"{key}:")
            for k, v in val.items():
                if isinstance(v, dict):
                    lines.append(f"  {k}:")
                    for kk, vv in v.items():
                        lines.append(f"    {kk}: {vv}")
                else:
                    lines.append(f"  {k}: {v}")
            lines.append("")
        else:
            lines.append(f"{key}: {val}")
            lines.append("")
    return "\n".join(lines)


def _count_words(text: str) -> int:
    """Count words (approximate token count)."""
    return len(text.split())


def generate_corpus(
    target_tokens: int,
    output_dir: str,
    *,
    seed: int = 42,
) -> dict[str, Any]:
    """Generate a synthetic corpus targeting approximately target_tokens words.

    Returns metadata dict with actual token count and question list.
    """
    rng = random.Random(seed)

    os.makedirs(output_dir, exist_ok=True)
    entities_dir = os.path.join(output_dir, "entities")
    rules_dir = os.path.join(output_dir, "rules")
    docs_dir = os.path.join(output_dir, "docs")
    os.makedirs(entities_dir, exist_ok=True)
    os.makedirs(rules_dir, exist_ok=True)
    os.makedirs(docs_dir, exist_ok=True)

    total_words = 0
    selected_entities: list[dict[str, Any]] = []
    all_questions: list[dict[str, str]] = []
    entity_texts: list[tuple[str, str]] = []  # (filename, text)
    q_counter = 0

    # Shuffle entity order for variety
    templates = list(ENTITY_TEMPLATES)
    rng.shuffle(templates)

    # Keep adding entities until we hit the target
    cycle = 0
    while total_words < target_tokens * 0.65:  # entities = ~65% of corpus
        for tmpl in templates:
            if total_words >= target_tokens * 0.65:
                break

            # On repeat cycles, create variant entities with suffix
            if cycle == 0:
                entity = dict(tmpl)
            else:
                entity = dict(tmpl)
                suffix = f"_V{cycle}"
                entity["entity"] = tmpl["entity"] + suffix
                # Modify description slightly
                entity["description"] = tmpl.get("description", "") + f" (variant {cycle})"
                if "identifier" in entity:
                    entity["identifier"] = dict(tmpl["identifier"])
                    entity["identifier"]["name"] = tmpl["identifier"]["name"] + f"_v{cycle}"

            yaml_text = _entity_to_yaml(entity)
            words = _count_words(yaml_text)
            total_words += words

            filename = entity["entity"].lower().replace("_", "-") + ".yaml"
            entity_texts.append((filename, yaml_text))
            selected_entities.append(entity)

            # Generate questions for this entity
            for qt in tmpl.get("questions", []):
                q_counter += 1
                ent_name = entity["entity"]
                id_field = entity.get("identifier", {}).get("name", "id")
                q_text = qt["q"].format(entity=ent_name, id_field=id_field)
                a_text = qt["a"].format(entity=ent_name, id_field=id_field)
                all_questions.append({
                    "id": f"Q{q_counter:03d}",
                    "question": q_text,
                    "expected": a_text,
                    "difficulty": qt["d"],
                    "entities": [ent_name],
                })

        cycle += 1
        if cycle > 100:  # safety valve
            break

    # Write entity files
    for filename, text in entity_texts:
        with open(os.path.join(entities_dir, filename), "w", encoding="utf-8") as f:
            f.write(text)

    # Add rules (scale proportionally)
    for rule_tmpl in RULE_TEMPLATES:
        rule_text = _rules_to_yaml(rule_tmpl)
        words = _count_words(rule_text)
        total_words += words
        filename = rule_tmpl["name"] + ".yaml"
        with open(os.path.join(rules_dir, filename), "w", encoding="utf-8") as f:
            f.write(rule_text)

        for qt in rule_tmpl.get("questions", []):
            q_counter += 1
            all_questions.append({
                "id": f"Q{q_counter:03d}",
                "question": qt["q"],
                "expected": qt["a"],
                "difficulty": qt["d"],
                "entities": [],
            })

    # Add docs (use first 3 entities for template substitution)
    e1 = selected_entities[0] if selected_entities else {"entity": "ENTITY1", "aliases": ["alias1"]}
    e2 = selected_entities[1] if len(selected_entities) > 1 else {"entity": "ENTITY2", "aliases": ["alias2"]}
    e3 = selected_entities[2] if len(selected_entities) > 2 else {"entity": "ENTITY3", "aliases": ["alias3"]}

    for doc_tmpl in DOC_TEMPLATES:
        doc_text = doc_tmpl["template"].format(
            entity1=e1["entity"],
            entity1_lower=e1["entity"].lower(),
            entity1_alias=e1.get("aliases", ["alias"])[0],
            entity2=e2["entity"],
            entity2_lower=e2["entity"].lower(),
            entity3=e3.get("entity", "PRODUCT"),
            entity3_lower=e3.get("entity", "PRODUCT").lower(),
        )
        words = _count_words(doc_text)
        total_words += words
        filename = doc_tmpl["name"] + ".md"
        with open(os.path.join(docs_dir, filename), "w", encoding="utf-8") as f:
            f.write(doc_text)

    # Add adversarial questions (10-15% of total)
    adversarial_count = max(2, len(all_questions) // 7)
    adversarial_qs = [
        {"q": "What is the customer return/refund policy?", "a": "NOT_IN_CONTEXT", "d": "hard"},
        {"q": "What GDPR or CCPA compliance rules apply to data deletion?", "a": "NOT_IN_CONTEXT", "d": "hard"},
        {"q": "What is the disaster recovery procedure?", "a": "NOT_IN_CONTEXT", "d": "hard"},
        {"q": "What machine learning models are used for classification?", "a": "NOT_IN_CONTEXT", "d": "hard"},
        {"q": "What is the SLA for API response time?", "a": "NOT_IN_CONTEXT", "d": "hard"},
    ]
    for i, aq in enumerate(adversarial_qs[:adversarial_count]):
        q_counter += 1
        all_questions.append({
            "id": f"Q{q_counter:03d}",
            "question": aq["q"],
            "expected": aq["a"],
            "difficulty": aq["d"],
            "entities": [],
            "adversarial": True,
        })

    # Add conflict detection questions if we have retention conflicts
    q_counter += 1
    all_questions.append({
        "id": f"Q{q_counter:03d}",
        "question": "Are there any conflicting retention policies?",
        "expected": f"Yes - {e1['entity']} says 36 months for churned, regulatory requires 7 years for financial records",
        "difficulty": "hard",
        "entities": [e1["entity"]],
        "tests_conflict_detection": True,
    })
    q_counter += 1
    all_questions.append({
        "id": f"Q{q_counter:03d}",
        "question": "What is the minimum retention period for financial transaction data?",
        "expected": "7 years (regulatory requirement)",
        "difficulty": "hard",
        "entities": [],
        "tests_conflict_detection": True,
    })

    # Write ctxpack.yaml config
    entity_names = [e["entity"] for e in selected_entities]
    aliases_map = {}
    golden_sources = {}
    for e in selected_entities:
        aliases_map[e["entity"]] = e.get("aliases", [])
        if "golden_source" in e:
            golden_sources[e["entity"]] = e["golden_source"]

    config_lines = [
        f"domain: scaling-test-{target_tokens}",
        f"scope: multi-domain-eval",
        f"author: ctxpack-scaling-generator",
        "",
        "entity_aliases:",
    ]
    for ent, als in aliases_map.items():
        if als:
            config_lines.append(f"  {ent}:")
            for a in als:
                config_lines.append(f"    - {a}")
    config_lines.append("")
    config_lines.append("golden_sources:")
    for ent, gs in golden_sources.items():
        config_lines.append(f"  {ent}: {gs}")
    config_text = "\n".join(config_lines) + "\n"
    total_words += _count_words(config_text)

    with open(os.path.join(output_dir, "ctxpack.yaml"), "w", encoding="utf-8") as f:
        f.write(config_text)

    # Write questions.yaml
    q_lines = []
    for q in all_questions:
        q_lines.append(f"- id: {q['id']}")
        q_lines.append(f'  question: "{q["question"]}"')
        q_lines.append(f'  expected: "{q["expected"]}"')
        q_lines.append(f"  difficulty: {q['difficulty']}")
        entities_str = ", ".join(q.get("entities", []))
        q_lines.append(f"  entities: [{entities_str}]")
        if q.get("adversarial"):
            q_lines.append("  adversarial: true")
        if q.get("tests_conflict_detection"):
            q_lines.append("  tests_conflict_detection: true")
        q_lines.append("")
    q_text = "\n".join(q_lines)

    # Questions file goes alongside the corpus dir, not inside it
    parent_dir = os.path.dirname(output_dir)
    with open(os.path.join(parent_dir, "questions.yaml"), "w", encoding="utf-8") as f:
        f.write(q_text)

    return {
        "target_tokens": target_tokens,
        "actual_words": total_words,
        "entity_count": len(selected_entities),
        "question_count": len(all_questions),
        "files": len(entity_texts) + len(RULE_TEMPLATES) + len(DOC_TEMPLATES) + 1,
    }


def generate_all_scaling_corpora(base_dir: str) -> list[dict[str, Any]]:
    """Generate corpora at all scaling targets."""
    targets = [1000, 5000, 20000, 50000]
    results = []
    for target in targets:
        corpus_dir = os.path.join(base_dir, f"scale_{target}", "corpus")
        meta = generate_corpus(target, corpus_dir, seed=42 + target)
        results.append(meta)
    return results
