"""Insert minority_thresholds blocks into jurisdiction YAML files."""

import re
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "jurisdictions"

# Each block is keyed by jurisdiction_id.
# operator: must be ">=" or ">" only (schema constraint).
# pct_threshold: null is fine.
# rights_required: null | "board_seat" | "veto_ordinary" | "veto_strategic"

BLOCKS: dict[str, str] = {

# ── Americas ─────────────────────────────────────────────────────────────────

"us_hsr": """\
minority_thresholds:
  applies: true
  standard: "any_acquisition"
  note: >
    The HSR Act is transaction-value driven and does not create a separate "minority
    acquisition" category. Any acquisition of voting securities is potentially
    notifiable if the size-of-transaction and size-of-person tests are met.
    Two passive exemptions carve out most purely financial minority investments:
    (1) 16 C.F.R. § 802.9 — the general passive exemption exempts acquisitions
    resulting in ≤10% of outstanding voting securities held 'solely for investment'
    (no intent to participate in business decisions). (2) 16 C.F.R. § 802.64 —
    institutional investors may hold up to 15% in the ordinary course of business
    solely for investment. Both exemptions are forfeited upon activist engagement
    (director nomination, strategy input, proxy contest). Once forfeited, even a
    single additional share can require filing. There is no investment-only exemption
    for stakes over 10% (general) or 15% (institutional). Foreign minority investors
    should also assess CFIUS separately — CFIUS applies to TID US business investments
    at 10%+ independently of HSR.
  rules: []
""",

"ca": """\
minority_thresholds:
  applies: true
  standard: "percentage_based"
  note: >
    Canada's Competition Act Part IX sets explicit share-crossing thresholds for both
    minority and majority acquisitions. The initial minority threshold differs between
    public (listed) and private companies. Crossing each threshold is a separate
    notifiable event if the size-of-parties (combined CAD 400m revenues or assets in
    Canada) and size-of-target (CAD 93m in 2024, adjusted annually) tests are also met.
    Bill C-59 (June 2024) enhanced gun-jumping penalties but did not alter the
    20%/35%/50% thresholds. Where the acquirer already holds above the minority
    threshold, only the 50% crossing triggers a fresh notification.
  rules:
    - rule_id: "ca_minority_public"
      relationship_type: "any"
      pct_threshold: 20.0
      operator: ">="
      rights_required: null
      source: "Competition Act, R.S.C. 1985, c. C-34, s. 110(3)(a)"
      source_type: "primary_legislation"
      source_url: "https://laws-lois.justice.gc.ca/eng/acts/C-34/page-21.html"
      note: >
        Acquisition resulting in the acquirer holding 20% or more of the voting shares
        of a public corporation (listed on a Canadian or foreign stock exchange) is
        notifiable if size-of-parties and size-of-target tests are met.
    - rule_id: "ca_minority_private"
      relationship_type: "any"
      pct_threshold: 35.0
      operator: ">="
      rights_required: null
      source: "Competition Act, R.S.C. 1985, c. C-34, s. 110(3)(b)"
      source_type: "primary_legislation"
      source_url: "https://laws-lois.justice.gc.ca/eng/acts/C-34/page-21.html"
      note: >
        Acquisition resulting in the acquirer holding 35% or more of the voting shares
        of a private corporation (not listed on any stock exchange) is notifiable if
        size-of-parties and size-of-target tests are met.
    - rule_id: "ca_majority"
      relationship_type: "any"
      pct_threshold: 50.0
      operator: ">"
      rights_required: null
      source: "Competition Act, R.S.C. 1985, c. C-34, s. 110(3)(c)"
      source_type: "primary_legislation"
      source_url: "https://laws-lois.justice.gc.ca/eng/acts/C-34/page-21.html"
      note: >
        Crossing 50% of voting shares is separately notifiable even if the prior
        minority threshold was already notified. Same size-of-parties and
        size-of-target tests apply.
""",

"br": """\
minority_thresholds:
  applies: true
  standard: "percentage_based"
  note: >
    Brazil's minority stake rules are set by CADE Resolution No. 33/2022, which
    operationalises Article 90 of Lei No. 12.529/2011. The regime uses a bifurcated
    percentage threshold depending on whether the acquirer and target are in a
    horizontal (competitor) or vertical (supply chain) relationship, or not. Thresholds
    are cumulative — prior holdings count toward the trigger. The standard BRL 750m +
    BRL 75m monetary thresholds (Article 88, Lei 12.529/2011) must also be met.
    There is no investment-only exemption analogous to the US HSR 802.9 rule.
    Brazil is the key Latin American jurisdiction where even small competitor stakes
    trigger mandatory filing obligations.
  rules:
    - rule_id: "br_minority_horizontal_vertical"
      relationship_type: "horizontal"
      pct_threshold: 5.0
      operator: ">="
      rights_required: null
      source: "CADE Resolution No. 33/2022, Article 9; Lei No. 12.529/2011, Article 90"
      source_type: "official_guidance"
      source_url: "https://www.gov.br/cade/en"
      note: >
        Acquisition of 5% or more of the total capital or voting shares is notifiable
        where the acquirer group and the target are in a horizontal (competing) or
        vertical (supply chain) relationship. Cumulative holdings are aggregated across
        related transactions. The 5% threshold reflects CADE's view that even small
        competitor stakes raise coordination and transparency concerns.
    - rule_id: "br_minority_non_horizontal"
      relationship_type: "non_horizontal"
      pct_threshold: 20.0
      operator: ">="
      rights_required: null
      source: "CADE Resolution No. 33/2022, Article 9; Lei No. 12.529/2011, Article 90"
      source_type: "official_guidance"
      source_url: "https://www.gov.br/cade/en"
      note: >
        Acquisition of 20% or more of the total capital or voting shares is notifiable
        where there is no horizontal or vertical relationship between the acquirer group
        and the target (conglomerate / unrelated acquisition). This mirrors the economic
        group definition under which a 20% holder is included in the economic group for
        Brazilian turnover calculation purposes.
""",

"mx": """\
minority_thresholds:
  applies: true
  standard: "any_acquisition"
  note: >
    Mexico does not carve out minority acquisitions from merger control under the
    Federal Antitrust Law (LFCE), now enforced by the Comisión Nacional Antimonopolio
    (CNA) following the July 2025 reform. Any acquisition of shares, assets, or rights
    meeting the monetary value threshold (~USD 95.9m as of July 2025, set as multiples
    of the UMA) requires prior notification regardless of the percentage of capital
    acquired. The sole meaningful minority exemption applies to acquisitions in publicly
    listed companies where: (a) the resulting stake is below 10% of issued capital; AND
    (b) the acquirer obtains no board appointment rights, no 10%+ voting rights, and no
    ability to directly or indirectly influence administration, strategy, or key policies.
    Both conditions must be satisfied simultaneously — a board seat right at even 8%
    destroys the exemption.
  rules:
    - rule_id: "mx_minority_listed_exception"
      relationship_type: "any"
      pct_threshold: 10.0
      operator: ">="
      rights_required: null
      source: "LFCE Article 86, paragraph 3 (as amended July 2025)"
      source_type: "primary_legislation"
      source_url: "https://www.dof.gob.mx/"
      note: >
        Below 10% of issued capital of a listed company AND no influence rights =
        exempt from notification. Above 10%, or below 10% with any governance rights
        (board appointment, 10%+ voting, influence over strategy), the full Article 86
        monetary threshold test applies. The exemption is narrow and must be construed
        strictly. For unlisted companies, no percentage-based exemption exists.
""",

"ar": """\
minority_thresholds:
  applies: true
  standard: "material_influence"
  note: >
    Argentina's merger control under Law 27.442 (in force May 2018, enforced by the
    National Competition Authority / ANC from November 2025) extends to any acquisition
    giving the acquirer 'control or substantial influence' (control o influencia
    sustancial) over the target. No explicit statutory percentage thresholds exist for
    minority acquisitions — the test is qualitative, assessing whether the stake grants
    the ability to influence strategic or commercial decisions. The monetary threshold
    (100,000,000 Adjustable Units, approximately ARS 110.2bn / USD 104.7m as of
    February 2025, adjusted annually) must also be met. A purely passive minority stake
    with no governance rights has generally not been treated as notifiable even where
    the monetary threshold is met.
  rules:
    - rule_id: "ar_minority_substantial_influence"
      relationship_type: "any"
      pct_threshold: null
      operator: ">="
      rights_required: "veto_strategic"
      source: "Law 27.442, Article 7; Decree 480/2018"
      source_type: "primary_legislation"
      source_url: "https://www.argentina.gob.ar/normativa/nacional/ley-27442-313411"
      note: >
        Law 27.442 Article 7 defines 'economic concentration' to include acquisitions
        conferring 'control or substantial influence' over an undertaking. Substantial
        influence is assessed qualitatively: minority stakes with veto rights over
        strategic decisions (pricing, investment, business plan) are treated as
        conferring substantial influence and are notifiable. Purely passive financial
        minority stakes with no governance rights have generally not been treated as
        notifiable by the CNDC/ANC.
""",

"cl": """\
minority_thresholds:
  applies: true
  standard: "percentage_based"
  note: >
    Chile operates a dual-track system: (i) the standard pre-closing mandatory
    clearance regime for full concentrations under DL 211, Article 47 et seq. (as
    amended by Law 20.945/2016); and (ii) a distinct post-closing mandatory
    notification obligation for minority acquisitions of more than 10% of a
    competing company's equity under DL 211, Article 4 bis (in force November 2021).
    The Article 4 bis notification is informational — filing is post-closing (within
    60 days) and does not block the transaction. The monetary threshold for the
    minority notification is low (UF 100,000 annual revenues for each party,
    approximately USD 4m / CLP 3.5bn), reached by most businesses of meaningful size.
    The FNE actively uses these notifications as intelligence inputs.
  rules:
    - rule_id: "cl_minority_horizontal_postclosing"
      relationship_type: "horizontal"
      pct_threshold: 10.0
      operator: ">"
      rights_required: null
      source: "DL 211, Article 4 bis (inserted by Law 20.945/2016; in force November 2021)"
      source_type: "primary_legislation"
      source_url: "https://www.fne.gob.cl/wp-content/uploads/2018/09/DL_211_English.pdf"
      note: >
        Acquirer (or any member of its business group) that acquires a direct or
        indirect participation of more than 10% of the capital of a competing company
        must notify the FNE within 60 days of completion. Both the acquirer group and
        the target must each have annual revenues on sales in Chile exceeding UF 100,000
        (~USD 4m). Successive acquisitions are aggregated — the obligation arises when
        total holding first exceeds 10%. 'Competing company' is interpreted broadly by
        the FNE to include potential or indirect competitors.
""",

"co": """\
minority_thresholds:
  applies: true
  standard: "material_influence"
  note: >
    Colombia's merger control under Law 1340/2009 (enforced by the SIC) applies a
    broad 'control' test capturing any acquisition granting direct or indirect
    influence over the target's corporate policy, strategy, or key asset disposal,
    regardless of the percentage of shares acquired. The statute defines control to
    include negative control (veto rights over strategic decisions) and factual
    influence. No explicit statutory percentage thresholds for minority acquisitions.
    Whether a qualifying transaction requires prior SIC approval (as opposed to
    mere post-implementation notification) depends on whether the combined market
    share in any relevant market reaches 20%. The UVT-based monetary threshold
    (approximately COP 77.2bn / USD 19.3m in 2024) must also be met.
  rules:
    - rule_id: "co_minority_material_influence"
      relationship_type: "any"
      pct_threshold: null
      operator: ">="
      rights_required: "veto_strategic"
      source: "Law 1340/2009, Article 9; SIC Circular Única, Title VIII"
      source_type: "primary_legislation"
      source_url: "https://www.sic.gov.co/integraciones-empresariales"
      note: >
        A transaction grants 'control' when the acquirer obtains the direct or indirect
        ability to influence corporate policy (including pricing, investment, strategy),
        initiate or terminate business activities, or manage assets essential to the
        target. Negative control (veto over strategic decisions) is expressly included
        even for minority stakes. No percentage floor — purely qualitative. A 15% stake
        with board seat and veto over the business plan may be caught; a 40% stake with
        purely financial rights may not be. Colombia does not have a passive investment
        exemption.
""",

"pe": """\
minority_thresholds:
  applies: false
  standard: "control_based"
  note: >
    Peru's merger control law (Law No. 31112, in force June 2021, enforced by INDECOPI)
    requires prior notification and clearance only for acquisitions resulting in 'control'
    over an economic agent, defined as the power to exercise 'lasting and decisive
    influence' (influencia duradera y determinante) over the target's governing bodies or
    competitive strategy. Minority acquisitions that do not confer such decisive influence
    are expressly excluded. There are no percentage-based thresholds and no post-closing
    minority notification regime. INDECOPI has published limited decisional practice —
    analysis of what constitutes decisive influence relies primarily on the statute and
    Supreme Decree No. 039-2021-PCM. Sector-specific regulators (banking, insurance,
    telecoms) may impose additional approval requirements at thresholds below the INDECOPI
    control standard.
  rules:
    - rule_id: "pe_minority_control_only"
      relationship_type: "any"
      pct_threshold: null
      operator: ">="
      rights_required: "veto_strategic"
      source: "Law No. 31112, Article 5; Supreme Decree No. 039-2021-PCM (Regulation)"
      source_type: "primary_legislation"
      source_url: "https://www.indecopi.gob.pe/web/control-de-fusiones"
      note: >
        Notification is required only on acquisition of 'control' — the power to exercise
        lasting and decisive influence over the target's governing bodies, directly or
        indirectly affecting competitive strategy. A minority stake with veto rights over
        strategic decisions in a shareholder agreement may constitute control even for a
        minority holder. Purely passive minority stakes without governance rights are
        entirely outside the regime.
""",

# ── EU Core ──────────────────────────────────────────────────────────────────

"eu": """\
minority_thresholds:
  applies: false
  standard: "control_based"
  note: >
    The EUMR (Regulation 139/2004) catches only concentrations — defined under Article 3
    as acquisitions of control (sole or joint) conferring the ability to exercise decisive
    influence on a lasting basis. Non-controlling minority shareholdings are NOT caught,
    regardless of size. The Commission's 2014 White Paper proposed a transparency system
    for non-controlling minority stakes but this was never legislated. A minority stake
    can constitute a concentration if it confers de facto sole control (e.g. dispersed
    remaining shareholders — Vivendi/Telecom Italia: 29.94% = de facto sole control) or
    negative joint control (strategic veto rights over business plan, budget, management
    appointments). The EC Consolidated Jurisdictional Notice (2008/C 95/01) paragraphs
    54–67 set out the control analysis framework used across the EU.
  rules:
    - rule_id: "eu_minority_de_facto_sole"
      relationship_type: "any"
      pct_threshold: null
      operator: ">="
      rights_required: null
      source: "EUMR Art. 3(2); EC Consolidated Jurisdictional Notice (2008/C 95/01) paras. 54–60"
      source_type: "official_guidance"
      source_url: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:52008XC0416(03)"
      note: >
        A minority stake without a formal majority can confer de facto sole control where
        the remaining shareholding is so widely dispersed that no other shareholder can
        achieve a blocking minority in practice. Assessment is entirely qualitative — no
        fixed percentage. Example: Vivendi/Telecom Italia (2017): 29.94% = de facto sole
        control due to atomised remaining shareholders.
    - rule_id: "eu_minority_negative_control"
      relationship_type: "any"
      pct_threshold: null
      operator: ">="
      rights_required: "veto_strategic"
      source: "EUMR Art. 3(2); Consolidated Jurisdictional Notice paras. 62–67"
      source_type: "official_guidance"
      source_url: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:52008XC0416(03)"
      note: >
        A minority shareholder holding veto rights over strategic decisions — business
        plan approval, major capex, budget, or appointment of senior management — acquires
        joint control (negative control). The vetoes must cover strategy, not day-to-day
        management. 'Protective' vetoes (anti-dilution, related-party transactions) do not
        confer control. This IS a notifiable concentration under the EUMR if turnover
        thresholds are met.
""",

"de": """\
minority_thresholds:
  applies: true
  standard: "percentage_based"
  note: >
    Germany operates two distinct minority triggers under §37(1) GWB — both broader than
    the EUMR control standard. §37(1) No. 3: a bare acquisition of 25% or more of capital
    OR voting rights is a concentration per se — no control, veto rights, or plus factors
    required. §37(1) No. 4: any arrangement below 25% that confers 'competitively
    significant influence' (wettbewerblich erheblicher Einfluss) is also a concentration,
    assessed via a plus-factors test requiring a competitive nexus between the parties.
    Both tests feed into the §35 turnover thresholds (combined worldwide >EUR 500m, German
    domestic >EUR 50m for one party, >EUR 17.5m for another) or the §35(1a) transaction-
    value test (deal value >EUR 400m with significant domestic activities). Germany has the
    broadest minority acquisition jurisdiction of any major EU state. The 10th GWB Amendment
    (2021) confirmed §37(1) No. 4 for digital platform contexts.
  rules:
    - rule_id: "de_minority_25pct"
      relationship_type: "any"
      pct_threshold: 25.0
      operator: ">="
      rights_required: null
      source: "§37(1) No. 3 GWB (Gesetz gegen Wettbewerbsbeschränkungen)"
      source_type: "primary_legislation"
      source_url: "https://www.gesetze-im-internet.de/englisch_gwb/englisch_gwb.html"
      note: >
        Acquisition of shares equalling or exceeding 25% of capital OR voting rights
        triggers a notifiable concentration regardless of whether control or influence is
        actually obtained. Existing group shareholdings are aggregated. Financial institutions
        acquiring shares for resale within 12 months without exercising voting rights are
        exempt (§37(1) No. 3 proviso). This is unique among EU jurisdictions — the 25% test
        requires NO additional rights or control.
    - rule_id: "de_minority_competitive_influence"
      relationship_type: "horizontal"
      pct_threshold: null
      operator: ">="
      rights_required: null
      source: "§37(1) No. 4 GWB; FCO Guidance on Competitively Significant Influence"
      source_type: "primary_legislation"
      source_url: "https://www.gesetze-im-internet.de/englisch_gwb/englisch_gwb.html"
      note: >
        For stakes below 25%, a concentration arises if the acquirer obtains 'competitively
        significant influence' — the ability to influence the commercial policy and competitive
        behaviour of the target. Requires: (a) plus factors such as board representation
        rights, veto/voting rights, information rights on operative business, options,
        personal links, or cooperation agreements; AND (b) a competitive nexus — the acquirer
        must compete with the target, control a target competitor, or have a significant
        vertical supply relationship. Confirmed for digital platforms in 10th GWB Amendment
        (2021). Recent examples: DFL/Dyn Media (6.5% stake triggered); Lufthansa/airBaltic
        (10% + wet-lease rights triggered).
""",

"fr": """\
minority_thresholds:
  applies: false
  standard: "control_based"
  note: >
    France follows a pure decisive-influence / control standard under Article L430-1 of the
    Code de Commerce. There are no special minority-specific thresholds — non-controlling
    minority interests are not subject to merger control. Notification is required only when
    an acquisition results in a change of control on a lasting basis. A minority stake can
    achieve this through veto rights over strategic decisions, joint voting agreements, or
    de facto control arising from dispersed remaining shareholding. The Autorité de la
    concurrence applies the EC Consolidated Jurisdictional Notice by analogy. Protective/
    minority investor vetoes (anti-dilution, tag/drag, related-party transaction limits)
    typically do not confer control.
  rules:
    - rule_id: "fr_minority_decisive_influence"
      relationship_type: "any"
      pct_threshold: null
      operator: ">="
      rights_required: "veto_strategic"
      source: "Article L430-1, Code de Commerce"
      source_type: "primary_legislation"
      source_url: "https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000006231929/"
      note: >
        A minority stake triggers notification only if it confers the ability to exercise
        decisive influence on a lasting basis: (1) veto rights over strategic decisions
        (business plan, budget, management appointments, major capex); (2) joint control
        through voting agreements enabling blocking or direction of key decisions; (3) de
        facto sole or joint control based on dispersed shareholder structure. No fixed
        percentage threshold. Purely financial minority stakes without influence rights
        are not notifiable.
""",

"it": """\
minority_thresholds:
  applies: false
  standard: "control_based"
  note: >
    Italian merger control under Law 287/1990 follows the EU decisive-influence / control
    standard (Article 7 of Law 287/1990). There are no special percentage-based minority
    triggers. Minority shareholdings are caught only when they confer control (sole or
    joint) — the ability to exercise decisive influence over the target's strategic
    commercial decisions. A minority stake can confer joint control via shareholders'
    agreements or veto rights over strategic decisions, or sole control in cases of widely
    dispersed remaining shareholding. The AGCM may call in below-threshold transactions
    within 30 days of completion where competition concerns arise (Article 16(1-bis), 2022),
    though this is a general competition power, not minority-specific. Financial institutions
    are exempt if they hold shares for resale within 24 months without exercising voting
    rights (Article 5(2) Law 287/1990).
  rules:
    - rule_id: "it_minority_decisive_influence"
      relationship_type: "any"
      pct_threshold: null
      operator: ">="
      rights_required: "veto_strategic"
      source: "Law 287/1990, Articles 5(1) and 7; AGCM procedural guidance"
      source_type: "primary_legislation"
      source_url: "https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:legge:1990-10-10;287"
      note: >
        A minority stake triggers notification only when it confers control — the ability
        to exercise decisive influence over the target's strategic commercial decisions.
        Control arises through: (1) veto powers over strategic decisions via shareholders'
        agreements; (2) de facto control where remaining shares are widely dispersed; (3)
        joint control through contractual or structural arrangements. No fixed percentage
        floor. Financial institution carve-out (Art. 5(2)): exempt for stakes held purely
        for resale within 24 months where voting rights are not exercised.
""",

"es": """\
minority_thresholds:
  applies: false
  standard: "control_based"
  note: >
    Spain follows a decisive-influence / control standard under Article 7 of the Ley de
    Defensa de la Competencia (LDC). There are no percentage-based minority triggers.
    Non-controlling minority interests are not notifiable. Spain also has a market share-
    based notification trigger (Article 8 LDC): the CNMC has jurisdiction if the parties'
    combined Spanish market share reaches 30% in any affected market, regardless of
    turnover. However, this market share gate requires a qualifying concentration (i.e.,
    a control change) — it does NOT catch non-controlling minority acquisitions regardless
    of post-combination market share. A de minimis exemption applies: no notification if
    the target's Spanish turnover or acquired assets are below EUR 10m AND combined market
    share does not reach 50%.
  rules:
    - rule_id: "es_minority_decisive_influence"
      relationship_type: "any"
      pct_threshold: null
      operator: ">="
      rights_required: "veto_strategic"
      source: "LDC Article 7(2) (Ley 15/2007 de Defensa de la Competencia)"
      source_type: "primary_legislation"
      source_url: "https://www.boe.es/buscar/act.php?id=BOE-A-2007-12946"
      note: >
        Control under Article 7(2) LDC arises from contracts, rights, or any other means
        (factual or legal) conferring decisive influence over the target's strategic
        commercial decisions. A minority shareholding triggers notification only when it
        confers decisive influence through veto rights over strategic decisions, board
        control, or de facto power arising from dispersed remaining shareholding. Pure
        financial minority investments without influence rights are not notifiable.
""",

"nl": """\
minority_thresholds:
  applies: false
  standard: "control_based"
  note: >
    The Netherlands applies a pure decisive-influence / control standard under Articles 27
    and 29 of the Mededingingswet (Mw). Minority shareholdings below 50% are only notifiable
    if they lead to a change of control, defined as the ability to exercise decisive influence
    on a lasting basis over the strategic commercial decisions of the target. The ACM
    interprets this in line with the EU Merger Regulation and the EC's Consolidated
    Jurisdictional Notice. Non-controlling minority interests are not caught. As of 2026,
    draft legislation to grant the ACM call-in powers for below-threshold transactions is
    advancing in Dutch Parliament — this is a general tool, not minority-specific, and is
    not yet in force. Healthcare sector transactions also require parallel NZa (Netherlands
    Healthcare Authority) notification under the WMG, with lower thresholds. The EU
    one-stop-shop applies: no Dutch filing required if EUMR thresholds are met.
  rules:
    - rule_id: "nl_minority_decisive_influence"
      relationship_type: "any"
      pct_threshold: null
      operator: ">="
      rights_required: "veto_strategic"
      source: "Mededingingswet Article 27 (concentration definition); Article 29 (notification)"
      source_type: "primary_legislation"
      source_url: "https://wetten.overheid.nl/BWBR0008691"
      note: >
        A minority shareholding triggers notification only if it confers 'decisive influence'
        — the ability to determine strategic decisions (not day-to-day management) of the
        target. This includes negative control via strategic veto rights (over business
        plan, budget, major investments, senior management appointments), de facto sole
        control in dispersed-shareholding structures, and joint control through contractual
        arrangements. No fixed percentage threshold. Dutch thresholds (Art. 29 Mw): combined
        worldwide >EUR 150m AND each of ≥2 parties Dutch domestic >EUR 30m.
""",

"be": """\
minority_thresholds:
  applies: false
  standard: "control_based"
  note: >
    Belgium applies a decisive-influence / control standard under Article IV.7 of the Code
    of Economic Law (CEL), Book IV. There are no fixed percentage thresholds for minority
    shareholdings. Non-controlling minority interests do not trigger notification. The BCA
    applies a broad contextual analysis: Picanol NV/Tessenderlo Chemie NV (BCA 2013-C/C-01)
    established that a 27.6% stake can constitute de facto sole control where remaining
    shares are dispersed among a large number of shareholders. The CEL control definition
    (Art. IV.6(3)–(4)) encompasses any factual or legal means conferring decisive influence.
    Financial institutions acquiring for resale are not automatically exempt — assess case-
    by-case. Belgian thresholds (Art. IV.8 CEL): combined worldwide >EUR 100m AND each of
    ≥2 parties Belgian domestic >EUR 40m.
  rules:
    - rule_id: "be_minority_decisive_influence"
      relationship_type: "any"
      pct_threshold: null
      operator: ">="
      rights_required: null
      source: "CEL Article IV.7 (concentration); Art. IV.6(3)–(4) (control definition)"
      source_type: "primary_legislation"
      source_url: "https://www.belgiancompetition.be/en/mergers"
      note: >
        A minority stake triggers notification if it confers decisive influence — the ability
        to exercise decisive influence on the activities of an undertaking. Control under
        Art. IV.6 CEL arises from rights, agreements, or other means (factual or legal)
        enabling decisive influence over governance, voting, or strategic decisions. De facto
        sole control can arise from a sub-majority stake in a dispersed shareholding structure
        (Picanol/Tessenderlo: 27.6% = sole control). Joint control arises through strategic
        veto rights or voting agreements. No fixed percentage floor.
""",

"at": """\
minority_thresholds:
  applies: true
  standard: "percentage_based"
  note: >
    Austria explicitly catches minority acquisitions under §7(1) of the Kartellgesetz 2005
    (KartG 2005). Acquisition of shares resulting in a post-acquisition stake of 25% or more
    (or 50% or more) constitutes a notifiable concentration — no control, decisive influence,
    or additional rights are required at the 25% level. This is one of the few EU
    jurisdictions (alongside Germany) with a mechanical percentage trigger below the control
    threshold. Sub-25% acquisitions may still be notifiable if structured to evade the 25%
    threshold via equivalent voting rights, or if the acquirer in fact exercises decisive
    influence. Austrian thresholds (§9 KartG): combined worldwide >EUR 300m AND combined
    Austrian domestic >EUR 15m AND ≥2 parties each with Austrian domestic >EUR 1m.
    Notifications go to both the Federal Competition Authority (BWB) and the Federal Cartel
    Prosecutor (Bundeskartellanwalt). Media sector: KommAustria regime applies in parallel.
  rules:
    - rule_id: "at_minority_25pct"
      relationship_type: "any"
      pct_threshold: 25.0
      operator: ">="
      rights_required: null
      source: "§7(1) Kartellgesetz 2005 (KartG 2005)"
      source_type: "primary_legislation"
      source_url: "https://www.ris.bka.gv.at/GeltendeFassung.wxe?Abfrage=Bundesnormen&Gesetzesnummer=20003058"
      note: >
        Acquisition of a shareholding resulting in a post-acquisition stake of 25% or more
        of shares (capital or voting rights) in an Austrian undertaking constitutes a
        concentration per se under §7(1) KartG 2005. No additional rights, control, or
        influence required — bright-line percentage rule. Both direct and indirect holdings
        are included. Group shareholdings are aggregated. The 50% crossing is a separately
        notifiable event within the same provision.
""",

# ── Asia-Pacific ──────────────────────────────────────────────────────────────

"cn": """\
minority_thresholds:
  applies: true
  standard: "control_based"
  note: >
    China's AML 2022 (effective 1 August 2022) does not set an explicit equity percentage
    safe-harbour for minority acquisitions. A 'concentration of undertakings' is triggered
    by acquiring control OR the ability to exercise decisive influence — assessed
    functionally without a fixed percentage floor. SAMR practice confirms that sub-50%
    stakes can constitute sole control (e.g. New Hope/Xingyuan 2021: 23.6% = sole control
    in practice due to dispersed other shareholders). Article 26 of the 2022 AML also
    creates a SAMR call-in power for below-threshold concentrations that may restrict
    competition. Notification thresholds (January 2024): combined global turnover >CNY 12bn
    AND one party's China turnover >CNY 800m. There is no passive investment exemption
    for acquisitions meeting the turnover thresholds.
  rules:
    - rule_id: "cn_minority_decisive_influence"
      relationship_type: "any"
      pct_threshold: null
      operator: ">="
      rights_required: "veto_strategic"
      source: "Anti-Monopoly Law 2022, Arts. 12, 13, 26; SAMR Measures for Review of Concentration of Undertakings 2023"
      source_type: "primary_legislation"
      source_url: "https://www.gov.cn/xinwen/2022-06/25/content_5697698.htm"
      note: >
        Control (sole or joint) is functional: veto rights over budget, business plan, or
        senior management appointments suffice. No hard percentage floor — SAMR pays close
        attention once a stake reaches or exceeds approximately 25% because that level commonly
        confers qualified-majority block rights under Chinese corporate law. Joint control
        requires that no single party can determine strategy alone.
    - rule_id: "cn_minority_callin"
      relationship_type: "any"
      pct_threshold: null
      operator: ">="
      rights_required: null
      source: "Anti-Monopoly Law 2022, Art. 26"
      source_type: "primary_legislation"
      source_url: "https://www.gov.cn/xinwen/2022-06/25/content_5697698.htm"
      note: >
        Even below turnover thresholds, SAMR may issue a written notice requiring
        notification where evidence suggests the concentration has or may have the effect
        of eliminating or restricting competition. Parties may also self-initiate notification
        proactively for competitive certainty.
""",

"jp": """\
minority_thresholds:
  applies: true
  standard: "percentage_based"
  note: >
    Japan's Antimonopoly Act (AMA) Articles 10–16 govern share acquisitions. Article 10
    imposes a hard prior-notification obligation once an acquirer's holding crosses 20%
    or 50% of the voting rights of the target — even if no control changes hands. The
    obligation is triggered by crossing those thresholds for the first time; intermediate
    movements between thresholds do not re-trigger. Substantive review uses the JFTC's
    Business Combination Guidelines (2019): a shareholding is assessed for competition
    effects when it exceeds 20% and the acquirer is the sole top holder, or exceeds 10%
    and is among the top 3 holders requiring deeper analysis. There is no passive investor
    exemption — institutional investors holding above 20% must notify. Size-of-party tests:
    acquirer group domestic turnover >JPY 20bn AND target group domestic turnover >JPY 5bn.
  rules:
    - rule_id: "jp_minority_20pct"
      relationship_type: "any"
      pct_threshold: 20.0
      operator: ">"
      rights_required: null
      source: "Antimonopoly Act (Act No. 54/1947, as amended), Art. 10; AMA Enforcement Regulations, Art. 9"
      source_type: "primary_legislation"
      source_url: "https://www.jftc.go.jp/en/legislation_gls/amended_ama09/index.html"
      note: >
        Prior notification required when the acquirer (including group companies) crosses
        20% of voting rights for the first time, provided combined domestic turnover of the
        acquirer's group exceeds JPY 20bn AND the target group's domestic turnover exceeds
        JPY 5bn. Control is not a prerequisite — the threshold is purely mechanical.
    - rule_id: "jp_minority_50pct"
      relationship_type: "any"
      pct_threshold: 50.0
      operator: ">"
      rights_required: null
      source: "Antimonopoly Act, Art. 10; AMA Enforcement Regulations, Art. 9"
      source_type: "primary_legislation"
      source_url: "https://www.jftc.go.jp/en/legislation_gls/amended_ama09/index.html"
      note: >
        A second independent notification threshold triggers when the acquirer's holding
        crosses 50%. Particularly relevant for listed-company acquisitions where a party
        already holds above 20% and continues buying. Same size-of-party tests apply.
""",

"kr": """\
minority_thresholds:
  applies: true
  standard: "percentage_based"
  note: >
    Korea's MRFTA (Monopoly Regulation and Fair Trade Act) Article 9 defines 'business
    combination' to include share acquisitions reaching or exceeding specific percentage
    thresholds — differentiated by listed vs. unlisted status of the target. Pre-notification
    to the KFTC before closing is required when size-of-party tests are met (one party
    worldwide assets or turnover ≥KRW 300bn AND the other ≥KRW 30bn). There is no minimum
    economic nexus test within the percentage triggers — crossing the percentage alone
    determines whether a 'combination' has occurred. An existing holder below the threshold
    that buys incrementally to become the largest shareholder also triggers notification,
    even if the additional stake is small.
  rules:
    - rule_id: "kr_minority_unlisted_20pct"
      relationship_type: "any"
      pct_threshold: 20.0
      operator: ">="
      rights_required: null
      source: "MRFTA (Act No. 18661, as amended 2022), Art. 9(1)(ii); KFTC Enforcement Decree Art. 15"
      source_type: "primary_legislation"
      source_url: "https://www.law.go.kr/engLsSc.do?menuId=1&subMenuId=21&tabMenuId=117"
      note: >
        Acquisition of 20% or more of the total voting shares of an unlisted Korean company
        constitutes a 'business combination.' A party already holding below 20% that acquires
        additional shares to become the largest shareholder at any level also triggers
        notification.
    - rule_id: "kr_minority_listed_15pct"
      relationship_type: "any"
      pct_threshold: 15.0
      operator: ">="
      rights_required: null
      source: "MRFTA Art. 9(1)(ii); KFTC Enforcement Decree Art. 15"
      source_type: "primary_legislation"
      source_url: "https://www.law.go.kr/engLsSc.do?menuId=1&subMenuId=21&tabMenuId=117"
      note: >
        For companies listed on the Korea Exchange (KRX), the threshold is 15% of total
        voting shares. The lower threshold for listed companies reflects that listed-company
        ownership is more dispersed, so a lower stake can confer effective influence.
""",

"in": """\
minority_thresholds:
  applies: true
  standard: "material_influence"
  note: >
    India's Competition Act 2002 Sections 5–6 govern combinations. The 2023 Competition
    Amendment Act codified 'material influence' as the lowest control standard — below
    decisive influence. Schedule I Item 1 of the Combination Regulations (amended 2022)
    provides a conditional exemption for minority stakes below 25%, but only if the
    investment is 'solely for investment' or 'ordinary course of business' with no
    governance rights beyond those of a standard shareholder. The CCI has progressively
    narrowed this exemption: board seats, observer rights, information rights beyond
    standard investor protections, or any consent right over business decisions each
    independently destroy the exemption. The 2023 Amendment Act also introduced a deal
    value threshold (DVT) of INR 2,000 crore (~USD 238m) for transactions where the
    target has substantial business operations in India — this can catch minority stakes
    in high-value digital/tech deals even if the 25% exemption would otherwise apply.
  rules:
    - rule_id: "in_minority_material_influence"
      relationship_type: "any"
      pct_threshold: 25.0
      operator: ">="
      rights_required: null
      source: "Competition Act 2002, Sec. 5; Combination Regulations Schedule I Item 1 (amended 2022)"
      source_type: "primary_legislation"
      source_url: "https://www.cci.gov.in/combination/regulations"
      note: >
        Acquisitions of 25% or more of shares or voting rights are generally notifiable
        (subject to financial thresholds). The conditional exemption for below-25% stakes
        requires: (a) solely for investment or ordinary course of business; (b) no board
        representation or observer rights; (c) no access to commercially sensitive
        information; (d) no horizontal, vertical, or complementary overlap between acquirer
        and target. All four conditions must be met. Above 25%, any acquisition conferring
        material influence over the target's management or affairs is notifiable.
    - rule_id: "in_minority_dvt"
      relationship_type: "any"
      pct_threshold: null
      operator: ">="
      rights_required: null
      source: "Competition (Amendment) Act 2023, Sec. 5(d); effective September 10, 2024"
      source_type: "primary_legislation"
      source_url: "https://prsindia.org/files/bills_acts/acts_parliament/2023/The%20Competition%20(Amendment)%20Act,%202023.pdf"
      note: >
        Even if a minority stake is below 25%, notification is mandatory where total deal
        value exceeds INR 2,000 crore (~USD 238m) and the target enterprise has 'substantial
        business operations in India.' This deal value threshold specifically targets killer
        acquisitions and high-value digital and tech deals that previously escaped CCI review.
        Effective September 10, 2024.
""",

"au": """\
minority_thresholds:
  applies: true
  standard: "any_acquisition"
  note: >
    Australia replaced its voluntary informal clearance regime with a mandatory and
    suspensory regime effective 1 January 2026, with voting-power percentage thresholds
    for share acquisitions applying from 1 April 2026 (new Part VII, Competition and
    Consumer Act 2010). Under the new regime, crossing the 20% voting power threshold
    in a non-listed entity is a notifiable event (subject to monetary thresholds). Section
    50 of the CCA continues to prohibit any acquisition of shares or assets that
    substantially lessens competition (SLC), regardless of the percentage acquired —
    even a sub-20% stake that facilitates anti-competitive information exchange or forms
    part of a creeping acquisition strategy can be challenged. A separate cumulative
    acquisition threshold targets serial minority-stake strategies.
  rules:
    - rule_id: "au_minority_20pct_voting"
      relationship_type: "any"
      pct_threshold: 20.0
      operator: ">"
      rights_required: null
      source: "Competition and Consumer Act 2010 (Cth), new Part VII; ACCC Amended Determination effective 1 April 2026"
      source_type: "primary_legislation"
      source_url: "https://www.accc.gov.au/business/mergers-and-acquisitions/thresholds-for-notifying-acquisitions"
      note: >
        From 1 April 2026, notification is mandatory when a person's voting power in a
        non-listed entity moves from ≤20% to >20%, provided monetary thresholds are also
        met: combined Australian revenue of merger parties ≥AUD 200m (or AUD 500m for a
        very large acquirer), plus the target's Australian revenue ≥AUD 10m. This means
        minority acquisitions without technical 'control' are captured.
    - rule_id: "au_slc_general"
      relationship_type: "any"
      pct_threshold: null
      operator: ">="
      rights_required: null
      source: "Competition and Consumer Act 2010 (Cth), Sec. 50"
      source_type: "primary_legislation"
      source_url: "https://www.legislation.gov.au/C2004A00109/latest/"
      note: >
        Section 50 applies to any acquisition of shares or assets regardless of the
        percentage acquired. A sub-20% stake that facilitates exchange of competitively
        sensitive information, confers effective influence over a rival, or forms part of
        a creeping acquisition strategy can be challenged as substantially lessening
        competition.
""",

"nz": """\
minority_thresholds:
  applies: true
  standard: "material_influence"
  note: >
    New Zealand's Commerce Act 1986 Section 47 prohibits acquisitions of shares or assets
    that substantially lessen competition (SLC) in any New Zealand market. The regime is
    voluntary — no mandatory notification threshold exists as of mid-2026 (proposed reforms
    under the Commerce Amendment Bill are pending). Minority acquisitions are caught when
    they create a 'substantial degree of influence' (SDI) over the target, assessed by
    reference to voting rights, board appointment powers, veto rights, economic dependency,
    or contractual arrangements. Parties may apply for voluntary clearance under Section 66
    for protection against post-closing challenge. The Commerce Commission has challenged
    minority stakes in small, concentrated New Zealand markets.
  rules:
    - rule_id: "nz_minority_slc"
      relationship_type: "any"
      pct_threshold: null
      operator: ">="
      rights_required: null
      source: "Commerce Act 1986 (NZ), Sec. 47"
      source_type: "primary_legislation"
      source_url: "https://www.legislation.govt.nz/act/public/1986/0005/188.0/DLM88421.html"
      note: >
        Any acquisition of shares, regardless of percentage, is caught by Section 47 if
        it substantially lessens competition. No percentage floor. The Commission considers
        the full economic effect: information sharing, board influence, veto powers, and
        structural links to competitors.
    - rule_id: "nz_minority_substantial_influence"
      relationship_type: "any"
      pct_threshold: null
      operator: ">="
      rights_required: "veto_strategic"
      source: "Commerce Act 1986, Sec. 47; Commerce Commission Merger Guidelines"
      source_type: "official_guidance"
      source_url: "https://www.comcom.govt.nz/business-competition/guidelines/"
      note: >
        A minority stake satisfying any of the SDI factors — voting rights enabling
        blocking, board appointment, veto powers over strategic decisions, economic
        dependency — can render the acquirer an 'associated person' of the target,
        bringing the combined position within the Section 47 SLC analysis.
""",

"sg": """\
minority_thresholds:
  applies: true
  standard: "any_acquisition"
  note: >
    Singapore's Competition Act 2004 Section 54 prohibits mergers that substantially
    lessen competition (SLC) in any Singapore market. The regime is voluntary — no
    mandatory notification threshold. The CCCS's Merger Guidelines (2022) establish
    market-share indicators as the primary proxy for whether notification is advisable:
    (1) post-merger market share ≥40% in any relevant Singapore market; or (2) post-merger
    market share 20–40% AND three-firm concentration ratio (CR3) ≥70%. These are market-
    share (not equity-stake) indicators. Minority acquisitions that confer competitive
    influence — board representation, information rights on competitively sensitive data,
    veto rights over product/pricing decisions — may trigger Section 54 scrutiny even at
    small equity percentages. Common ownership concerns (overlapping financial investors
    across competing portfolio companies) are an emerging focus in CCCS's 2022 guidelines.
  rules:
    - rule_id: "sg_minority_slc_general"
      relationship_type: "any"
      pct_threshold: null
      operator: ">="
      rights_required: null
      source: "Competition Act 2004 (Cap. 50B), Sec. 54"
      source_type: "primary_legislation"
      source_url: "https://www.cccs.gov.sg/anti-competitive-practices/legislation-and-guidelines/competition-act-and-guidelines"
      note: >
        Any minority acquisition can trigger Section 54 scrutiny — including purely
        structural minority stakes — if the CCCS concludes they substantially lessen
        competition. Parties must self-assess. CCCS can investigate even after closing.
    - rule_id: "sg_minority_market_share_40pct"
      relationship_type: "any"
      pct_threshold: null
      operator: ">="
      rights_required: null
      source: "CCCS Merger Guidelines (2022), para. 3.5"
      source_type: "official_guidance"
      source_url: "https://www.cccs.gov.sg/docs/default-source/media-release/2022/cccs-guidelines-on-the-substantive-assessment-of-mergers-2022.pdf"
      note: >
        CCCS advises notification where the post-merger combined entity will have a market
        share of ≥40% in a relevant Singapore market, or 20–40% with CR3 ≥70%. These
        thresholds apply to any acquisition including minority stakes that confer effective
        market influence. Note: these are market-share indicators, not equity-stake
        percentages.
""",

"tw": """\
minority_thresholds:
  applies: true
  standard: "percentage_based"
  note: >
    Taiwan's Fair Trade Act (FTA) Article 10 defines 'combination' (merger) to include
    any acquisition of one-third or more of the voting shares or capital contributions of
    another enterprise. This is a hard statutory definition: reaching the one-third
    threshold constitutes a combination regardless of whether operational control changes.
    Article 11 then establishes whether the combination must be pre-notified to the Fair
    Trade Commission (FTC) based on market share or turnover tests. All shares and capital
    contributions held by the acquirer's group (including affiliates) are aggregated for
    the one-third calculation. The FTC has a strict gun-jumping posture with fines up to
    NTD 50m for consummating a notifiable combination before clearance.
  rules:
    - rule_id: "tw_minority_one_third"
      relationship_type: "any"
      pct_threshold: 33.33
      operator: ">"
      rights_required: null
      source: "Fair Trade Act (Taiwan), Art. 10(1)(ii)"
      source_type: "primary_legislation"
      source_url: "https://law.moj.gov.tw/ENG/LawClass/LawAll.aspx?pcode=J0150002"
      note: >
        Acquiring 'more than one-third' of the total voting shares or capital of another
        enterprise is a statutory 'combination.' All shares and capital contributions held
        by the acquirer (including affiliates) are aggregated. The trigger is the equity
        percentage itself; no separate control test applies at the definitional stage.
        Pre-notification under Article 11 is then required if the notional market-share
        or turnover tests are also met.
""",

"id": """\
minority_thresholds:
  applies: true
  standard: "control_based"
  note: >
    Indonesia's Law No. 5/1999 on the Prohibition of Monopoly and Unfair Business
    Competition, Articles 28–29, requires post-closing notification (within 30 business
    days) of mergers, consolidations, and share acquisitions. KPPU Regulation No. 3/2023
    revised the framework. Control for merger purposes is established at ownership of more
    than 50% of shares or voting rights, but sub-50% holdings that 'influence and determine
    policies and/or management' also constitute a reportable acquisition. The regime is
    post-closing — not suspensory. Value thresholds: combined Indonesian assets >IDR 2.5
    trillion OR combined Indonesian annual sales >IDR 5 trillion (IDR 20 trillion for
    banking). There is no explicit safe-harbour percentage below 50% for passive minority
    stakes that do not influence management.
  rules:
    - rule_id: "id_minority_50pct"
      relationship_type: "any"
      pct_threshold: 50.0
      operator: ">"
      rights_required: null
      source: "Law No. 5/1999, Arts. 28-29; KPPU Regulation No. 3/2023"
      source_type: "primary_legislation"
      source_url: "https://arma-law.com/news-event/newsflash/peraturan-kppu-no-3-tahun-2023-the-new-revamped-merger-control-regulation-in-indonesia/"
      note: >
        Ownership of more than 50% of shares or control of more than 50% of voting rights
        automatically constitutes 'control' triggering post-closing notification obligation,
        subject to value thresholds: combined Indonesian assets >IDR 2.5 trillion OR combined
        Indonesian annual sales >IDR 5 trillion (IDR 20 trillion for banking).
    - rule_id: "id_minority_de_facto_control"
      relationship_type: "any"
      pct_threshold: null
      operator: ">="
      rights_required: "veto_strategic"
      source: "Law No. 5/1999, Art. 7 (definition of control); KPPU Reg. No. 3/2023"
      source_type: "primary_legislation"
      source_url: "https://arma-law.com/news-event/newsflash/peraturan-kppu-no-3-tahun-2023-the-new-revamped-merger-control-regulation-in-indonesia/"
      note: >
        A stake below 50% that nonetheless 'influences and determines the policies and/or
        management' of the company is also treated as a control acquisition requiring
        post-closing notification. Whether minority governance rights (veto on strategy,
        board appointment) rise to this standard is assessed case-by-case. There is no
        explicit safe-harbour percentage below 50% for non-influential passive stakes.
""",

"ph": """\
minority_thresholds:
  applies: true
  standard: "percentage_based"
  note: >
    The Philippine Competition Act (PCA), Republic Act No. 10667, Section 17 and its
    Implementing Rules and Regulations (IRR) impose mandatory pre-merger notification
    based on explicit equity percentage thresholds, independent of whether the transaction
    confers formal 'control.' The Philippine Competition Commission (PCC) updated the Size
    of Party (SOP) and Size of Transaction (SOT) thresholds in March 2024. Control under
    the PCA is defined as the ability to substantially influence or direct actions or
    decisions of an entity; majority ownership (>50%) creates a presumption of control.
    The Philippine regime creates a two-step structure: notification at 35% crossing, then
    again at 50% crossing.
  rules:
    - rule_id: "ph_minority_35pct"
      relationship_type: "any"
      pct_threshold: 35.0
      operator: ">"
      rights_required: null
      source: "RA 10667 (Philippine Competition Act), Sec. 17; PCA-IRR Rule 4, Sec. 2"
      source_type: "primary_legislation"
      source_url: "https://www.phcc.gov.ph/philippine-competition-law-ra-10667"
      note: >
        Notification is mandatory when an acquisition of voting securities would result in
        the acquirer holding, in aggregate, more than 35% of the votes attached to all
        outstanding voting shares, subject to SOP/SOT thresholds: SOP >PHP 9.1bn (as
        adjusted March 2024) AND SOT >PHP 3.8bn.
    - rule_id: "ph_minority_50pct"
      relationship_type: "any"
      pct_threshold: 50.0
      operator: ">"
      rights_required: null
      source: "RA 10667 PCA-IRR Rule 4, Sec. 2"
      source_type: "primary_legislation"
      source_url: "https://www.phcc.gov.ph/philippine-competition-law-ra-10667"
      note: >
        Where the acquirer already holds ≥35% of outstanding voting shares, a further
        notification obligation arises when the acquirer subsequently crosses 50% of total
        outstanding voting shares. Same SOP/SOT thresholds apply.
""",

# ── MENA / Africa / UK ────────────────────────────────────────────────────────

"uk": """\
minority_thresholds:
  applies: true
  standard: "material_influence"
  note: >
    The UK uses a 'material influence' standard — the lowest of the three levels of control
    under Enterprise Act 2002 ss. 26–29. Material influence is below decisive influence
    (the EU EUMR standard) and can be established by shareholding alone or in combination
    with board rights, veto rights, or other structural factors. The CMA's Mergers Guidance
    (CMA2revised, September 2021, paras. 4.16–4.32) establishes that a 25%+ stake
    presumptively confers material influence (blocking minority over special resolutions
    under the Companies Act 2006). Stakes as low as 15–20% can confer material influence
    when combined with board representation, observer rights, or commercially significant
    veto rights. There is no statutory safe-harbour percentage — the CMA assesses the full
    factual matrix in every case. The NSI Act 2021 applies separately at 25%/50%/75% hard
    thresholds in 17 sensitive sectors, independently of the CMA material influence test.
  rules:
    - rule_id: "uk_minority_25pct_presumptive"
      relationship_type: "any"
      pct_threshold: 25.0
      operator: ">="
      rights_required: null
      source: "Enterprise Act 2002, ss. 26–29; CMA2revised (September 2021), paras. 4.16–4.17"
      source_type: "official_guidance"
      source_url: "https://www.gov.uk/government/publications/mergers-guidance-on-the-cmas-jurisdiction-and-procedure"
      note: >
        A 25%+ stake is presumed to confer material influence under CMA2revised para. 4.17
        because it enables the holder to block special resolutions under the Companies Act
        2006. This creates a rebuttable presumption that the CMA has jurisdiction. The
        parties may rebut by demonstrating the 25%+ stake is held by a passive financial
        investor with no structural influence rights.
    - rule_id: "uk_minority_board_rights"
      relationship_type: "any"
      pct_threshold: 15.0
      operator: ">="
      rights_required: "board_seat"
      source: "Enterprise Act 2002, ss. 26–29; CMA2revised (September 2021), paras. 4.18–4.28"
      source_type: "official_guidance"
      source_url: "https://www.gov.uk/government/publications/mergers-guidance-on-the-cmas-jurisdiction-and-procedure"
      note: >
        The CMA has found material influence in several cases involving stakes of 15–24%
        where the acquirer held a board seat or had rights to appoint a director, or held
        commercially significant veto rights over business plans, budgets, or strategy.
        The 15% figure reflects the lower end of the CMA's practice, not a statutory floor.
        The full factual matrix is assessed: size of stake relative to other shareholders,
        board composition, shareholder agreements, and any de facto ability to block
        commercial decisions (CMA2revised, paras. 4.20–4.28).
""",

"za": """\
minority_thresholds:
  applies: true
  standard: "control_based"
  note: >
    South Africa's Competition Act 89/1998 Section 12 defines a 'merger' as the acquisition
    of 'direct or indirect control over the whole or part of the business of another firm.'
    Control is broadly defined and includes the ability to 'materially influence' the policy
    of the firm — meaning South Africa, like the UK, uses a sub-decisive-influence standard.
    Section 12(2) lists four bases of control: (a) majority voting rights; (b) appointing
    or removing a majority of directors; (c) ability to materially influence policy through
    shareholding, agreement, or otherwise; (d) 35%+ of voting rights where no single other
    person holds more. The 35% threshold in Section 12(2)(d) is a specific statutory
    presumption of control, but control can arise below 35% via the material influence limb.
    There is no standalone passive minority exemption — any acquisition conferring material
    influence is a merger requiring notification if the financial thresholds are met.
  rules:
    - rule_id: "za_minority_35pct_statutory"
      relationship_type: "any"
      pct_threshold: 35.0
      operator: ">="
      rights_required: null
      source: "Competition Act 89 of 1998, Section 12(2)(d)"
      source_type: "primary_legislation"
      source_url: "https://www.compcom.co.za/"
      note: >
        A firm directly or indirectly controls another if it holds 35% or more of the
        voting rights and no other single person holds more voting rights — a statutory
        presumption of control. At 35%+, the transaction is treated as a merger subject
        to mandatory notification (if financial thresholds are met) without further
        analysis.
    - rule_id: "za_minority_material_influence"
      relationship_type: "any"
      pct_threshold: null
      operator: ">="
      rights_required: "veto_strategic"
      source: "Competition Act 89 of 1998, Section 12(2)(c); Competition Commission practice"
      source_type: "primary_legislation"
      source_url: "https://www.compcom.co.za/"
      note: >
        Section 12(2)(c): control includes the ability to materially influence policy
        through shareholding, agreement, or any other means. The Competition Commission
        and Tribunal have found material influence at minority stakes well below 35% where
        the acquirer held blocking rights over significant operational or strategic
        decisions. No statutory percentage floor for this limb — assessed on facts.
""",

"tr": """\
minority_thresholds:
  applies: true
  standard: "control_based"
  note: >
    Turkey's Law No. 4054, Article 7 and Communiqué No. 2010/4 (as amended) require
    notification for 'concentrations' — defined as mergers and acquisitions of direct or
    indirect control. Control means the ability to exercise 'decisive influence' over an
    undertaking (Article 5(1) of Communiqué 2010/4). Turkey does not have a standalone
    minority acquisition regime below the decisive influence threshold — it follows the EU
    EUMR control paradigm. A purely passive minority stake that does not confer decisive
    influence or de facto control is not a concentration requiring TCA notification.
    Joint control (veto rights over key strategic decisions in a JV) is caught. The TCA
    applies EU EUMR-style criteria and the EC Jurisdictional Notice is instructive for
    control analysis.
  rules:
    - rule_id: "tr_minority_decisive_influence"
      relationship_type: "any"
      pct_threshold: null
      operator: ">="
      rights_required: "veto_strategic"
      source: "Law No. 4054 on the Protection of Competition, Article 7; Communiqué No. 2010/4 (as amended), Article 5(1)"
      source_type: "primary_legislation"
      source_url: "https://www.rekabet.gov.tr/en/Sayfa/Birlesme-ve-devralmalar"
      note: >
        A concentration exists when one or more undertakings acquire direct or indirect
        control (decisive influence) over the whole or part of another undertaking. Decisive
        influence covers: majority voting rights; ability to appoint a majority of the
        supervisory or management board; and structural rights enabling veto over strategic
        decisions (capex, business plan, budget approval, key personnel). A minority stake
        without any structural governance rights does NOT constitute a concentration. Joint
        control arises where parties must agree on strategic commercial behaviour and neither
        can act alone.
""",

"uae": """\
minority_thresholds:
  applies: true
  standard: "control_based"
  note: >
    The UAE Federal Decree-Law No. 36 of 2023 defines an 'economic concentration' as any
    act resulting in a transfer of control over an enterprise (Article 14). Control means
    the ability to exercise decisive influence over an enterprise's activities — consistent
    with the EU EUMR paradigm. A purely passive minority stake that does not confer decisive
    influence is NOT caught. There is no equivalent of the UK material influence standard
    and no explicit percentage-based minority threshold below decisive influence. Cabinet
    Resolution No. 3 of 2025 specifies the financial notification thresholds (AED 300m
    combined UAE sales OR 40% combined UAE market share) but does not alter the control
    standard. The UAE merger control regime became operational 31 March 2025 — decisional
    practice is limited. Sector-specific approvals (Central Bank, NMC for media) may be
    triggered at lower percentage thresholds, independently of merger control.
  rules:
    - rule_id: "uae_minority_decisive_influence"
      relationship_type: "any"
      pct_threshold: null
      operator: ">="
      rights_required: "veto_strategic"
      source: "Federal Decree-Law No. 36 of 2023 on Competition, Article 14; Cabinet Resolution No. 3 of 2025"
      source_type: "primary_legislation"
      source_url: "https://www.economy.gov.ae/English/BusinessLegislation/Pages/CompetitionLaw.aspx"
      note: >
        Article 14 catches acquisitions resulting in 'control' — the ability to exercise
        decisive influence over the activities of an enterprise. The Ministry of Economy
        (MoE) has not published formal guidelines on when minority stakes constitute
        control, but the standard tracks the EU approach. A minority stake with veto rights
        over the business plan, budget, or key executive appointments may confer joint
        control and trigger notification if the financial thresholds are met.
""",

"sa": """\
minority_thresholds:
  applies: true
  standard: "material_influence"
  note: >
    Saudi Arabia's Competition Law (Royal Decree No. M/75 of 2019) Article 12 defines an
    'economic concentration' to include any act enabling an enterprise to 'control or
    materially influence the management, conduct, or affairs of another enterprise.' The
    GAC's Economic Concentration Review Guidelines (5th edition, April 2025) explicitly
    extend the regime to minority stakes that confer material influence — analogous to the
    UK standard but with less decisional history. The GAC 5th edition guidelines also
    introduced de minimis exemptions for investment funds acquiring minority stakes purely
    for investment purposes (passive financial investment with no governance rights beyond
    standard investor protections). Three-way AND threshold structure: SAR 200m worldwide /
    SAR 40m Saudi combined / SAR 40m target worldwide — if any one limb is missed, no
    filing is required regardless of influence conferred.
  rules:
    - rule_id: "sa_minority_material_influence"
      relationship_type: "any"
      pct_threshold: null
      operator: ">="
      rights_required: "veto_strategic"
      source: "Saudi Competition Law, Royal Decree No. M/75 of 2019, Article 12; GAC Economic Concentration Review Guidelines (5th edition, April 2025)"
      source_type: "official_guidance"
      source_url: "https://www.gac.gov.sa/en/economic-concentration/"
      note: >
        Article 12 catches any act enabling an enterprise to 'materially influence' the
        management, conduct, or affairs of another. The GAC 5th edition guidelines confirm
        that a minority stake combined with structural rights (veto over strategic decisions,
        board seat, right to appoint key management) may constitute a notifiable economic
        concentration. The GAC assesses the totality of the transaction — share percentage,
        contractual rights, governance documents, and commercial context. No statutory
        percentage floor for the material influence limb.
""",

"ng": """\
minority_thresholds:
  applies: true
  standard: "control_based"
  note: >
    Nigeria's Federal Competition and Consumer Protection Act 2018 (FCCPA) Section 92
    defines a merger as the acquisition of 'direct or indirect control over the whole or
    part of a business.' The FCCPC has not published detailed guidance on when a minority
    stake constitutes control, but the statutory definition of control includes the ability
    to 'direct or cause the direction of management and policies of an enterprise' through
    shareholding, voting power, board appointment rights, or contractual arrangements.
    A purely passive minority stake without governance rights is unlikely to be caught.
    However, the NGN financial thresholds are very low in USD terms (~USD 625,000 combined
    at 2026 rates), meaning virtually any transaction with Nigerian operating businesses
    will trigger the financial tests — making the control analysis the primary gating
    question. The Central Bank of Nigeria (CBN) separately requires approval for
    acquisitions of 5%+ in a Nigerian bank.
  rules:
    - rule_id: "ng_minority_decisive_control"
      relationship_type: "any"
      pct_threshold: null
      operator: ">="
      rights_required: "veto_strategic"
      source: "Federal Competition and Consumer Protection Act 2018 (FCCPA), Section 92"
      source_type: "primary_legislation"
      source_url: "https://fccpc.gov.ng/"
      note: >
        Section 92 FCCPA: a merger occurs when a person acquires 'direct or indirect
        control' over the whole or part of a business — defined as the ability to direct
        or cause the direction of management and policies through shareholding, voting
        power, contractual arrangements, or other means. A minority stake with board
        appointment rights or veto over strategic decisions may constitute control.
        The FCCPC has limited published practice on minority stakes; conservative assessment
        is advised.
    - rule_id: "ng_minority_banking_5pct"
      relationship_type: "any"
      pct_threshold: 5.0
      operator: ">="
      rights_required: null
      source: "Central Bank of Nigeria Act; CBN Regulation on Scope of Banking Activities No. 3 of 2010"
      source_type: "primary_legislation"
      source_url: "https://www.cbn.gov.ng/"
      note: >
        Separate from FCCPC merger control: the Central Bank of Nigeria requires prior
        approval for any acquisition of 5% or more of the shares of a Nigerian bank.
        This is a sector-specific concurrent requirement entirely separate from the FCCPA
        and applies at a much lower threshold.
""",

"ke": """\
minority_thresholds:
  applies: true
  standard: "control_based"
  note: >
    Kenya's Competition Act No. 12 of 2010 Section 41 defines a merger as the 'direct or
    indirect acquisition or establishment of control over the whole or part of the business
    of another undertaking.' The Competition Authority of Kenya (CAK) applies a decisive
    influence standard for control, consistent with the EU approach. A purely passive
    minority stake without governance rights does not constitute a 'merger' under the Act.
    The KES 1bn (~USD 7.7m) combined turnover/assets threshold is low, meaning most
    minority acquisitions involving a Kenyan company with meaningful revenues will trigger
    the financial threshold test — at which point the control analysis determines whether
    notification is required. COMESA filing obligations run concurrently for regional
    transactions meeting COMESA thresholds (combined African revenues >USD 50m AND each
    of ≥2 parties >USD 10m).
  rules:
    - rule_id: "ke_minority_decisive_influence"
      relationship_type: "any"
      pct_threshold: null
      operator: ">="
      rights_required: "veto_strategic"
      source: "Competition Act No. 12 of 2010 (Kenya), Section 41"
      source_type: "primary_legislation"
      source_url: "https://www.cak.go.ke/"
      note: >
        Section 41 defines a merger as an acquisition of 'control over the whole or part
        of the business of another undertaking.' Control is the ability to exercise decisive
        influence over management and strategic decisions. A minority shareholder with board
        representation and veto rights over strategic decisions (budget, business plan, key
        management appointments) may be found to control the target. Purely passive financial
        stakes with standard minority investor protections are unlikely to constitute control.
""",

"eg": """\
minority_thresholds:
  applies: true
  standard: "control_based"
  note: >
    Egypt's Competition Protection Law No. 3 of 2005 (as amended by Law No. 175 of 2022)
    Article 19 defines an economic concentration to include any act enabling an enterprise
    to 'directly or indirectly acquire a controlling share in or over another enterprise.'
    A 'controlling share' means an interest enabling a party to direct or significantly
    influence the management and policies of another. The 'significant influence' language
    may be slightly broader than the EU decisive influence standard, closer to the UK
    material influence or South African material influence concepts. The ECA has limited
    published practice since the 2022 amendment — conservative assessment and informal
    ECA engagement is advisable. EGP depreciation has made the EGP-denominated thresholds
    substantially lower in USD terms (EGP 900m worldwide threshold ~USD 18m at 2025 rates).
  rules:
    - rule_id: "eg_minority_significant_influence"
      relationship_type: "any"
      pct_threshold: null
      operator: ">="
      rights_required: "veto_strategic"
      source: "Competition Protection Law No. 3 of 2005 (as amended by Law No. 175 of 2022), Article 19"
      source_type: "primary_legislation"
      source_url: "https://eca.gov.eg/en/MergerControl"
      note: >
        Article 19 catches any act enabling a party to 'acquire a controlling share' —
        an interest enabling the party to direct or significantly influence the management
        and policies of another enterprise. This 'significant influence' language is
        potentially broader than the EU decisive influence standard. A minority stake with
        board representation plus veto rights over strategic or operational decisions is
        likely to be treated as conferring a 'controlling share.' Purely passive financial
        investments without governance rights are unlikely to be caught.
""",

}


