// Types mirroring the FastAPI responses. Keep in sync with backend/app/api/routes.

export type DataStatus = "verified" | "imported" | "estimated" | "synthetic" | "secondary_source" | "extracted" | "requires_review" | "unavailable";
export type IpoStatus = "pipeline" | "upcoming" | "open" | "closed" | "listed" | "withdrawn";
export type IpoStage = "pipeline" | "upcoming" | "open" | "awaiting_allotment" | "awaiting_listing" | "listing_unconfirmed" | "closed" | "listed" | "withdrawn";
export type Readiness = "ready" | "partial" | "insufficient";
export type RiskLevel = "low" | "moderate" | "elevated" | "high" | null;

export interface SourceBrief {
  id: number;
  title: string;
  url: string | null;
  source_type: string;
  data_status: DataStatus;
  retrieved_at: string | null;
}

export interface ScoreSummary {
  status: "complete" | "partial" | "insufficient";
  composite: number | null;
  classification: string | null;
  profitability: number | null;
  growth: number | null;
  financial_health: number | null;
  cash_flow: number | null;
  valuation: number | null;
  risk: number | null;
  risk_level: RiskLevel;
  coverage: number | null;
  basis: string | null;
  latest_period: string | null;
  pe: number | null;
  price_status: "verified" | "estimated" | null;
  config_version: string;
  profile?: string | null;
  governance_risk?: number | null;
  calculated_at: string | null;
}

export interface CompletenessSummary {
  overall_pct: number;
  readiness: Readiness;
  readiness_label: string;
  groups: Record<string, number | null>;
  missing: string[];
  pipeline: Record<string, "done" | "pending" | "failed">;
}

export interface Subscription {
  as_of: string;
  timezone?: string | null;
  basis?: string;
  categories: Record<string, number>;
  data_status: DataStatus[];
}

export interface Freshness {
  live: boolean;
  last_verified_at: string | null;
  is_stale: boolean;
  stale_reasons: string[];
  missing_critical: string[];
  note?: string;
}

export interface KeyDate {
  key: string;
  label: string;
  date: string | null;
  status: DataStatus;
}

export interface IpoSummary {
  stage: IpoStage;
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
  face_value?: number | null;
  promoter_holding_pre_pct?: number | null;
  promoter_holding_post_pct?: number | null;
  issue_size_cr: number | null;
  fresh_issue_cr: number | null;
  ofs_cr: number | null;
  listing_price: number | null;
  listing_close_price?: number | null;
  listing_price_basis?: string | null;
  listing_return_pct: number | null;
  listing_close_return_pct?: number | null;
  listing_high_price?: number | null;
  listing_low_price?: number | null;
  industry_profile?: string;
  completeness_pct?: number | null;
  completeness?: CompletenessSummary | null;
  listing_data_status: DataStatus | null;
  listing_date_status?: "actual" | "expected" | null;
  nse_symbol?: string | null;
  freshness: Freshness;
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
  basis?: string | null;
  period_label?: string | null;
  face_value?: number | null;
  closing_price?: number | null;
  eps_basic?: number | null;
  eps_diluted?: number | null;
  nav_per_share?: number | null;
  ronw_pct?: number | null;
  document_id?: number | null;
  page?: number | null;
  check_note?: string | null;
  nse_symbol?: string | null;
  latest_price?: number | null;
  latest_price_date?: string | null;
  pe_at_latest_price?: number | null;
}

export interface DocumentFact {
  value: number | string;
  page: number;
  text: string;
  basis: string | null;
  document_id: number;
  read_at: string;
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
  archive_url?: string | null;
  sha256?: string | null;
  source_key?: string | null;
  size_bytes?: number | null;
  original_filename?: string | null;
  original_retained?: boolean;
  extraction_status?: "pending" | "extracted" | "partial" | "failed" | "not_found" | "skipped" | "duplicate";
  extraction_method?: string | null;
  attempts?: number;
  next_attempt_at?: string | null;
  published_date?: string | null;
  extraction_error?: string | null;
  extracted_at?: string | null;
  parser_version?: string | null;
  last_checked_at?: string | null;
  file_url?: string | null;
}

