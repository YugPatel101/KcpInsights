// Types mirroring the FastAPI responses. Keep in sync with backend/app/api/routes.

export type DataStatus = "verified" | "imported" | "estimated" | "synthetic" | "unavailable";
export type IpoStatus = "upcoming" | "open" | "closed" | "listed" | "withdrawn";
export type RiskLevel = "low" | "moderate" | "high" | null;

export interface SourceBrief {
  id: number;
  title: string;
  url: string | null;
  source_type: string;
  data_status: DataStatus;
  retrieved_at: string | null;
}

export interface ScoreSummary {
  status: "complete" | "incomplete";
  composite: number | null;
  quality: number | null;
  valuation: number | null;
  risk: number | null;
  risk_level: RiskLevel;
  coverage: number;
  input_completeness: number;
  valuation_multiple: string | null;
  ipo_multiple: number | null;
  config_version: string;
}

export interface Subscription {
  as_of: string;
  categories: Record<string, number>;
  data_status: DataStatus[];
}

export interface IpoSummary {
  id: number;
  company_id: number;
  company_name: string;
  symbol: string | null;
  sector: string;
  industry: string | null;
  exchange: string;
  issue_type: "mainboard" | "sme";
  status: IpoStatus;
  open_date: string | null;
  close_date: string | null;
  listing_date: string | null;
  price_band_low: number | null;
  price_band_high: number | null;
  final_issue_price: number | null;
  lot_size: number | null;
  min_investment_inr: number | null;
  issue_size_cr: number | null;
  fresh_issue_cr: number | null;
  ofs_cr: number | null;
  listing_price: number | null;
  listing_return_pct: number | null;
  listing_data_status: DataStatus | null;
  subscription: Subscription | null;
  data_mode: "demo" | "imported" | "source";
  data_status: DataStatus;
  last_updated: string | null;
  source: SourceBrief | null;
  scores?: ScoreSummary;
}

export interface Peer {
  id: number;
  name: string;
  ticker: string | null;
  sector: string;
  as_of: string;
  market_cap_cr: number | null;
  pe: number | null;
  ev_ebitda: number | null;
  pb: number | null;
  ps: number | null;
  revenue_cr: number | null;
  selection_reason: string | null;
  data_status: DataStatus;
  source: SourceBrief | null;
}

export interface Disclosure {
  id: number;
  category: string;
  severity: "low" | "medium" | "high";
  status: "confirmed_disclosure" | "unresolved_concern";
  title: string;
  description: string;
  amount_cr: number | null;
  data_status: DataStatus;
  source: SourceBrief | null;
}

export interface DocumentInfo {
  id: number;
  title: string;
  doc_type: string;
  page_count: number;
  source_url: string | null;
  data_status: DataStatus;
  retrieved_at: string;
  injection_flags: number;
  chunks?: number;
  retrieval_mode?: string;
}

export interface IpoDetail extends IpoSummary {
  description: string | null;
  business_model: string | null;
  revenue_sources: { segment: string; share_pct: number }[] | null;
  website: string | null;
  customer_concentration_pct: number | null;
  face_value: number | null;
  pre_issue_shares: number | null;
  post_issue_shares: number | null;
  dilution_pct: number | null;
  promoter_holding_pre_pct: number | null;
  promoter_holding_post_pct: number | null;
  use_of_proceeds: { purpose: string; amount_cr: number }[] | null;
  risk_disclosures_reviewed: boolean;
  research_notes: string | null;
  subscription_history: { as_of: string; category: string; times_subscribed: number; data_status: DataStatus }[];
  grey_market: { caveat: string; observations: { observed_at: string; premium_inr: number; data_status: DataStatus }[] };
  peers: Peer[];
  disclosures: Disclosure[];
  documents: DocumentInfo[];
  watchlisted: boolean;
  can_edit: boolean;
  scores: ScoreSummary;
}

export interface Paged<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export const FIN_FIELDS = [
  "revenue",
  "ebitda",
  "ebit",
  "pat",
  "operating_cash_flow",
  "capex",
  "interest_expense",
  "total_assets",
  "total_liabilities",
  "total_debt",
  "cash_and_equivalents",
  "total_equity",
  "current_assets",
  "current_liabilities",
] as const;
export type FinField = (typeof FIN_FIELDS)[number];

export type Statement = {
  id: number;
  period_label: string;
  period_end: string;
  period_months: number;
  currency: string;
  unit: string;
  derived: Record<string, number | null>;
  data_status: DataStatus;
  source: SourceBrief | null;
} & Record<FinField, number | null>;

