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