export type IssueFactUnit = "text" | "inr" | "inr_range" | "cr" | "shares" | "pct" | "x" | "list" | "url" | "split";

/** One key issue fact with its source and status, or the reason it is missing (GET /api/ipos/{id} → issue_facts). */
export interface IssueFact {
  key: string;
  label: string;
  value: number | string | string[] | number[] | { fresh_cr: number | null; ofs_cr: number | null; fresh_shares?: number | null; ofs_shares?: number | null } | null;
  unit: IssueFactUnit;
  status: "verified" | "estimated" | "derived" | "unverified" | "unavailable" | "pending" | string;
  source?: string | null;
  basis?: string | null;
  page?: number | null;
  document_id?: number | null;
  url?: string | null;
  reason: string | null;
}

export interface IpoDetail extends IpoSummary {
  description: string | null;
  business_model: string | null;
  revenue_sources: { segment: string; share_pct: number }[] | null;
  website: string | null;
  customer_concentration_pct: number | null;
  face_value: number | null;
  isin: string | null;
  issue_method: "book_built" | "fixed_price" | null;
  listing_exchanges: string | null;
  pre_issue_shares: number | null;
  post_issue_shares: number | null;
  dilution_pct: number | null;
  promoter_holding_pre_pct: number | null;
  promoter_holding_post_pct: number | null;
  use_of_proceeds: { purpose: string; amount_cr: number | null }[] | null;
  risk_disclosures_reviewed: boolean;
  research_notes: string | null;
  registrar: string | null;
  lead_managers: string | null;
  offer_document_url: string | null;
  basis_of_price_url: string | null;
  issue_size_text: string | null;
  shares_offered: number | null;
  key_dates: KeyDate[];
  subscription_history: { as_of: string; category: string; times_subscribed: number; basis?: string; data_status: DataStatus }[];
  grey_market: { caveat: string; observations: { observed_at: string; premium_inr: number; data_status: DataStatus }[] };
  peers: Peer[];
  disclosures: Disclosure[];
  documents: DocumentInfo[];
  document_facts: Partial<Record<"pre_issue_shares" | "customer_concentration_pct" | "auditor_qualifications" | "contingent_liabilities_cr" | "business_overview", DocumentFact>> & {
    lender_kpis?: Omit<DocumentFact, "value"> & { value: Record<string, { label: string; values_as_printed: string[]; page: number; note: string }> };
  };
  classification: Classification | null;
  issue_facts?: IssueFact[];
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

export type ComponentKey = "profitability" | "growth" | "financial_health" | "cash_flow" | "valuation";

export interface Statement {
  id: number;
  period_label: string;
  period_end: string;
  period_months: number;
  currency: string;
  unit: string;
  basis: "consolidated" | "standalone" | "unknown";
  data_status: DataStatus;
  validation_status: "passed" | "partial" | "failed" | "not_checked";
  validation: { check: string; formula: string; lhs: number; rhs: number; difference: number; passed: boolean; hard: boolean }[];
  document_id: number | null;
  source: SourceBrief | null;
  [field: string]: unknown;
}

export interface Metric {
  key: string;
  label: string;
  value: number | null;
  unit: string;
  formula: string;
  period: string | null;
  inputs: Record<string, unknown>;
  status: "ok" | "unavailable" | "not_meaningful" | "not_applicable";
  reason: string | null;
  note: string | null;
}

export interface RatioHistoryRow {
  period: string;
  period_end: string;
  [key: string]: number | string | null;
}

export interface Financials {
  ipo_id: number;
  company_name: string;
  currency: string;
  unit: string;
  basis_used: string | null;
  statements: Statement[];
  metrics: Record<string, Metric>;
  ratio_history: RatioHistoryRow[];
  superseded: { id: number; period_label: string; basis: string; data_status: DataStatus; created_at: string; document_id: number | null }[];
  formulas: Record<string, string>;
  note: string;
}

export interface LineItem {
  field: string;
  raw_label: string;
  raw_text: string;
  unit: string;
  value: number | null;
  page: number | null;
  status: "extracted" | "derived";
  validation_status: string;
}

export interface StatementProvenance {
  statement_id: number;
  period_label: string;
  basis: string;
  data_status: DataStatus;
  validation_status: string;
  checks: Statement["validation"];
  document_id: number | null;
  items: LineItem[];
}

export interface ComponentItem {
  key: string;
  weight: number;
  score: number | null;
  note: string | null;
  available: boolean;
  applicable?: boolean;
}

export interface ComponentResult {
  name: ComponentKey;
  label: string;
  score: number | null;
  coverage: number | null;
  applicable?: boolean;
  weights?: Record<string, number>;
  items: ComponentItem[];
  reason: string | null;
}

export interface Classification {
  sector: string;
  profile: string;
  status: "extracted" | "unavailable";
  confidence: number;
  evidence: { phrase: string; count: number; pages: number[]; in_company_name?: boolean }[];
  runner_up: string | null;
  note: string | null;
  method: string;
  document_id?: number;
  classified_at?: string;
}

export interface RiskComponent {
  key: string;
  label: string;
  points: number | null;
  weight: number;
  kind: "derived from financials" | "derived from issue terms" | "disclosed fact" | "data quality";
  detail: string | null;
  available: boolean;
  applicable?: boolean;
}

export interface Quartiles { min: number | null; q1: number | null; median: number | null; q3: number | null; max: number | null }

export interface PeerSummary {
  count: number;
  with_pe: number;
  with_pb: number;
  min_peers: number;
  median_pe: number | null;
  median_pb: number | null;
  median_ronw_pct: number | null;
  pe_quartiles?: Quartiles | null;
  pb_quartiles?: Quartiles | null;
  ronw_quartiles?: Quartiles | null;
  excluded_loss_making?: number;
  basis: string[];
  periods: string[];
  note: string | null;
}

export interface ScoreResult {
  config_version: string;
  status: "complete" | "partial" | "insufficient";
  as_of: string;
  basis: string | null;
  periods_used: string[];
  latest_period: string | null;
  price: { price: number | null; price_basis: string | null; price_status: "verified" | "estimated" | null; post_issue_shares: number | null;
           post_issue_shares_status: string | null; post_issue_shares_formula: string | null; market_cap_cr: number | null };
  metrics: Record<string, Metric>;
  components: Record<ComponentKey, ComponentResult>;
  fundamental: { score: number | null; classification: string | null; weight_coverage: number; renormalized: boolean; excluded?: string[]; not_applicable?: string[];
                 reason: string | null; formula: string; weights: Record<ComponentKey, number>; note?: string | null };
  composite: number | null;
  classification: string | null;
  risk: { score: number | null; level: RiskLevel; components: RiskComponent[]; weight_coverage: number | null; formula: string;
          governance_disclosure?: { score: number | null; components: string[]; available: number; of: number; formula: string; reason: string | null } };
  profile?: { key: string; label: string };
  applicability?: { key: string; label: string; reason: string }[];
  period_sources?: { label: string; period_end: string; basis: string; data_status: DataStatus; validation_status: string; document_id: number | null; source_record_id: number | null }[];
  peers: PeerSummary | null;
  coverage: number | null;
  missing: string[];
  warnings: string[];
  disclaimer: string;
  input_fingerprint: string;
  calculated_at: string | null;
}

export interface SensitivityRow {
  label: string;
  price: number;
  pe: number | null;
  pb: number | null;
  ev_ebitda: number | null;
  price_to_sales?: number | null;
  market_cap_cr: number | null;
  valuation_score: number | null;
  fundamental_score: number | null;
}

export interface CalendarEvent {
  date: string;
  event: "open" | "close" | "allotment" | "refund" | "demat_credit" | "listing";
  label: string;
  status: "confirmed" | "estimated";
  ipo_id: number;
  company_name: string;
  issue_type: "mainboard" | "sme";
  ipo_status: IpoStatus;
  stage: IpoStage;
  data_mode: string;
  price_band: [number | null, number | null] | null;
}

export interface CalendarResponse {
  start: string;
  end: string;
  today: string;
  events: CalendarEvent[];
  note: string;
}

export interface ExceptionsReport {
  documents: { document_id: number; ipo_id: number | null; company_name: string | null; status: string; error: string | null; extracted_at: string | null; archive_url: string | null }[];
  statements_requiring_review: { statement_id: number; ipo_id: number | null; company_name: string | null; period_label: string; basis: string;
                                 failed_checks: { check: string; formula: string; difference: number }[] }[];
  field_conflicts: { ipo_id: number; company_name: string | null; field: string; value: string; source_key: string; observed_at: string }[];
  peer_rows_requiring_review: { ipo_id: number; company_name: string | null; peer: string; note: string | null; page: number | null }[];
  documents_pending: number;
  note: string;
}

export interface ExtractionRun {
  id: number;
  status: string;
  parser_version: string;
  started_at: string;
  finished_at: string | null;
  pages_scanned: number;
  statements: { kind: string; page: number; basis: string; unit: string | null; title: string; periods: string[]; fields: string[] }[];
  checks: { period: string; basis: string; status: string; checks: Statement["validation"] }[];
  warnings: string[];
  error: string | null;
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





export interface ReportSection {
  key: string;
  title: string;
  paragraphs: string[];
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
  config_version: string;
  scores: { status: string; composite: number | null; classification: string | null; profitability: number | null; growth: number | null;
            financial_health: number | null; cash_flow: number | null; valuation: number | null; risk: number | null; risk_level: RiskLevel; coverage: number };
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


export interface ModelsStatus {
  retrieval: { chunks: number; mode: string };
  scoring: { active_version: string; description: string };
}

export interface DashboardSummary {
  as_of: string;
  totals: { ipos: number; by_status: Partial<Record<IpoStatus, number>>; by_stage: Partial<Record<IpoStage, number>>; documents: number;
            documents_extracted: number; scored: number; recently_listed_30d: number; issue_size_open_upcoming_cr: number;
            pipeline?: number; recently_closed_14d?: number };
  data_modes: Record<string, number>;
  demo_included: boolean;
  demo_available: boolean;
  synthetic_share: number;
  upcoming: IpoSummary[];
  awaiting: IpoSummary[];
  recently_closed?: IpoSummary[];
  recently_listed: IpoSummary[];
  pipeline?: IpoSummary[];
  data_health?: { median_completeness: number | null; readiness: Record<Readiness, number>; distribution: { bucket: string; count: number }[]; not_computed: number };
  calendar: { date: string; event: "opens" | "closes" | "lists"; estimated: boolean; ipo_id: number; company_name: string; issue_type: string }[];
  activity: { month: string; mainboard: number; sme: number; issue_size_cr: number }[];
  scatter: { id: number; name: string; score: number; risk: number; data_status: DataStatus; sector: string; issue_type: string }[];
  score_distribution: { label: string; count: number }[];
  risk_distribution: { level: Exclude<RiskLevel, null>; count: number }[];
  sectors: { sector: string; count: number; issue_size_cr: number }[];
  issue_sizes: { bucket: string; count: number }[];
  recent_changes: (FieldChangeRow & { company_name: string | null })[];
  sources: SourceHealth[];
  freshness: { latest_record_update: string | null; last_successful_sync_at: string | null; last_successful_job: string | null };
  watchlist: IpoSummary[];
  recent_reports: { id: number; title: string; ipo_id: number | null; generator: string; created_at: string }[];
}


export interface SourceHealth {
  key: string;
  name: string;
  base_url: string;
  authority: string;
  access_mode: "automatic" | "manual_only";
  health_status: string;
  last_attempt_at: string | null;
  last_success_at: string | null;
  last_error: string | null;
  consecutive_failures: number;
  requests_made: number;
  is_stale: boolean;
  notes: string | null;
}

export interface FieldChangeRow {
  ipo_id: number;
  field: string;
  old_value: unknown;
  new_value: unknown;
  source_key: string;
  changed_at: string;
}

export interface SchedulerStatus {
  running: boolean;
  enabled: boolean;
  note?: string;
  jobs?: { id: string; next_run_at: string | null; interval_minutes: number }[];
}

export interface FreshnessReport {
  last_successful_sync_at: string | null;
  last_successful_job: string | null;
  sources: SourceHealth[];
  stale_records: { id: number; company_name: string; status: IpoStatus; reasons: string[] }[];
  missing_critical_fields: { id: number; company_name: string; status: IpoStatus; missing: string[] }[];
  recent_changes: FieldChangeRow[];
  scheduler: SchedulerStatus;
}

export interface SyncJob {
  id: number;
  job_type: string;
  trigger: string;
  status: "running" | "success" | "partial" | "failed" | "skipped";
  started_at: string;
  finished_at: string | null;
  records_discovered: number;
  records_created: number;
  records_updated: number;
  fields_changed: number;
  requests_made: number;
  errors: Record<string, unknown>[];
  detail: Record<string, unknown>;
  warning_count: number;
}

export interface SyncStatus {
  scheduler: SchedulerStatus;
  intervals_minutes: Record<string, number>;
  jobs: SyncJob[];
  sources: SourceHealth[];
}

export interface MarketOverview {
  as_of: string;
  counts: Partial<Record<IpoStatus, number>>;
  open: IpoSummary[];
  opening_soon: IpoSummary[];
  listing_soon: IpoSummary[];
  recently_listed: IpoSummary[];
  listing_stats_30d: { count_with_verified_return: number; positive: number; negative: number; median_return_pct: number | null; note: string };
  data: { last_successful_sync_at: string | null; stale_records: number; live_records: number; demo_records_included: boolean };
}

export interface SubscriptionDetail {
  ipo_id: number;
  company_name: string;
  status: IpoStatus;
  latest_as_of: string | null;
  timezone: string | null;
  basis_note: string;
  latest: { category: string; times_subscribed: number; shares_offered: number | null; shares_bid: number | null; data_status: DataStatus }[];
  history: { as_of: string; category: string; times_subscribed: number; basis: string }[];
  freshness: Freshness;
  source_url: string | null;
}

export interface FieldProvenance {
  value: unknown;
  source_key: string;
  source_url: string | null;
  first_seen_at: string;
  last_verified_at: string;
  data_status: DataStatus;
  basis: string | null;
  conflicts: number;
}

// ---------------------------------------------------------------- completeness, peers, history, industries, methodology, health
export type FieldStatus = "available" | "estimated" | "unverified" | "requires_review" | "unavailable" | "not_applicable" | "pending" | "not_meaningful";

export interface FieldState {
  key: string;
  label: string;
  group: string;
  status: FieldStatus;
  value: unknown;
  unit: string | null;
  source: string | null;
  period: string | null;
  as_of: string | null;
  data_status: string | null;
  stale: boolean;
  reason: string | null;
  extra: Record<string, unknown>;
}

export interface PipelineStage { stage: string; label: string; status: "done" | "pending" | "failed"; detail: string | null }

export interface Completeness {
  ipo_id: number;
  stage: IpoStage;
  overall_pct: number;
  readiness: { level: Readiness; label: string; reason: string | null };
  groups: { key: string; label: string; pct: number | null; available: number; partial: number; missing: number; not_applicable: number; pending: number; fields: FieldState[] }[];
  pipeline: PipelineStage[];
  sources_tried: { source: string; status: string; detail: string | null; document_id?: number; url?: string | null }[];
  missing_important: FieldState[];
  computed_at: string;
  note: string;
}

export interface PeerRow extends Peer {
  price_age_days: number | null;
  stale: boolean;
  used_in_median: boolean;
}

export interface PeerAnalysis {
  ipo_id: number;
  peers: PeerRow[];
  benchmarks: PeerSummary;
  ipo_multiples: { pe: number | null; pb: number | null; price_basis: string | null; pe_vs_median_pct: number | null; pb_vs_median_pct: number | null };
  selection_rationale: string;
  similar_ipos: { id: number; company_name: string; issue_type: string; open_date: string | null; issue_size_cr: number | null; composite: number | null;
                  risk: number | null; pe: number | null; completeness_pct: number | null }[];
  similar_basis: string | null;
  warnings: string[];
  note: string;
}

export interface OutcomeStats { n: number; mean: number | null; median: number | null; positive_share: number | null; min: number | null; max: number | null }

export interface HistoryRow {
  id: number;
  company_name: string;
  sector: string;
  issue_type: "mainboard" | "sme";
  listing_date: string | null;
  issue_size_cr: number | null;
  final_issue_price: number | null;
  listing_open: number | null;
  listing_high: number | null;
  listing_low: number | null;
  listing_close: number | null;
  listing_gain_pct: number | null;
  listing_close_return_pct: number | null;
  listing_high_return_pct: number | null;
  listing_low_return_pct: number | null;
  listing_data_status: DataStatus | null;
  subscription_total: number | null;
  subscription_as_of: string | null;
  pre_listing_score: number | null;
  score_classification: string | null;
  risk: number | null;
  score_available: boolean;
  point_in_time_ok: boolean | null;
  point_in_time_note: string | null;
  data_mode: string;
}

export interface HistoryResponse {
  items: HistoryRow[];
  count: number;
  with_listing_price: number;
  summary: { listing_gain: OutcomeStats; listing_close_return: OutcomeStats };
  by_sector: (OutcomeStats & { group: string; median_close_return: number | null })[];
  by_issue_type: (OutcomeStats & { group: string; median_close_return: number | null })[];
  by_issue_size: (OutcomeStats & { group: string })[];
  score_vs_outcome: { pairs: { score: number; listing_gain_pct: number }[]; n: number; spearman_rho: number | null; note: string };
  formulas: Record<string, string>;
  source: string;
}

export interface IndustryProfile {
  key: string;
  label: string;
  not_applicable: string[];
  reasons: Record<string, string>;
  not_applicable_components: string[];
  weights: Record<string, Record<string, number>>;
  ranges: Record<string, Record<string, number | string>>;
}

export interface IndustriesResponse {
  sectors: { sector: string; profile: string; ipos: number; scored: number; benchmarks: Record<string, { median: number; n: number }>; indicative_only: boolean }[];
  profiles: IndustryProfile[];
  note: string;
}

export interface MethodologyResponse {
  active_version: string;
  description: string;
  config: {
    version: string;
    weights: Record<string, Record<string, number>>;
    ranges: Record<string, Record<string, number | string>>;
    risk_ranges: Record<string, Record<string, number | string>>;
    coverage: { component_min: number; overall_min: number; required_components: string[]; min_annual_periods: number };
    peers: { min_peers: number };
    usable_statuses: string[];
    classification: [number, string][];
    risk_levels: [number, string][];
    profiles: Record<string, Omit<IndustryProfile, "key">>;
  };
  formulas: Record<string, string>;
  component_labels: Record<string, string>;
  disclaimer: string;
  parser_version: string;
  versions: { version: string; is_active: boolean; created_at: string; description: string }[];
}

export interface FieldSpec {
  key: string; label: string; group: string; group_label: string; dtype: string; unit: string | null; primary: string; secondary: string[];
  normalization: string; validation: string; refresh: string; stale_after_hours: number | null; fallback: string; stages: string[];
}

export interface FieldRegistry { groups: Record<string, string>; group_weights: Record<string, number>; fields: FieldSpec[] }

export interface SystemHealth {
  as_of: string;
  scheduler: SchedulerStatus;
  sources: SourceHealth[];
  jobs_24h: { job_type: string; runs: number; success: number; partial: number; failed: number; skipped: number; requests: number;
              last_status: string | null; last_finished_at: string | null; last_error: string | null }[];
  documents: { by_source_and_status: Record<string, Record<string, number>>; total: number; parser_version: string; awaiting_reprocessing: number;
               retained_mb: number; storage_limit_mb: number; ocr_available: boolean; ocr_enabled: boolean; max_attempts: number };
  dead_letters: { document_id: number; ipo_id: number | null; title: string; attempts: number; error: string | null }[];
  backing_off: { document_id: number; ipo_id: number | null; title: string; attempts: number; next_attempt_at: string | null; error: string | null }[];
  pipeline_funnel: { stage: string; done: number; failed: number; pending: number }[];
  completeness: { ipos: number; computed: number; median: number | null; below_50: number };
  integrity: { statements_requiring_review: number; field_conflicts: number; stale_live_issues: { ipo_id: number; company_name: string; last_verified_at: string | null }[] };
  hosting_note: string;
  problems?: { level: "warning" | "error"; code: string; message: string }[];
  backups?: { enabled: boolean; every_hours: number; keep: number; count: number; last_at: string | null };
}
