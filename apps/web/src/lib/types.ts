export type Jurisdiction = "EU" | "UK" | "US";

export type ExtractionMethod = "ai_extracted" | "manually_added" | "imported_metadata";
export type ReviewStatus = "unreviewed" | "spot_checked" | "lawyer_reviewed";
export type DefinitionStatus = "defined" | "discussed" | "segmented" | "left_open";
export type PartyRole = "acquirer" | "target" | "merged_entity" | "third_party";

export type Outcome =
  | "cleared"
  | "cleared_with_remedies"
  | "cleared_with_conditions"
  | "blocked"
  | "abandoned"
  | "referred"
  | "pending"
  | "pending_litigation"
  | "under_appeal"
  | "annulled"
  | "partially_annulled"
  | "upheld_on_appeal"
  | "unknown";

export type IndexedExtractionStatus = "pending" | "not_applicable" | "extracted";

export type VerificationStatus = "source_linked" | "verified" | "no_source_linked";
export type RetrievalStatus = "direct" | "fallback" | "broken" | "unknown";

export type CaseHistoryStatus =
  | "final_no_known_challenge"
  | "challenged"
  | "pending_litigation"
  | "under_appeal"
  | "upheld"
  | "upheld_on_appeal"
  | "annulled"
  | "partially_annulled"
  | "withdrawn"
  | "settled"
  | "unknown";

export interface PropositionVerification {
  verification_status: VerificationStatus;
  verified_by?: string;
  verified_at?: string;
  verification_notes?: string;
  verification_count: number;
}

export interface CaseHistoryEvent {
  event_type: string;
  event_date?: string;
  forum?: string;
  case_number?: string;
  title: string;
  outcome?: string;
  source_url?: string;
  summary?: string;
  review_status: ReviewStatus;
}

export interface CaseHistory {
  status: CaseHistoryStatus;
  events: CaseHistoryEvent[];
}

export interface SourcePassage {
  passage_id: string;
  source_document_id: string;
  page?: string;
  paragraph?: string;
  section?: string;
  quote_snippet: string;
  extraction_method: ExtractionMethod;
  review_status: ReviewStatus;
  confidence_score: number;
  last_checked_date: string;
  supports_markets: string[];
  supports_geographic_markets: string[];
  supports_theories: string[];
}

export interface SourceDocument {
  doc_id: string;
  title: string;
  url?: string;
  pdf_url?: string;
  case_page_url?: string;
  doc_type: string;
  authority_reference?: string;
  retrieval_status: RetrievalStatus;
  published_date?: string;
  last_checked?: string;
}

export interface Party {
  name: string;
  role: PartyRole;
}

export interface ProductMarket {
  market_id: string;
  name: string;
  definition_status: DefinitionStatus;
  notes?: string;
  verification?: PropositionVerification;
}

export interface GeographicMarket {
  market_id: string;
  name: string;
  definition_status: DefinitionStatus;
  notes?: string;
  verification?: PropositionVerification;
}

export interface TheoryOfHarm {
  theory_id: string;
  name: string;
  description?: string;
  verification?: PropositionVerification;
}

export interface SimilarCase {
  case_id: string;
  score: number;
  method: string;
  reasons: string[];
}

export interface CaseMetadata {
  extraction_method: ExtractionMethod;
  review_status: ReviewStatus;
  overall_confidence: number;
  created_date: string;
  last_updated_date: string;
  tags: string[];
}

export interface CaseRecord {
  case_id: string;
  case_name: string;
  jurisdiction: Jurisdiction;
  authority: string;
  decision_date: string;
  case_type: string;
  procedure_stage: string;
  sector: string;
  parties: Party[];
  outcome: Outcome;
  remedies: string[];
  theories_of_harm: TheoryOfHarm[];
  product_markets_considered: ProductMarket[];
  geographic_markets_considered: GeographicMarket[];
  source_documents: SourceDocument[];
  source_passages: SourcePassage[];
  similar_cases: SimilarCase[];
  ai_summary?: string;
  case_history?: CaseHistory;
  metadata: CaseMetadata;
}

export interface ConceptRef {
  concept_id: string;
  quality_level: string;  // "canonical" | "indexed"
  provenance: string;     // "manually_tagged" | "ai_extracted" | "yaml_concept_field"
}

export interface IndexedCaseDetail {
  data_layer: "indexed";
  record_status: "indexed_metadata";
  case_id: string;
  case_name: string;
  jurisdiction: Jurisdiction;
  authority: string;
  decision_date: string;
  sector: string;
  outcome: Outcome;
  case_type: string;
  source_url?: string;
  pdf_url?: string;
  pdf_language?: string;
  ai_summary?: string;
  parties: Party[];
  concept_refs: ConceptRef[];
  extraction_status?: IndexedExtractionStatus;
}

export interface GraphNeighbourhood {
  case: Record<string, unknown>;
  parties: Record<string, unknown>[];
  sectors: Record<string, unknown>[];
  product_markets: Record<string, unknown>[];
  geographic_markets: Record<string, unknown>[];
  theories_of_harm: Record<string, unknown>[];
  outcomes: Record<string, unknown>[];
  similar_cases: {
    case: Record<string, unknown>;
    score: number;
    reasons: string[];
  }[];
  authority?: Record<string, unknown>;
  jurisdiction?: Record<string, unknown>;
  source?: string;
}

