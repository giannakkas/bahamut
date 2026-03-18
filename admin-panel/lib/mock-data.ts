import type {
  ConfigMap,
  ConfigOverride,
  SystemSummary,
  MarginalRiskData,
  LearningPattern,
  Alert,
  AuditLogEntry,
} from "@/types";

export const MOCK_SUMMARY: SystemSummary = {
  kill_switch: { active: false, reason: null, last_triggered: "2026-03-17T14:32:00Z" },
  safe_mode: { active: false, level: 0 },
  readiness: { score: 0.87, grade: "A-", components: { data: 0.95, model: 0.82, market: 0.84 } },
  confidence: { score: 0.79, trend: "stable", history: [0.72, 0.74, 0.76, 0.79, 0.78, 0.79] },
  risk_level: "MEDIUM",
  active_constraints: 3,
  portfolio_value: 127450.0,
  daily_pnl: 1247.5,
  daily_pnl_pct: 0.98,
  open_positions: 7,
  agents_active: 6,
  last_cycle: "2026-03-18T09:45:12Z",
};

export const MOCK_CONFIG: ConfigMap = {
  "scenario.count": { value: 5, type: "int", category: "scenario", description: "Number of scenarios to simulate", default: 5, min: 1, max: 20 },
  "scenario.weight_bull": { value: 0.25, type: "float", category: "scenario", description: "Bull scenario weight", default: 0.2, min: 0, max: 1 },
  "scenario.weight_bear": { value: 0.25, type: "float", category: "scenario", description: "Bear scenario weight", default: 0.2, min: 0, max: 1 },
  "scenario.weight_base": { value: 0.3, type: "float", category: "scenario", description: "Base scenario weight", default: 0.4, min: 0, max: 1 },
  "scenario.weight_stress": { value: 0.1, type: "float", category: "scenario", description: "Stress scenario weight", default: 0.1, min: 0, max: 1 },
  "scenario.weight_black_swan": { value: 0.1, type: "float", category: "scenario", description: "Black swan scenario weight", default: 0.1, min: 0, max: 1 },
  "marginal_risk.threshold": { value: 0.15, type: "float", category: "marginal_risk", description: "Max acceptable marginal risk", default: 0.2, min: 0, max: 1 },
  "marginal_risk.lookback_days": { value: 30, type: "int", category: "marginal_risk", description: "Lookback period for risk calc", default: 30, min: 5, max: 90 },
  "marginal_risk.decay_factor": { value: 0.94, type: "float", category: "marginal_risk", description: "Exponential decay for weighting", default: 0.95, min: 0.8, max: 1 },
  "quality_ratio.min_threshold": { value: 0.6, type: "float", category: "quality_ratio", description: "Minimum quality ratio to trade", default: 0.5, min: 0, max: 1 },
  "quality_ratio.weight_sharpe": { value: 0.4, type: "float", category: "quality_ratio", description: "Sharpe ratio weight in quality", default: 0.4, min: 0, max: 1 },
  "quality_ratio.weight_sortino": { value: 0.3, type: "float", category: "quality_ratio", description: "Sortino ratio weight", default: 0.3, min: 0, max: 1 },
  "quality_ratio.weight_calmar": { value: 0.3, type: "float", category: "quality_ratio", description: "Calmar ratio weight", default: 0.3, min: 0, max: 1 },
  "exposure.max_single": { value: 0.15, type: "float", category: "exposure", description: "Max single asset exposure", default: 0.2, min: 0.01, max: 0.5 },
  "exposure.max_sector": { value: 0.4, type: "float", category: "exposure", description: "Max sector exposure", default: 0.4, min: 0.1, max: 0.8 },
  "exposure.max_total": { value: 0.95, type: "float", category: "exposure", description: "Max total portfolio exposure", default: 1.0, min: 0.5, max: 1 },
  "kill_switch.enabled": { value: true, type: "bool", category: "kill_switch", description: "Enable kill switch engine", default: true },
  "kill_switch.drawdown_threshold": { value: 0.05, type: "float", category: "kill_switch", description: "Max drawdown before kill", default: 0.05, min: 0.01, max: 0.2 },
  "kill_switch.cooldown_minutes": { value: 60, type: "int", category: "kill_switch", description: "Cooldown after kill trigger", default: 60, min: 5, max: 1440 },
  "kill_switch.auto_resume": { value: true, type: "bool", category: "kill_switch", description: "Auto resume after cooldown", default: true },
  "safe_mode.enabled": { value: true, type: "bool", category: "safe_mode", description: "Enable safe mode", default: true },
  "safe_mode.reduce_exposure_pct": { value: 0.5, type: "float", category: "safe_mode", description: "Reduce exposure by % in safe mode", default: 0.5, min: 0.1, max: 0.9 },
  "deleverage.enabled": { value: true, type: "bool", category: "deleverage", description: "Enable auto deleverage", default: true },
  "deleverage.trigger_threshold": { value: 0.12, type: "float", category: "deleverage", description: "Risk threshold to trigger deleverage", default: 0.15, min: 0.05, max: 0.3 },
  "deleverage.speed": { value: 0.3, type: "float", category: "deleverage", description: "Deleverage speed (0=slow, 1=instant)", default: 0.3, min: 0.1, max: 1 },
  "allocator.method": { value: "risk_parity", type: "string", category: "allocator", description: "Allocation method", default: "risk_parity", options: ["equal_weight", "risk_parity", "mean_variance", "kelly"] },
  "allocator.rebalance_frequency": { value: "4h", type: "string", category: "allocator", description: "Rebalance frequency", default: "4h", options: ["15m", "1h", "4h", "1d"] },
  "confidence.min_trade": { value: 0.65, type: "float", category: "confidence", description: "Min confidence to execute trade", default: 0.6, min: 0, max: 1 },
  "confidence.agent_weight_trend": { value: 0.2, type: "float", category: "confidence", description: "Trend agent weight", default: 0.167, min: 0, max: 1 },
  "confidence.agent_weight_momentum": { value: 0.2, type: "float", category: "confidence", description: "Momentum agent weight", default: 0.167, min: 0, max: 1 },
  "confidence.agent_weight_sentiment": { value: 0.15, type: "float", category: "confidence", description: "Sentiment agent weight", default: 0.167, min: 0, max: 1 },
  "confidence.agent_weight_fundamentals": { value: 0.15, type: "float", category: "confidence", description: "Fundamentals agent weight", default: 0.167, min: 0, max: 1 },
  "confidence.agent_weight_volatility": { value: 0.15, type: "float", category: "confidence", description: "Volatility agent weight", default: 0.167, min: 0, max: 1 },
  "confidence.agent_weight_correlation": { value: 0.15, type: "float", category: "confidence", description: "Correlation agent weight", default: 0.167, min: 0, max: 1 },
  "profile.risk_tolerance": { value: "moderate", type: "string", category: "profile", description: "Risk tolerance profile", default: "moderate", options: ["conservative", "moderate", "aggressive"] },
  "readiness.min_score": { value: 0.7, type: "float", category: "readiness", description: "Min readiness to trade", default: 0.7, min: 0, max: 1 },
  "readiness.data_weight": { value: 0.4, type: "float", category: "readiness", description: "Data readiness weight", default: 0.33, min: 0, max: 1 },
  "readiness.model_weight": { value: 0.3, type: "float", category: "readiness", description: "Model readiness weight", default: 0.33, min: 0, max: 1 },
  "readiness.market_weight": { value: 0.3, type: "float", category: "readiness", description: "Market readiness weight", default: 0.34, min: 0, max: 1 },
};

