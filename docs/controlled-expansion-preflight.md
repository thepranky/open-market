# Controlled Expansion Preflight — Batch 2

**Date:** 2026-06-03  
**Status:** Preflight complete — no canonical YAML created, no pipeline commands run.

---

## Summary table

| # | case_id (proposed) | Authority | Date | Stage | Outcome | PDF size | Ready |
|---|---|---|---|---|---|---|---|
| 1 | eu_cochlear_oticon_medical_2023 | EC M.10966 | 2023-10-09 | phase1 | cleared | ~126 KB | Yes |
| 2 | eu_viasat_inmarsat_2023 | EC M.10807 | 2023-05-25 | phase2 | cleared | ~1.2 MB | Yes |
| 3 | eu_booking_etraveli_2023 | EC M.10615 | 2023-09-25 | phase2 | blocked | ~5.6 MB | Yes |
| 4 | eu_orange_masmovil_2024 | EC M.10896 | 2024-02-20 | phase2 | cleared_with_conditions | >10 MB | Yes — flag large PDF |
| 5 | uk_viasat_inmarsat_2023 | CMA | 2023-05-10 | phase2 | cleared | 1.6 MB / 194 pp | Yes |
| 6 | us_tapestry_capri_2024 | SDNY | 2024-10-24 | federal_district_court | blocked | ~3.5 MB | Yes — note format |

All six source documents returned HTTP 200 from authoritative government domains. No ambiguity flags.

---

## Case details

### 1 · eu_cochlear_oticon_medical_2023

| Field | Value |
|---|---|
| case_id | eu_cochlear_oticon_medical_2023 |
| case_name | Cochlear / Oticon Medical |
| authority | European Commission |
| jurisdiction | EU |
| authority_reference | M.10966 |
| procedure_stage | phase1 |
| outcome | cleared |
| decision_date | 2023-10-09 |
| sector | medical devices / hearing implants |

**Source document**

- Case page: `https://competition-cases.ec.europa.eu/cases/M.10966`
- PDF (main decision): `https://ec.europa.eu/competition/mergers/cases1/202405/M_10966_9881563_2329_5.pdf`
- File size: ~126 KB (short Phase I non-opposition decision, ~10–20 pages)

**Scope note:** The notification covers only the cochlear implant (CI) business of Oticon Medical. The CMA separately prohibited the broader acquisition of the bone-conduction solutions business (June 2023) before this EC filing. The EC decision is therefore deliberately narrow in scope.

**Recommended focus modes**

1. `market_definition` — primary pass; cochlear implants market(s) by device type / geography
2. `outcome_metadata` — useful given short document; captures any Phase I competitive overlap screening

**Theories / remedies / unit_assessment:** Not needed. Phase I unconditional clearance — no SLC finding, no conditions.

**Proposed commands (not yet run)**
```bash
# from repo root
python apps/api/scripts/ingest_case.py \
    --case-id eu_cochlear_oticon_medical_2023 \
    --focus market_definition \
    --max-cost 0.50
```

---

### 2 · eu_viasat_inmarsat_2023

| Field | Value |
|---|---|
| case_id | eu_viasat_inmarsat_2023 |
| case_name | Viasat / Inmarsat |
| authority | European Commission |
| jurisdiction | EU |
| authority_reference | M.10807 |
| procedure_stage | phase2 |
| outcome | cleared |
| decision_date | 2023-05-25 |
| sector | satellite communications / broadband |

**Source document**

- Case page: `https://competition-cases.ec.europa.eu/cases/M.10807`
- PDF (Phase II decision): `https://ec.europa.eu/competition/mergers/cases1/202414/M_10807_9975023_3369_3.pdf`
- File size: ~1.2 MB

**Scope note:** Phase II opened 12 February 2023; cleared unconditionally May 2023. The investigation focused on satellite broadband and inflight connectivity. A sister CMA inquiry ran in parallel (see case 5 below).

**Recommended focus modes**

1. `market_definition` — satellite broadband, inflight connectivity, maritime and land-mobile segments
2. `theories` — Phase II investigation warrants theories pass even with unconditional clearance