def insert_minority_thresholds(jid: str, block: str) -> bool:
    """Insert minority_thresholds block into a jurisdiction YAML file."""
    path = DATA_DIR / f"{jid}.yaml"
    if not path.exists():
        print(f"  SKIP: {path} does not exist")
        return False

    content = path.read_text()

    if "minority_thresholds:" in content:
        print(f"  SKIP: {jid} already has minority_thresholds")
        return False

    # Find insertion point: before gun_jumping comment or before gun_jumping:
    patterns = [
        r"(# ── Gun-jumping / standstill obligation ─+\n)",
        r"(gun_jumping:\n)",
        r"(# ── FDI / national security screening ─+\n)",
        r"(fdi_screening:\n)",
        r"(# ── Source passages ─+\n)",
        r"(source_passages:\n)",
    ]

    inserted = False
    for pattern in patterns:
        m = re.search(pattern, content)
        if m:
            insert_pos = m.start()
            # Add a blank line before the block if needed
            prefix = "\n" if content[insert_pos - 1] != "\n" or content[insert_pos - 2] != "\n" else ""
            content = content[:insert_pos] + prefix + block + "\n" + content[insert_pos:]
            inserted = True
            break

    if not inserted:
        # Append at end
        content = content.rstrip("\n") + "\n\n" + block
        inserted = True

    path.write_text(content)
    return True


def main():
    missing = []
    for jid, block in BLOCKS.items():
        result = insert_minority_thresholds(jid, block)
        if result:
            print(f"  OK: {jid}")
        else:
            missing.append(jid)

    print(f"\nDone. Processed {len(BLOCKS)} jurisdictions.")
    if missing:
        print(f"Already had / skipped: {missing}")


if __name__ == "__main__":
    main()
