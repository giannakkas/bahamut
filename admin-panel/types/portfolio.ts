export interface KillSwitchState {
  active: boolean;
  reason: string | null;
  last_triggered: string;
}

export interface SafeModeState {
  active: boolean;
  level: number;
}

export interface ReadinessState {
  score: number;
  grade: string;
  components: {
    data: number;
    model: number;
    market: number;
  };
}

export interface ConfidenceState {
  score: number;
  trend: "rising" | "stable" | "falling";
  history: number[];
}

export interface SystemSummary {
  kill_switch: KillSwitchState;
  safe_mode: SafeModeState;
  readiness: ReadinessState;
  confidence: ConfidenceState;
  risk_level: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  active_constraints: number;
  portfolio_value: number;
  daily_pnl: number;
  daily_pnl_pct: number;
  open_positions: number;
  agents_active: number;
  last_cycle: string;
}

export interface RiskContributor {
  asset: string;
  risk: number;
  weight: number;
  contribution_pct: number;
}

export interface ScenarioResult {
  name: string;
  probability: number;
  impact: number;
  color: string;
}

export interface MarginalRiskData {
  total_risk: number;
  expected_return: number;
  quality_ratio: number;
  contributors: RiskContributor[];
  scenarios: ScenarioResult[];
}

export interface LearningPattern {
  pattern: string;
  frequency: number;
  confidence: number;
  win_rate: number;
  last_seen: string;
}

export interface Alert {
  id: number;
  type: "info" | "warning" | "error" | "critical";
  message: string;
  timestamp: string;
  dismissed: boolean;
}

export interface AISuggestion {
  key: string;
  current: number;
  suggested: number;
  reason: string;
}
