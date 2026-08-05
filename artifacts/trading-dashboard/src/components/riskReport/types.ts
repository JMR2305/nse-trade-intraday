/** Shared TypeScript types for Risk Decision Report V2 */

export interface Gate {
  gate:      string;
  label:     string;
  passed:    boolean;
  reason:    string;
  is_global: boolean;
}

export interface Sizing {
  quantity:       number;
  entry_price:    number;
  stop_loss:      number;
  target_price:   number;
  position_value: number;
  risk_amount:    number;
  rr_ratio:       number;
}

export interface Candidate {
  symbol:                 string;
  sector:                 string;
  recommendation:         string;
  eligible:               boolean;
  failed_gates:           string[];
  gates:                  Gate[];
  sizing:                 Sizing;
  confidence:             number;
  opportunity_score:      number;
  trade_quality_score:    number;
  strategy_id?:           string;
  strategy_name?:         string;
  regime?:                string;
  expected_holding_days?: number;
}

export interface GatePressure {
  gate_id:      string;
  label:        string;
  is_global:    boolean;
  blocked:      number;
  blocked_pct:  number;
  blocked_7d?:  number;
  blocked_30d?: number;
  trend?:       string;
}

export interface HistoryEntry {
  date:           string;
  evaluated_at:   string;
  total_count:    number;
  blocked_count:  number;
  eligible_count: number;
  pass_rate:      number;
}

export interface Report {
  available:         boolean;
  reason?:           string;
  evaluated_at?:     string;
  scan_id?:          string;
  snapshot_ts?:      string;
  market_state?:     string;
  global_gates?:     Gate[];
  global_pass?:      boolean;
  candidates?:       Candidate[];
  total_count?:      number;
  eligible_count?:   number;
  blocked_count?:    number;
  gate_pressure?:    GatePressure[];
  top_blockers?:     string[];
  history_timeline?: HistoryEntry[];
  history_days?:     number;
  history_entries?:  number;
  label?:            string;
}

export interface SimSettings {
  minConfidence:   number;
  minOpportunity:  number;
  minRR:           number;
  minTradeQuality: number;
  sectorCap:       number;
  perStockCap:     number;
}