export interface GraphNode {
  id: string;
  label: string;
  type: string;
  data_layer?: string;
  record_status?: string;
  href?: string;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  quality_level?: string;
  provenance?: string;
}

export interface GraphNeighborhoodResponse {
  center_case_id: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  source: string;
}

// ── Search hit (shared by keyword and semantic results) ──────────────────────

export interface CaseSearchHit {
  data_layer: string;
  record_status: string;
  case_id: string;
  case_name: string;
  jurisdiction: string;
  authority: string;
  decision_date: string;
  sector: string;
  outcome: Outcome;
  case_type: string;
  source_url?: string;
  ai_summary?: string;
  parties: Party[];
  concept_refs: ConceptRef[];
  product_market_count: number;
  theory_count: number;
  source_passage_count: number;
  similarity_score?: number;
}

// ── Entity-centric graph types ───────────────────────────────────────────────

export interface MarketSummary {
  market_name: string;
  case_count: number;
  case_ids: string[];
  sectors: string[];
  definition_status_breakdown: Record<string, number>;
  dominant_status: string;
}

export interface TheorySummary {
  theory_name: string;
  case_count: number;
  case_ids: string[];
  sectors: string[];
  outcome_breakdown: Record<string, number>;
}

export interface EntityCase {
  case_id: string;
  case_name: string;
  jurisdiction: string;
  authority: string;
  decision_date: string;
  outcome: string;
  market_id?: string;
  definition_status?: string;
  notes?: string;
  theory_id?: string;
  description?: string;
  similarity?: number;
}

// ── Home page stats ───────────────────────────────────────────────────────────

export interface AppStats {
  canonical_case_count: number;
  indexed_case_count: number;
  total_case_count: number;
  unique_market_count: number;
  jurisdiction_count: number;
  jurisdictions: string[];
}

// ── Drill-down navigation graph types ────────────────────────────────────────

export interface SectorSummary {
  sector: string;
  case_count: number;
  market_count: number;
  outcome_breakdown: Record<string, number>;
}

export interface SectorMarketCase {
  case_id: string;
  case_name: string;
  outcome: string;
  definition_status: string;
  jurisdiction: string;
}

export interface SectorMarket {
  market_name: string;
  case_count: number;
  dominant_status: string;
  definition_status_breakdown: Record<string, number>;
  cases: SectorMarketCase[];
}

export interface SimilarMarket {
  market_name: string;
  shared_case_count: number;
  shared_case_ids: string[];
  case_count: number;
  dominant_status: string;
}

// ── Jurisdiction threshold types ──────────────────────────────────────────────

export type SourceType =
  | "primary_legislation"
  | "official_guidance"
  | "authority_announcement"
  | "practitioner";

export type MetricType =
  | "revenue"
  | "assets"
  | "deal_value"
  | "revenue_or_assets"
  | "market_share"
  | "incremental_share";

export type ScopeType =
  | "worldwide"
  | "domestic"
  | "eu_eea"
  | "eu_member_state"
  | "single_member_state"
  | "uk"
  | "us"
  | "eea_member_state";

export type PartyType =
  | "combined"
  | "acquirer_group"
  | "target_group"
  | "either_party"
  | "each_party"
  | "each_of_at_least_two";

export interface ThresholdCondition {
  condition_id: string;
  metric: MetricType;
  scope: ScopeType;
  party: PartyType;
  operator: ">" | ">=" | "<" | "<=";
  value: number;
  currency?: string;
  source: string;
  source_type: SourceType;
  source_url?: string;
  verified_via: string[];
  note?: string;
}

export interface ThresholdTest {
  test_id: string;
  description: string;
  legal_basis: string;
  source_url: string;
  note?: string;
  annual_adjustment: boolean;
  effective_date?: string;
  status?: string;
  conditions: ThresholdCondition[];
  exclusions: { exclusion_id: string; description: string; source: string; effect: string }[];
  exceptions: { exception_id: string; description: string; source: string; effect?: string }[];
}

export interface JurisdictionAuthority {
  name: string;
  abbreviation: string;
  url: string;
  filing_url: string;
}

export interface JurisdictionRegime {
  mandatory: boolean;
  suspensory: boolean;
  voluntary: boolean;
}

export interface LegalBasisEntry {
  citation: string;
  url: string;
  note?: string;
  source_type: SourceType;
}

export interface ReviewPeriod {
  days: number;
  day_type?: string;
  day_unit?: string;
  extendable_to_days?: number;
  day_unit_extended?: string;
  legal_basis: string;
  note?: string;
}

export interface ReviewPeriods {
  phase_1: ReviewPeriod;
  phase_2: ReviewPeriod;
}

export interface SourcePassage {
  passage_id: string;
  document_title: string;
  article_reference: string;
  document_url: string;
  quoted_text: string;
  source_type: SourceType;
  supports_conditions: string[];
}