**Theories / remedies / unit_assessment**

- Theories: **Yes** — Phase II requires a full theories pass to capture horizontal/vertical theories assessed and dismissed.
- Remedies: No — cleared unconditionally.
- unit_assessment: **Consider** — inflight connectivity markets may have per-route or per-orbit-type granularity; defer decision until market_definition draft is reviewed.

**Proposed commands (not yet run)**
```bash
python apps/api/scripts/ingest_case.py \
    --case-id eu_viasat_inmarsat_2023 \
    --focus market_definition \
    --max-cost 1.50

python apps/api/scripts/ingest_case.py \
    --case-id eu_viasat_inmarsat_2023 \
    --focus theories \
    --max-cost 1.00
```

---

### 3 · eu_booking_etraveli_2023

| Field | Value |
|---|---|
| case_id | eu_booking_etraveli_2023 |
| case_name | Booking Holdings / eTraveli |
| authority | European Commission |
| jurisdiction | EU |
| authority_reference | M.10615 |
| procedure_stage | phase2 |
| outcome | blocked |
| decision_date | 2023-09-25 |
| sector | travel / online travel agencies / digital platforms |

**Source document**

- Case page: `https://competition-cases.ec.europa.eu/cases/M.10615`
- PDF (Phase II prohibition decision): `https://ec.europa.eu/competition/mergers/cases1/202451/M_10615_10430872_121034_7.pdf`
- File size: ~5.6 MB (substantial — prohibition decisions are typically long)
- Press release: `https://ec.europa.eu/commission/presscorner/detail/en/ip_23_4573`

**Scope note:** First EC prohibition of a digital-platform deal under the revised merger framework. Core concern was Booking's gatekeeper position in hotel accommodations and flight OTA's potential to entrench that position. Decision includes a rejected remedies package.

**Recommended focus modes**

1. `market_definition` — accommodation OTA, flight OTA, metasearch, and their geographic scopes
2. `theories` — theory of harm (conglomerate / portfolio effects) is central to this prohibition
3. `remedies` — remedies package was proposed and rejected; worth capturing as a data point

**Theories / remedies / unit_assessment**

- Theories: **Yes** — prohibition decision; full SLC / theories of harm analysis documented.
- Remedies: **Yes** — rejected behavioural/structural remedies are part of the decision record.
- unit_assessment: **Consider** — OTA markets may segment by destination country; defer until market_definition draft reviewed.

**Proposed commands (not yet run)**
```bash
python apps/api/scripts/ingest_case.py \
    --case-id eu_booking_etraveli_2023 \
    --focus market_definition \
    --max-cost 2.00

python apps/api/scripts/ingest_case.py \
    --case-id eu_booking_etraveli_2023 \
    --focus theories \
    --max-cost 1.50

python apps/api/scripts/ingest_case.py \
    --case-id eu_booking_etraveli_2023 \
    --focus remedies \
    --max-cost 1.00
```

---

### 4 · eu_orange_masmovil_2024

| Field | Value |
|---|---|
| case_id | eu_orange_masmovil_2024 |
| case_name | Orange / MasMovil |
| authority | European Commission |
| jurisdiction | EU |
| authority_reference | M.10896 |
| procedure_stage | phase2 |
| outcome | cleared_with_conditions |
| decision_date | 2024-02-20 |
| sector | telecoms / mobile |

**Source document**

- Case page: `https://competition-cases.ec.europa.eu/cases/M.10896`
- PDF (Phase II conditional clearance): `https://ec.europa.eu/competition/mergers/cases1/202426/M_10896_10132275_5929_5.pdf`
- File size: **>10 MB** (fetch limit exceeded; likely 200+ pages)

**Scope note:** Four-to-three mobile consolidation in Spain (Orange + MasMovil). Cleared after commitments to divest 60 MHz spectrum assets to Digi Communications and offer an optional national roaming agreement. Statement of Objections was issued during Phase II.

