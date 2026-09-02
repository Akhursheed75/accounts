export type Currency = "USD" | "NIO";
export type MatchStatus = "MATCHED" | "POSSIBLE" | "UNMATCHED" | "IGNORED";

export interface ApiErrorBody {
  error: { code: string; message: string; details?: unknown };
}

export interface RoleBrief { id: number; code: string; name: string }

export interface Me {
  id: number;
  email: string;
  full_name: string;
  is_active: boolean;
  last_login_at: string | null;
  role: RoleBrief;
  permissions: string[];
  shop_ids: number[];
  has_global_scope: boolean;
}

export interface Shop {
  id: number; code: string; name: string; city_id: number | null;
  city_name: string | null; is_active: boolean; is_demo: boolean;
}

export interface City { id: number; name: string; country: string }

export interface BankAccount {
  id: number; bank_id: number; bank_code: string | null; bank_name: string | null;
  label: string; account_number: string; currency_code: Currency; is_active: boolean;
}

export interface Bank {
  id: number; code: string; name: string; parser_key: string | null;
  parser_available: boolean; is_active: boolean; accounts: BankAccount[];
}

export interface Page<T> { items: T[]; total: number; page: number; page_size: number }

export interface Transfer {
  id: number; bank_id: number; bank_code: string | null; bank_name: string | null;
  bank_account_id: number | null; currency_code: Currency; amount: string;
  reference: string | null; deposit_time: string | null; note: string;
  is_ignored: boolean; ignored_reason: string | null;
  match_status: MatchStatus; matched_transaction_id: number | null; suggestion_count: number;
}

export interface Expense {
  id: number; category: string; description: string; currency_code: Currency; amount: string;
}

export interface BaleRow {
  id: number; bale_type_id: number; bale_type_code: string | null;
  bale_type_name: string | null; opening_qty: number; received_qty: number;
  sold_qty: number; closing_qty: number;
}

export interface BaleType {
  id: number; code: string; name: string; weight_lbs: string | null;
  sort_order: number; is_active: boolean;
}

export interface BalanceStep {
  key: string; label: string; sign: number; amount: string; running_total: string;
}

export interface BalanceSide {
  steps: BalanceStep[]; computed: string; entered: string;
  difference: string; matches: boolean;
}

export interface DailyRecord {
  id: number; shop_id: number; shop_name: string | null; shop_code: string | null;
  business_date: string; status: string; bale_count: number; invoice_count: number;
  total_sales_usd: string; total_sales_nio: string;
  delivery_usd: string; delivery_nio: string;
  commercial_invoice_usd: string; commercial_invoice_nio: string;
  credit_usd: string; credit_nio: string;
  opening_balance_usd: string; opening_balance_nio: string;
  closing_balance_usd: string; closing_balance_nio: string;
  closing_balance_source: string; observations: string;
  created_at: string; updated_at: string; submitted_at: string | null;
  locked_at: string | null; is_demo: boolean;
  transfers: Transfer[]; expenses: Expense[]; bale_records: BaleRow[];
  transfer_totals: Record<string, string>; expense_totals: Record<string, string>;
  balance: Record<string, BalanceSide>;
}

export interface DailyRecordRow {
  id: number; shop_id: number; shop_name: string | null; business_date: string;
  status: string; bale_count: number; invoice_count: number;
  total_sales_usd: string; total_sales_nio: string;
  transfer_total_usd: string; transfer_total_nio: string;
  matched_count: number; possible_count: number; unmatched_count: number;
}

export interface Statement {
  id: number; bank_account_id: number; bank_id: number | null;
  bank_code: string | null; bank_name: string | null; account_label: string | null;
  currency_code: Currency | null; period_start: string | null; period_end: string | null;
  original_filename: string; file_size: number; page_count: number | null;
  status: string; parser_key: string | null; extraction_method: string;
  error_message: string | null; warnings: string[] | null;
  transaction_count: number; duplicate_count: number;
  statement_closing_balance: string | null; uploaded_by_id: number | null;
  created_at: string; processed_at: string | null; is_demo: boolean;
}