export const MOCK_RISK: MarginalRiskData = {
  total_risk: 0.128,
  expected_return: 0.067,
  quality_ratio: 0.72,
  contributors: [
    { asset: "BTC", risk: 0.042, weight: 0.25, contribution_pct: 32.8 },
    { asset: "ETH", risk: 0.031, weight: 0.18, contribution_pct: 24.2 },
    { asset: "SOL", risk: 0.019, weight: 0.12, contribution_pct: 14.8 },
    { asset: "AAPL", risk: 0.012, weight: 0.15, contribution_pct: 9.4 },
    { asset: "TSLA", risk: 0.01, weight: 0.1, contribution_pct: 7.8 },
    { asset: "NVDA", risk: 0.008, weight: 0.08, contribution_pct: 6.3 },
    { asset: "GOLD", risk: 0.006, weight: 0.12, contribution_pct: 4.7 },
  ],
  scenarios: [
    { name: "Bull", probability: 0.25, impact: 0.12, color: "#10b981" },
    { name: "Base", probability: 0.3, impact: 0.04, color: "#06b6d4" },
    { name: "Bear", probability: 0.25, impact: -0.08, color: "#f59e0b" },
    { name: "Stress", probability: 0.1, impact: -0.15, color: "#ef4444" },
    { name: "Black Swan", probability: 0.1, impact: -0.35, color: "#7c3aed" },
  ],
};