**Large-PDF flag:** File exceeds the 10 MB fetch threshold. Likely comparable in length to Bayer/Monsanto (1006 pages) or Microsoft/Activision. A page-range planning pass should be run before full extraction to avoid runaway cost.

**Recommended focus modes**

1. `market_definition` — retail mobile, wholesale access, fixed-mobile convergence, spectrum bands
2. `theories` — horizontal SLC in retail mobile; access foreclosure concerns
3. `remedies` — spectrum divestiture + roaming access commitment

**Theories / remedies / unit_assessment**

- Theories: **Yes** — Phase II with SOO; horizontal and vertical theories documented.
- Remedies: **Yes** — structural (spectrum divestiture) and behavioural (roaming) remedies accepted.
- unit_assessment: **Yes** — telecom cases typically segment by service type (prepaid/postpaid), spectrum band (700/800/2100/3500 MHz), and possibly geography (regional coverage); unit_assessment batch runner is appropriate.

**Proposed commands (not yet run)**
```bash
# Step 0: plan extraction ranges before committing cost
python apps/api/scripts/plan_extraction_ranges.py \
    --case-id eu_orange_masmovil_2024

# Step 1: market definition (run after range planning)
python apps/api/scripts/ingest_case.py \
    --case-id eu_orange_masmovil_2024 \
    --focus market_definition \
    --max-cost 2.00

# Step 2: theories + remedies (after market_definition draft reviewed)
python apps/api/scripts/ingest_case.py \
    --case-id eu_orange_masmovil_2024 \
    --focus theories \
    --max-cost 1.50

python apps/api/scripts/ingest_case.py \
    --case-id eu_orange_masmovil_2024 \
    --focus remedies \
    --max-cost 1.00

# Step 3: unit assessment batch (spectrum bands / service types)
python apps/api/scripts/run_unit_assessment_batch.py \
    --case-id eu_orange_masmovil_2024 \
    --max-units 10 \
    --max-cost 3.00
```

---

### 5 · uk_viasat_inmarsat_2023

| Field | Value |
|---|---|
| case_id | uk_viasat_inmarsat_2023 |
| case_name | Viasat / Inmarsat (CMA) |
| authority | CMA |
| jurisdiction | UK |
| authority_reference | ME/6997/22 |
| procedure_stage | phase2 |
| outcome | cleared |
| decision_date | 2023-05-10 |
| sector | satellite communications / inflight connectivity |

**Source document**

- Case page: `https://www.gov.uk/cma-cases/viasat-slash-inmarsat-merger-inquiry`
- PDF (Final Report): `https://assets.publishing.service.gov.uk/media/645b8da5c6e897000ca0fc92/Final_report._A.pdf`
- Appendices PDF: `https://assets.publishing.service.gov.uk/media/645b8dbec6e8970012a0fc85/A._Appendices_and_glossary.pdf`
- File size: 1.6 MB / 194 pages (main report)

**Scope note:** CMA Phase 2 inquiry ran in parallel with EC M.10807. The CMA found no SLS (substantial lessening of competition) in inflight connectivity services and cleared unconditionally. The main report and a separate appendices/glossary document are both available.

**Recommended focus modes**

1. `market_definition` — inflight connectivity (IFC), aviation broadband, maritime satcom
2. `theories` — Phase 2 full investigation; horizontal overlap theories assessed and dismissed

**Theories / remedies / unit_assessment**

- Theories: **Yes** — Phase 2 with full theories analysis documented (even absent SLS finding).
- Remedies: No — cleared unconditionally; no undertakings.
- unit_assessment: **Consider** — IFC may segment by aviation vs maritime, or by orbit type (GEO/MEO/LEO); defer until market_definition draft reviewed.

**Proposed commands (not yet run)**
```bash
python apps/api/scripts/ingest_case.py \
    --case-id uk_viasat_inmarsat_2023 \
    --focus market_definition \
    --max-cost 1.50

python apps/api/scripts/ingest_case.py \
    --case-id uk_viasat_inmarsat_2023 \
    --focus theories \
    --max-cost 1.00
```

---