export interface Transaction {
  id: number; statement_id: number; bank_account_id: number; bank_id: number;
  bank_code: string | null; account_label: string | null;
  txn_date: string; value_date: string | null; description: string;
  reference: string | null; external_id: string | null; movement_type: string | null;
  debit: string; credit: string; amount: string; direction: "CREDIT" | "DEBIT";
  currency_code: Currency; running_balance: string | null;
  extraction_confidence: number | null; page_number: number | null;
  is_ignored: boolean; match_status: MatchStatus;
  matched_transfer_id: number | null; suggestion_count: number;
}

export interface ScoreSignal { signal: string; points: number; detail: string }

export interface Match {
  id: number; shop_transfer_id: number; bank_transaction_id: number;
  status: string; match_type: string; confidence: number;
  amount_delta: string; date_delta_days: number;
  score_breakdown: ScoreSignal[] | null; is_active: boolean;
  matched_by_name: string | null; matched_at: string | null;
  unmatched_by_name: string | null; unmatched_at: string | null; note: string | null;
}

export interface TransferSide {
  id: number; shop_id: number; shop_name: string | null; business_date: string;
  bank_id: number; bank_code: string | null; currency_code: Currency;
  amount: string; reference: string | null; note: string; is_ignored: boolean;
}

export interface ReconciliationRow {
  transfer: TransferSide;
  status: MatchStatus;
  confirmed: Match | null;
  confirmed_transaction: Transaction | null;
  suggestions: Match[];
  suggested_transactions: Transaction[];
  history: Match[];
}

export interface Dashboard {
  range: { from: string; to: string };
  sales: { USD: string; NIO: string; bales: number; invoices: number; records: number };
  shop_transfers: Record<string, string>;
  bank_received: Record<string, string>;
  reconciliation: {
    counts: Record<string, number>;
    amounts: Record<string, Record<string, string>>;
  };
  shops: { shop_id: number; name: string; code: string; USD: string; NIO: string; records: number }[];
  banks: { bank_id: number; code: string; name: string; USD: string; NIO: string; transfer_count: number }[];
  trend: { date: string; USD: string; NIO: string }[];
}

export interface AuditRow {
  id: number; user_id: number | null; user_email: string | null; user_name: string | null;
  action: string; module: string; record_type: string | null; record_id: string | null;
  summary: string | null; old_values: Record<string, unknown> | null;
  new_values: Record<string, unknown> | null; ip_address: string | null; created_at: string;
}

export interface ReportColumn { key: string; label: string; kind: string }

export interface ReportResult {
  key: string; title: string; description: string; generated_at: string;
  columns: ReportColumn[]; rows: Record<string, string | number>[];
  totals: Record<string, Record<string, string> | string>;
  filters: Record<string, string | number | null>;
}

export interface MatchSettings {
  date_window_days: number; amount_tolerance: string; auto_confirm_score: number;
  suggest_score: number; auto_confirm_requires_unique: boolean;
  match_debit_transactions: boolean;
}

export interface BalanceComponent { key: string; label: string; sign: number; enabled: boolean }

export interface SystemSettings {
  company_name: string; base_currency: string;
  balance_components: BalanceComponent[];
  allow_shop_edit_after_submit: boolean; lock_records_after_days: number;
}

export interface UserRow {
  id: number; email: string; full_name: string; is_active: boolean;
  role_id: number; role_name: string; shop_ids: number[];
}

export interface Role {
  id: number; code: string; name: string; description: string;
  is_system: boolean; permissions: string[]; user_count: number;
}

export interface Permission { id: number; code: string; description: string }

export interface UnmatchedSummary {
  shop_payments: TransferSide[];
  bank_transactions: Transaction[];
  totals: {
    shop_payments: { count: number; USD: string; NIO: string };
    bank_transactions: { count: number; USD: string; NIO: string };
  };
}