export interface MetricValue {
  key: string;
  label: string;
  value: number | null;
  unit: string;
  status: "ok" | "unavailable" | "not_meaningful";
  formula: string;
  reason: string | null;
  inputs: Record<string, unknown>;
  periods: string[];
  source_record_ids: number[];
  score_override: number | null;
}

export interface Financials {
  ipo_id: number;
  company_name: string;
  unit: string;
  statements: Statement[];
  metrics: Record<string, MetricValue>;
  note: string;
}

export interface ScoreItem {
  key: string;
  weight: number;
  score: number | null;
  evidence?: string;
  value?: number | string | null;
  normalization?: Record<string, number | string>;
  metric?: MetricValue;
}

export interface Component {
  name: string;
  score: number | null;
  status: "ok" | "unavailable";
  weight: number;
  weight_coverage: number;
  reason: string | null;
  items: ScoreItem[];
}

export interface PeerRow {
  name: string;
  ticker: string | null;
  value: number | null;
  as_of: string;
  data_status: DataStatus;
  used: boolean;
  excluded_reason: string | null;
}

export interface ValuationResult {
  score: number | null;
  status: "ok" | "unavailable";
  formula: string;
  kind: string;
  reason?: string;
  flags: string[];
  multiple?: string;
  multiple_label?: string;
  ipo_multiple?: number;
  price_used?: number;
  price_basis?: string;
  market_cap_cr?: number;
  peer_low?: number;
  peer_high?: number;
  peer_median?: number;
  low_percentile?: number;
  high_percentile?: number;
  premium_to_median_pct?: number;
  peers?: PeerRow[];
  peer_selection?: string;
  attempts: { multiple: string; used: boolean; reason?: string }[];
  calculation_inputs?: Record<string, number | string>;
}

export interface EvidenceItem {
  key: string;
  weight: number;
  present: boolean;
  status: DataStatus;
  credit: number;
  note: string | null;
}

export interface ScoreResult {
  ipo_id: number;
  company_name: string;
  status: "complete" | "incomplete";
  composite: number | null;
  composite_formula: string;
  composite_weights: { quality: number; valuation: number; risk_inverse: number };
  missing_components: { component: string; reason: string }[];
  quality: { score: number | null; status: string; formula: string; weights: Record<string, number>; components: Record<string, Component>; annual_periods_used: string[]; excluded_periods: { label: string; reason: string }[] };
  valuation: ValuationResult;
  risk: { score: number | null; status: string; level: RiskLevel; formula: string; weights: Record<string, number>; components: Record<string, Component> };
  evidence: { coverage: number; input_completeness: number; formula: string; note: string; financials_stale: boolean; items: EvidenceItem[] };
  coverage: number;
  warnings: string[];
  unavailable_metrics: { component: string; metric: string; reason: string }[];
  provenance_source_record_ids: number[];
  config_version: string;
  input_fingerprint: string;
  calculated_at: string;
  is_probability: false;
  disclaimer: string;
}

export interface Scenario {
  name: "bear" | "base" | "bull";
  status: "ok" | "unavailable";
  assumptions: Record<string, number | string | null>;
  steps?: Record<string, number | null>;
  implied_price?: number;
  implied_return_pct?: number;
  reasons?: string[];
}

export interface ScenarioResult {
  note: string;
  status: "ok" | "unavailable";
  issue_price: number | null;
  issue_price_basis: string;
  post_issue_shares: number | null;
  base_revenue_cr?: number;
  base_period?: string;
  derivation_notes?: Record<string, string>;
  formulas: Record<string, string>;
  scenarios: Scenario[];
  reasons?: string[];
  config_version: string;
}

export interface SourceRecord {
  id: number;
  title: string;
  url: string | null;
  source_type: string;
  data_status: DataStatus;
  document_id: number | null;
  document_page: number | null;
  retrieved_at: string | null;
  publication_date: string | null;
  reporting_period: string | null;
  currency: string | null;
  unit: string | null;
  transformation: string | null;
  notes: string | null;
  used_for: string[];
}

export interface User {
  id: number;
  email: string;
  display_name: string;
  is_admin: boolean;
}

export interface Session {
  user: User;
  csrf_token: string;
  expires_at: string;
}