### 6 · us_tapestry_capri_2024

| Field | Value |
|---|---|
| case_id | us_tapestry_capri_2024 |
| case_name | FTC v Tapestry / Capri |
| authority | SDNY |
| jurisdiction | US |
| authority_reference | 1:24-cv-03109 |
| procedure_stage | federal_district_court |
| outcome | blocked |
| decision_date | 2024-10-24 |
| sector | consumer goods / luxury fashion / handbags |

**Source document**

- Case page (FTC docket): `https://www.ftc.gov/legal-library/browse/cases-proceedings/231-0133-tapestry-inccapri-holdings-limited-matter`
- PDF (SDNY court opinion): `https://www.nysd.uscourts.gov/sites/default/files/2024-11/FTC%20V%20Tapestry.pdf`
- File size: ~3.5 MB
- Judge: Jennifer L. Rochon (SDNY)

**Scope note:** FTC obtained a preliminary injunction (15 U.S.C. § 53(b)) blocking the combination of Tapestry (Coach, Kate Spade) and Capri (Michael Kors, Versace, Jimmy Choo). Court accepted the FTC's "accessible luxury handbags" product market. Deal abandoned post-injunction; no trial on the merits. The authoritative document is the court opinion on the SDNY domain, not an FTC agency decision — document structure differs from EC/CMA decisions (legal opinion format with factual findings, legal analysis, and order). The FTC.gov case page returns 403; use the court URL.

**Recommended focus modes**

1. `market_definition` — "accessible luxury handbags" novel market definition; price-tier segmentation
2. `theories` — horizontal overlap theory (head-to-head competition between Coach/Kate Spade and Michael Kors)

**Theories / remedies / unit_assessment**

- Theories: **Yes** — court opinion contains detailed antitrust analysis and findings of fact on theories of harm.
- Remedies: No — deal abandoned after PI; no accepted remedies.
- unit_assessment: **Consider** — handbag market segments by brand tier, price point, occasion; defer to after market_definition draft.

**Format caveat:** US district court opinions follow a legal-opinion structure rather than an agency merger decision structure. The extraction prompt may need to accommodate "findings of fact and conclusions of law" framing. Monitor Stage 4 (source integrity) carefully on first run.

**Proposed commands (not yet run)**
```bash
python apps/api/scripts/ingest_case.py \
    --case-id us_tapestry_capri_2024 \
    --focus market_definition \
    --max-cost 1.50

python apps/api/scripts/ingest_case.py \
    --case-id us_tapestry_capri_2024 \
    --focus theories \
    --max-cost 1.00
```

---

## Cross-cutting flags

### Large PDF — eu_orange_masmovil_2024
PDF exceeds 10 MB fetch limit. Run `plan_extraction_ranges.py` before any extraction pass to get page-range windows. Budget accordingly; expect 3–5 extraction passes similar to Bayer/Monsanto.

### Format divergence — us_tapestry_capri_2024
Court opinion format (legal findings + order) rather than an agency merger decision. The standard extraction prompts are calibrated to regulatory decision language; watch Stage 4 integrity scores on the first pass and be prepared to adjust passage extraction if quote grounding fails.

### Parallel satellite cases — eu_viasat_inmarsat_2023 + uk_viasat_inmarsat_2023
Two decisions on the same transaction from different regulators. Ingest them independently; they should produce separate canonical records. Useful for cross-jurisdictional comparison once both are promoted.

### Suggested ingestion order
Complexity/cost ordering: easiest → hardest:

1. eu_cochlear_oticon_medical_2023 (short, Phase I, narrow)
2. uk_viasat_inmarsat_2023 (194 pp, Phase 2, cleared, familiar CMA format)
3. eu_viasat_inmarsat_2023 (Phase II, cleared, ~1.2 MB)
4. us_tapestry_capri_2024 (court opinion, novel format)
5. eu_booking_etraveli_2023 (prohibition, ~5.6 MB, three focus passes)
6. eu_orange_masmovil_2024 (>10 MB, remedies, unit assessment — highest cost)
