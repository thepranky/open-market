# Jurisdiction Schema Specification

## Logical structure

Threshold tests for a jurisdiction are **OR**'d — passing any one test triggers a filing obligation.  
Conditions within a single test are **AND**'d — all must be true for the test to fire.  
Exclusions within a test are evaluated after conditions and, if met, cancel the test result.

## Top-level fields

| Field | Type | Description |
|-------|------|-------------|
| `jurisdiction_id` | string | Unique snake_case identifier, e.g. `eu`, `us_hsr`, `uk` |
| `jurisdiction_name` | string | Display name |
| `last_verified` | date | When the data was last checked against primary sources |
| `authority.name` | string | Full name of the competition authority |
| `authority.abbreviation` | string | e.g. `EC`, `CMA`, `FTC/DOJ` |
| `authority.url` | string | Authority homepage |
| `authority.filing_url` | string | Filing portal or notification guidance page |

## Regime fields

| Field | Type | Description |
|-------|------|-------------|
| `regime.mandatory` | bool | Filing is legally required if thresholds are met |
| `regime.suspensory` | bool | Parties may not close before clearance (standstill obligation) |
| `regime.voluntary` | bool | Filing is possible below thresholds at parties' discretion |

## Legal basis

Array of source objects. Each source must cite a specific legal provision, not a website page.

```yaml
legal_basis:
  - citation: "Council Regulation (EC) No 139/2004, Article 1"
    url: "https://eur-lex.europa.eu/..."
    note: "Optional clarification"
```

## Filing deadlines

```yaml
filing:
  deadline_from_signing_days: int | null    # null = no fixed deadline from signing
  deadline_from_closing_days: int | null    # null = no fixed deadline from closing
  pre_closing_required: bool                # must file and receive clearance before closing
  note: string
```

## Review periods

```yaml
review_periods:
  phase_1:
    days: int
    day_type: "calendar" | "working"
    extendable_to_days: int | null
    legal_basis: string                     # specific article
  phase_2:
    days: int
    day_type: "calendar" | "working"
    extendable_to_days: int | null
    legal_basis: string
```

## Threshold tests

```yaml
threshold_tests:
  - test_id: string                         # unique within jurisdiction
    description: string
    legal_basis: string                     # specific article/paragraph
    source_url: string                      # direct URL to the legal text
    note: string | null
    annual_adjustment: bool                 # true if thresholds are periodically revised
    effective_date: date | null             # when current values took effect

    conditions:
      - condition_id: string
        metric: see Metric types below
        scope: see Scope types below
        party: see Party types below
        operator: ">" | ">=" | "<" | "<="
        value: number                       # monetary values in currency units (not millions)
        currency: string | null             # ISO 4217 code; null for ratios/percentages
        source: string                      # specific sub-article this figure comes from
        qualifier: null | CountQualifier    # for "in each of at least N countries" conditions

    exclusions:
      - exclusion_id: string
        description: string
        source: string
        effect: "excludes_jurisdiction" | "reduces_scope"

    exceptions:
      - exception_id: string
        description: string
        source: string
        effect: string
```

## Metric types

| Value | Meaning |
|-------|---------|
| `revenue` | Aggregate turnover / net sales |
| `revenue_or_assets` | Larger of annual net sales or total assets (HSR-specific) |
| `deal_value` | Transaction value / consideration paid |
| `assets` | Total assets |
| `market_share` | Share of supply / market share (0.0–1.0) |
| `incremental_share` | Increment to share resulting from the transaction |

## Scope types

| Value | Meaning |
|-------|---------|
| `worldwide` | Global aggregate |
| `domestic` | Within the jurisdiction's territory |
| `eu_eea` | EU/EEA-wide |
| `eu_member_state` | Within a single EU Member State (used with count qualifier) |
| `single_member_state` | Any one Member State (used in exclusion tests) |
| `uk` | United Kingdom |
| `us` | United States |
| `eea_member_state` | EEA member state |

## Party types

| Value | Meaning |
|-------|---------|
| `combined` | All parties to the transaction together |
| `acquirer_group` | Acquiring group (including all affiliates) |
| `target_group` | Target group (including all affiliates) |
| `either_party` | Either acquirer or target (OR logic) |
| `each_party` | Each of the parties individually (AND logic — all must meet condition) |
| `each_of_at_least_two` | Each of at least two of the parties (used in EU tests) |

## Count qualifier

Used when a condition must be satisfied in a minimum number of countries:

```yaml
qualifier:
  type: "count_of_countries"
  operator: ">="
  count: 3
  country_set: "eu_member_states"   # or "eea_member_states", "all"
```

## Source type convention

Every condition must carry a `source_type` field. The four permitted values, in descending order of authority:

| Value | Meaning | Example |
|-------|---------|---------|
| `primary_legislation` | The statute or regulation itself | "Article 1(2) EC Merger Regulation" |
| `official_guidance` | Guidance published by the authority (not the legislature) | "CMA Mergers Guidance CMA2revised" |
| `authority_announcement` | Official press release or annual threshold notice | "FTC Federal Register notice effective 2026-02-17" |
| `practitioner` | Law firm alert, secondary database — not independently verified against primary source | "Skadden client alert Jan 2024" |

`primary_legislation` is the default. Only use `practitioner` where the primary source could not be directly accessed and the value was taken from a law firm summary; flag with a `note` explaining what needs direct verification.

Optionally include `source_url` (direct link to the source document) and `verified_via` (list of secondary URLs used to cross-check).

A single condition must not mix citation types — if a value is confirmed by both a statute and a press release, `source_type` should reflect the higher-authority source, with the secondary URL in `verified_via`.

Statements that would require mixed citations must be split into separate conditions.

---

## Scope section

Documents what types of transactions trigger the regime and how "concentration" is legally defined. All fields are optional but should be populated for completeness.

```yaml
scope:
  concentration_definition: >
    Verbatim or close paraphrase of the statutory definition of "concentration" or "merger".
  concentration_definition_source: "Article N, Act Name"
  concentration_definition_url: "https://..."   # direct link to the defining statutory article
  trigger_events:
    - merger                # full legal merger / amalgamation
    - share_acquisition     # acquisition of shares conferring control
    - asset_acquisition     # acquisition of business assets
    - joint_venture         # full-function JV (autonomous economic entity)
    - minority_stake        # minority without control (rare — only if explicitly in scope)
  control_threshold: >
    Description of the control standard (decisive influence, material influence, etc.)
  intra_group_exempt: true | false
  foreign_to_foreign_rule: >
    Whether pure foreign-to-foreign deals with domestic nexus are caught.
  substantive_test: "dominance" | "siec" | "slc" | "dominance_and_siec"
  substantive_test_note: >
    Explanation of what the test means in this jurisdiction, including any caveats.
  substantive_test_url: "https://..."   # link to the statutory provision setting the test
  note: >
    Any additional scope caveats (de minimis exceptions, sector carve-outs, etc.)
```

## Gun-jumping / standstill section

```yaml
gun_jumping:
  automatic_void: true | false          # is the transaction automatically void without clearance?
  voidable: true | false                # can the authority order it voided post-facto?
  max_fine_pct_turnover: 10.0           # e.g. 10.0 for 10% of worldwide turnover
  max_fine_fixed: 1000000               # fixed cap in max_fine_currency
  max_fine_currency: "EUR"
  per_day_fine: 50000                   # per-day fine (in max_fine_currency) if applicable
  criminal_sanctions: true | false
  legal_basis: "Article N, Act Name"    # human-readable citation
  legal_basis_url: "https://..."        # direct link to the standstill/penalty provision
  note: >
    Explanation of how the sanctions work in practice.
```

## FDI / national security screening section

```yaml
fdi_screening:
  applicable: true | false
  regime_name: "Name of the FDI screening law or regime"
  authority: "Ministry or body responsible"
  url: "https://..."              # authority or ministry website
  legislation_url: "https://..."  # direct link to the FDI screening statute
  sectors_covered:
    - defense
    - critical_infrastructure
    - sensitive_technology
    - energy
    - telecommunications
    - media
    - financial_infrastructure
    - healthcare
    - artificial_intelligence
    - semiconductors
    - space
    - nuclear
    - data
  note: >
    Key details: notification thresholds, review timelines, what constitutes "control"
    for FDI purposes, whether EU investors are covered, any phase-in/retroactive provisions.
```

## Source passages section

Verbatim statutory text that anchors one or more threshold conditions. Required for anti-hallucination verification.

```yaml
source_passages:
  - passage_id: "xx_actname_art_N"        # unique within the file; convention: jid_shortlaw_art_N
    document_title: "Full official title of the act or regulation"
    article_reference: "Article N" | "§ N" | "Section N"
    document_url: "https://..."            # direct link to the official text
    source_type: primary_legislation       # or official_guidance
    quoted_text: >
      "Verbatim English text (or official translation) of the relevant provision.
      Use quotation marks. If paraphrasing because exact text is unavailable, note that
      and use source_type: official_guidance or practitioner."
    supports_conditions:
      - condition_id_1
      - condition_id_2
```

## Filing fees section

```yaml
fees:
  structure: >
    Multi-line fee schedule (or "none" if no fees apply).
    Show bracket structure if tiered; indicate the currency and unit clearly.
  source: "Article N, Act Name"   # or "Authority fee schedule"
  source_type: primary_legislation | official_guidance | authority_announcement
  source_url: "https://..."       # direct link to the fee notice or statute
  annual_adjustment: true | false # true if fees are recalculated periodically
  note: >
    Practical filing note (e.g. when to verify current year's amount).
```