export interface JurisdictionScope {
  concentration_definition?: string;
  concentration_definition_source?: string;
  concentration_definition_url?: string;
  trigger_events: string[];
  control_threshold?: string;
  intra_group_exempt?: boolean;
  foreign_to_foreign_rule?: string;
  substantive_test?: string;
  substantive_test_note?: string;
  substantive_test_url?: string;
  note?: string;
}

export interface MinorityThresholdRule {
  rule_id: string;
  relationship_type: "horizontal" | "vertical" | "conglomerate" | "non_horizontal" | "any";
  pct_threshold?: number;
  operator: ">=" | ">";
  rights_required?: string;
  source: string;
  source_type: SourceType;
  source_url?: string;
  note?: string;
}

export interface MinorityThresholds {
  applies: boolean;
  standard: "percentage_based" | "control_based" | "material_influence" | "any_acquisition" | "none";
  note?: string;
  rules: MinorityThresholdRule[];
}

export interface Fees {
  structure?: string;
  source?: string;
  source_type?: SourceType;
  source_url?: string;
  annual_adjustment?: boolean;
  note?: string;
}

export interface GunJumping {
  automatic_void?: boolean;
  voidable?: boolean;
  max_fine_pct_turnover?: number;
  max_fine_fixed?: number;
  max_fine_currency?: string;
  per_day_fine?: number;
  criminal_sanctions?: boolean;
  legal_basis?: string;
  legal_basis_url?: string;
  note?: string;
}

export interface FdiScreening {
  applicable: boolean;
  regime_name?: string;
  authority?: string;
  url?: string;
  legislation_url?: string;
  sectors_covered: string[];
  note?: string;
}

export interface PractitionerNote {
  title: string;
  firm: string;
  url: string;
  date?: string;
  summary: string;
}

export interface JurisdictionVerificationMeta {
  source_verification_tier: number;
  regression_status: "not_run" | "passed" | "failed";
  freshness_status: "fresh" | "stale" | "drift_detected" | "unknown";
  verified_at?: string | null;
}

export interface JurisdictionRule {
  jurisdiction_id: string;
  jurisdiction_name: string;
  last_verified: string;
  verification?: JurisdictionVerificationMeta;
  authority: JurisdictionAuthority;
  regime: JurisdictionRegime;
  legal_basis: LegalBasisEntry[];
  filing: {
    deadline_from_signing_days?: number;
    deadline_from_closing_days?: number;
    pre_closing_required: boolean;
    note?: string;
  };
  review_periods: ReviewPeriods;
  threshold_tests: ThresholdTest[];
  notes: string[];
  scope?: JurisdictionScope;
  gun_jumping?: GunJumping;
  fdi_screening?: FdiScreening;
  fees?: Fees;
  minority_thresholds?: MinorityThresholds;
  source_passages: SourcePassage[];
  practitioner_notes?: PractitionerNote[];
}

export interface JurisdictionSummary {
  jurisdiction_id: string;
  jurisdiction_name: string;
  authority: string;
  mandatory: boolean;
  suspensory: boolean;
  last_verified: string;
  test_count: number;
}

// ── Screening request / response types ───────────────────────────────────────

export interface RevenueByScopeInput {
  worldwide?: number;
  domestic?: number;
  eu_eea?: number;
  uk?: number;
  us?: number;
  by_country?: Record<string, number>;
}

export interface ScreeningRequest {
  acquirer: RevenueByScopeInput;
  target: RevenueByScopeInput;
  acquirer_assets?: number;
  target_assets?: number;
  acquirer_assets_by_country?: Record<string, number>;
  target_assets_by_country?: Record<string, number>;
  deal_value?: number;
  deal_currency?: string;
  revenue_currency?: string;
  fx_rates?: Record<string, number>;
  deal_type?: string;
  pct_shares_acquired?: number;
  post_closing_control?: string;
  relationship_type?: string;
  combined_market_share?: Record<string, number>;
  acquirer_market_share?: Record<string, number>;
  incremental_share?: Record<string, number>;
}

export interface ConditionResult {
  condition_id: string;
  met?: boolean;
  actual_value?: number;
  threshold_value: number;
  gap?: number;
  note?: string;
  missing_data?: string;
}

export interface TestResult {
  test_id: string;
  fired?: boolean;
  description?: string;
  excluded: boolean;
  exclusion_reason?: string;
  conditions: ConditionResult[];
}

export interface LegalCitation {
  citation: string;
  url?: string;
}

export interface ScreeningResult {
  jurisdiction_id: string;
  jurisdiction_name: string;
  status: "triggered" | "not_triggered" | "unclear" | "data_insufficient";
  triggered_by: string[];
  confidence: "high" | "medium" | "low";
  screening_confidence?: "high" | "medium" | "low";
  source_verification_tier?: number;
  regression_status?: "not_run" | "passed" | "failed";
  freshness_status?: "fresh" | "stale" | "drift_detected" | "unknown";
  filing_type?: string;
  suspensory?: boolean;
  test_results: TestResult[];
  notes: string[];
  legal_basis?: LegalCitation[];
  authority_url?: string;
}