export interface Evidence {
  id: string;
  kind: "source_record" | "calculation" | "document_chunk" | "ipo_record";
  label: string;
  ref_id: number | string | null;
  url: string | null;
  data_status: DataStatus | null;
  page: number | null;
  cited: boolean;
}

export interface ToolCall {
  tool: string;
  arguments: Record<string, unknown>;
  status: "ok" | "error" | "rejected";
  summary: string;
  duration_ms: number;
}

export interface AgentAnswer {
  summary: string;
  points: { text: string; evidence: string[] }[];
  limitations: string[];
  follow_up_questions?: string[];
}

export interface AgentResponse {
  answer: AgentAnswer;
  answer_text: string;
  mode: string;
  generative: boolean;
  intents: string[];
  ipo_ids: number[];
  evidence: Evidence[];
  tool_calls: ToolCall[];
  warnings: string[];
  report_id: number | null;
  conversation_id: number | null;
  saved: boolean;
  elapsed_ms: number;
}

export interface ReportSection {
  key: string;
  title: string;
  paragraphs: string[];
  narrative?: string;
  facts: { label: string; value: string; status?: string; used?: boolean; excluded_reason?: string | null; reasons?: string[] }[];
  evidence: string[];
}

export interface Report {
  id: number;
  title: string;
  ipo_id: number;
  company_name: string;
  generated_at: string;
  created_at?: string;
  generator: string;
  llm: { used: boolean; reason?: string; model?: string; note?: string };
  config_version: string;
  scores: { status: string; composite: number | null; quality: number | null; valuation: number | null; risk: number | null; risk_level: RiskLevel; coverage: number };
  synthetic: boolean;
  sections: ReportSection[];
  citations: { id: string; kind: string; ref_id: number | string | null; label: string; url: string | null; data_status: DataStatus | null }[];
  disclaimer: string;
}

export interface ReportListItem {
  id: number;
  title: string;
  ipo_id: number | null;
  generator: string;
  config_version: string;
  created_at: string;
  scores: Report["scores"] | null;
  synthetic: boolean | null;
}

export interface ImportReport {
  ok: boolean;
  errors: { where: string; message: string }[];
  warnings: { where: string; message: string }[];
  info: { where: string; message: string }[];
}

export interface ImportResponse {
  kind: "bundle_json" | "financials_csv";
  dry_run: boolean;
  committed: boolean;
  report: ImportReport;
  preview?: { ipos?: string[]; rows?: Record<string, unknown>[]; row_count?: number } | null;
  dataset_id?: number;
  counts?: Record<string, number>;
}

export interface ProviderHealth {
  name: string;
  available: boolean;
  model: string | null;
  detail: string;
  models_present: string[];
  embedding_model: string | null;
  embedding_available: boolean;
}

export interface ModelsStatus {
  ai: {
    configured_provider: string;
    active_mode: string;
    generative_available: boolean;
    reason: string;
    ollama: { base_url: string; model: string; small_model: string; using_small_model: boolean; embed_model: string };
    providers: ProviderHealth[];
    fallback: string;
  };
  retrieval: { chunks: number; embedded_chunks: number; mode: string };
  scoring: { active_version: string; description: string };
  listing_model: {
    models: {
      id: number;
      name: string;
      version: string;
      model_type: string;
      dataset_kind: "real" | "synthetic";
      status: string;
      n_samples: number;
      created_at: string;
      label: string | null;
      evaluations: { split: string; n: number; metrics: Record<string, unknown> }[];
    }[];
    real_listed_ipos: number;
    min_samples: number;
    warning: string;
  };
}

export interface DashboardSummary {
  as_of: string;
  totals: { ipos: number; by_status: Partial<Record<IpoStatus, number>>; documents: number; issue_size_open_upcoming_cr: number };
  data_modes: Record<string, number>;
  synthetic_share: number;
  upcoming: IpoSummary[];
  recently_listed: IpoSummary[];
  scatter: { id: number; name: string; quality: number; risk: number; composite: number | null; data_status: DataStatus; sector: string }[];
  sectors: { sector: string; count: number; issue_size_cr: number }[];
  issue_sizes: { bucket: string; count: number }[];
  freshness: { latest_record_update: string | null; stale_financials: string[] };
  watchlist: IpoSummary[];
  recent_reports: { id: number; title: string; ipo_id: number | null; generator: string; created_at: string }[];
}

export interface Prediction {
  available: boolean;
  reason?: string;
  warning: string;
  probability_positive?: number;
  expected_return_pct?: number;
  model_version?: string;
}