export const MOCK_AUDIT: AuditLogEntry[] = [
  { id: 1, timestamp: "2026-03-18T09:30:00Z", key: "kill_switch.drawdown_threshold", old_value: "0.07", new_value: "0.05", source: "user", user: "chris" },
  { id: 2, timestamp: "2026-03-18T08:15:00Z", key: "confidence.min_trade", old_value: "0.6", new_value: "0.65", source: "user", user: "chris" },
  { id: 3, timestamp: "2026-03-17T22:00:00Z", key: "safe_mode.enabled", old_value: "false", new_value: "true", source: "system", user: "auto" },
  { id: 4, timestamp: "2026-03-17T21:58:00Z", key: "kill_switch.enabled", old_value: "true", new_value: "true", source: "system", user: "auto" },
  { id: 5, timestamp: "2026-03-17T14:32:00Z", key: "exposure.max_single", old_value: "0.2", new_value: "0.15", source: "user", user: "chris" },
  { id: 6, timestamp: "2026-03-17T10:00:00Z", key: "allocator.method", old_value: "equal_weight", new_value: "risk_parity", source: "user", user: "chris" },
  { id: 7, timestamp: "2026-03-16T16:45:00Z", key: "deleverage.trigger_threshold", old_value: "0.15", new_value: "0.12", source: "user", user: "chris" },
  { id: 8, timestamp: "2026-03-16T09:00:00Z", key: "scenario.weight_bear", old_value: "0.2", new_value: "0.25", source: "system", user: "learning" },
  { id: 9, timestamp: "2026-03-15T18:30:00Z", key: "marginal_risk.threshold", old_value: "0.2", new_value: "0.15", source: "user", user: "chris" },
  { id: 10, timestamp: "2026-03-15T12:00:00Z", key: "confidence.agent_weight_trend", old_value: "0.167", new_value: "0.2", source: "system", user: "learning" },
];

export const MOCK_OVERRIDES: ConfigOverride[] = [
  { key: "exposure.max_single", value: 0.1, ttl: 3600, created: "2026-03-18T09:00:00Z", expires: "2026-03-18T10:00:00Z", reason: "Volatility spike" },
  { key: "safe_mode.reduce_exposure_pct", value: 0.7, ttl: 7200, created: "2026-03-18T08:00:00Z", expires: "2026-03-18T10:00:00Z", reason: "FOMC meeting" },
];

export const MOCK_LEARNING: LearningPattern[] = [
  { pattern: "Momentum reversal on high volume", frequency: 34, confidence: 0.82, win_rate: 0.71, last_seen: "2026-03-18T08:12:00Z" },
  { pattern: "Correlation breakdown BTC/ETH", frequency: 12, confidence: 0.74, win_rate: 0.67, last_seen: "2026-03-17T22:45:00Z" },
  { pattern: "Volatility cluster post-FOMC", frequency: 8, confidence: 0.88, win_rate: 0.75, last_seen: "2026-03-15T19:00:00Z" },
  { pattern: "Mean reversion after >2σ move", frequency: 21, confidence: 0.79, win_rate: 0.69, last_seen: "2026-03-18T06:30:00Z" },
  { pattern: "Sentiment divergence signal", frequency: 15, confidence: 0.68, win_rate: 0.6, last_seen: "2026-03-16T14:20:00Z" },
  { pattern: "Cross-asset momentum spillover", frequency: 9, confidence: 0.71, win_rate: 0.63, last_seen: "2026-03-17T11:00:00Z" },
];

export const MOCK_ALERTS: Alert[] = [
  { id: 1, type: "warning", message: "Confidence dropped below 0.8 threshold", timestamp: "2026-03-18T09:42:00Z", dismissed: false },
  { id: 2, type: "info", message: "Rebalance cycle completed successfully", timestamp: "2026-03-18T09:45:12Z", dismissed: false },
  { id: 3, type: "warning", message: "Active override: exposure.max_single (expires 10:00)", timestamp: "2026-03-18T09:00:00Z", dismissed: true },
];
