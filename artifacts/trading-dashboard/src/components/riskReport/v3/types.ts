/** V3 AI Risk Intelligence & Optimization Center — TypeScript interfaces */

export interface FalseRejectionEntry {
  symbol:              string;
  rejected_at:         string;
  failed_gates:        string[];
  confidence:          number;
  rr_ratio:            number;
  price_at_rejection:  number | null;
  highest_price:       number | null;
  lowest_price:        number | null;
  current_price:       number | null;
  max_gain_pct:        number | null;
  max_loss_pct:        number | null;
  classification:      "false_rejection" | "correct_rejection" | "still_monitoring";
  days_monitored:      number;
  strategy:            string;
  sector:              string;
  regime:              string;
}

export interface GateAccuracyRow {
  gate_id:               string;
  label:                 string;
  trades_blocked:        number;
  correct_decisions:     number;
  incorrect_decisions:   number;
  trades_became_winners: number;
  trades_became_losers:  number;
  accuracy_pct:          number;
}

export interface LeakagePeriod {
  total_rejected:                number;
  resolved:                      number;
  potential_winners_missed:       number;
  correct_rejections:            number;
  potential_profit_missed_inr:   number;
  potential_loss_avoided_inr:    number;
  estimated_alpha_lost_inr:      number;
  false_rejection_pct:           number | null;
}

export interface ThresholdOptimizerRow {
  gate_id:                 string;
  label:                   string;
  current_value:           number;
  suggested_value:         number;
  direction:               string;
  false_rejection_pct:     number;
  correct_rejection_pct:   number | null;
  sample_size:             number;
  reason:                  string;
  expected_approved_trades:number;
  expected_win_rate:        number | null;
}

export interface RegimeRow {
  regime:             string;
  min_confidence:     number;
  min_risk_reward:    number;
  min_trade_quality:  number;
  sector_cap:         number;
  per_stock_cap:      number;
  rationale:          string;
}

export interface StrategyRow {
  strategy:            string;
  total_rejections:    number;
  false_rejection_pct: number | null;
  avg_confidence:      number | null;
  avg_rr:              number | null;
  paper_trades_count:  number;
}

export interface PredictorRow {
  symbol:                 string;
  eligible:               boolean;
  probability_success:    number;
  probability_failure:    number;
  expected_return_pct:    number;
  expected_drawdown_pct:  number;
  expected_holding_days:  number;
  prediction_confidence:  string;
  confidence_score:       number;
  opportunity_score:      number;
  trade_quality_score:    number;
  rr_ratio:               number;
}

export interface LearningStage {
  id:     string;
  label:  string;
  status: "active" | "pending";
}

export interface ThresholdImpactRow {
  gate_id:                       string;
  label:                         string;
  rejected_trades:               number;
  would_have_been_winners:       number;
  would_have_been_losers:        number;
  estimated_profit_missed_inr:   number;
  estimated_loss_avoided_inr:    number;
  net_impact_inr:                number;
  recommendation:                "keep" | "review" | "relax" | "tighten";
}

export interface CalibrationPoint {
  bucket:                   string;
  predicted_confidence_pct: number;
  actual_success_rate_pct:  number;
  confidence_drift:         number;
  sample_size:              number;
}

export interface OptDashboard {
  overall_risk_accuracy:   number | null;
  false_rejection_rate:    number | null;
  correct_rejection_rate:  number | null;
  opportunity_leakage_pct: number | null;
  threshold_stability_pct: number | null;
  learning_progress_pct:   number;
  optimization_score:      number | null;
  total_tracked:           number;
  total_resolved:          number;
  history_days:            number;
  data_quality:            string;
}

export interface V3Analytics {
  available:     boolean;
  generated_at:  string;
  cache_ttl_s:   number;
  tracker_count: number;
  history_entries:number;
  s1_false_rejections: {
    summary: { false: number; correct: number; monitoring: number; total: number };
    by_period: Record<string, FalseRejectionEntry[]>;
  };
  s2_gate_accuracy:       GateAccuracyRow[];
  s3_opportunity_leakage: {
    today:      LeakagePeriod;
    this_week:  LeakagePeriod;
    this_month: LeakagePeriod;
    daily_trend: Array<{ date: string; total_rejected: number; total_evaluated: number }>;
  };
  s4_threshold_optimizer:      ThresholdOptimizerRow[];
  s5_regime_optimization:      RegimeRow[];
  s6_strategy_effectiveness:   StrategyRow[];
  s7_outcome_predictor:        PredictorRow[];
  s8_learning_loop: {
    has_data:              boolean;
    patterns_discovered?:  number;
    knowledge_updates?:    number;
    last_learning_at?:     string;
    stages:                LearningStage[];
    future_recommendations?: string[];
  };
  s9_threshold_impact:          ThresholdImpactRow[];
  s10_ai_coach:                 string[];
  s11_weekly_report:            Record<string, unknown>;
  s12_monthly_report:           Record<string, unknown>;
  s13_confidence_calibration: {
    calibration_points:  CalibrationPoint[];
    average_drift:       number;
    calibration_error:   number;
    calibration_status:  string;
    calibration_note:    string;
    sample_size:         number;
    insufficient_data:   boolean;
  };
  s14_sandbox_data: {
    current_thresholds:     Record<string, number>;
    suggested_thresholds:   Record<string, number>;
    historical_tracker_count:number;
    resolved_count:         number;
  };
  s15_optimization_dashboard: OptDashboard;
  label: string;
}
