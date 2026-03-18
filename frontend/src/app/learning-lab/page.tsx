'use client';

import { useEffect, useState, useCallback } from 'react';
import AppShell from '@/components/layout/AppShell';
import { api } from '@/lib/api';

export default function LearningLabPage() {
  const [fitness, setFitness] = useState<any>(null);
  const [meta, setMeta] = useState<any>(null);
  const [trust, setTrust] = useState<any[]>([]);
  const [leaderboard, setLeaderboard] = useState<any[]>([]);
  const [calibrations, setCalibrations] = useState<any[]>([]);
  const [thresholds, setThresholds] = useState<any>(null);
  const [trustHistory, setTrustHistory] = useState<any[]>([]);
  const [recalResult, setRecalResult] = useState<string | null>(null);
  const [readiness, setReadiness] = useState<any>(null);
  const [stressScenarios, setStressScenarios] = useState<any[]>([]);
  const [stressResults, setStressResults] = useState<any[]>([]);
  const [stressRunning, setStressRunning] = useState<string | null>(null);
  const [portfolioExp, setPortfolioExp] = useState<any>(null);
  const [portfolioFrag, setPortfolioFrag] = useState<any>(null);
  const [rankings, setRankings] = useState<any[]>([]);
  const [reallocLog, setReallocLog] = useState<any[]>([]);
  const [adaptiveRules, setAdaptiveRules] = useState<any[]>([]);
  const [scenarioSim, setScenarioSim] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const [f, m, t, l, c, th, h, rd, ss, sh, pe, pf, pr, rl, ar, sc] = await Promise.allSettled([
        api.getStrategyFitness(),
        api.getMetaEvaluation(),
        api.getTrustSummary(),
        api.getAgentLeaderboard(),
        api.getCalibrationHistory(5),
        api.getThresholds(),
        api.getTrustHistory(undefined, 20),
        api.getReadinessCheck(),
        api.getStressScenarios(),
        api.getStressHistory(5),
        api.getPortfolioExposure(),
        api.getPortfolioFragility(),
        api.getPortfolioRankings(),
        api.getReallocationLog(5),
        api.getAdaptiveRules(),
        api.getScenarioSim(),
      ]);
      if (f.status === 'fulfilled') setFitness(f.value);
      if (m.status === 'fulfilled') setMeta(m.value);
      if (t.status === 'fulfilled') setTrust(t.value);
      if (l.status === 'fulfilled') setLeaderboard(l.value);
      if (c.status === 'fulfilled') setCalibrations(c.value);
      if (th.status === 'fulfilled') setThresholds(th.value);
      if (h.status === 'fulfilled') setTrustHistory(h.value);
      if (rd.status === 'fulfilled') setReadiness(rd.value);
      if (ss.status === 'fulfilled') setStressScenarios(ss.value);
      if (sh.status === 'fulfilled') setStressResults(sh.value);
      if (pe.status === 'fulfilled') setPortfolioExp(pe.value);
      if (pf.status === 'fulfilled') setPortfolioFrag(pf.value);
      if (pr.status === 'fulfilled') setRankings(pr.value || []);
      if (rl.status === 'fulfilled') setReallocLog(rl.value || []);
      if (ar.status === 'fulfilled') setAdaptiveRules(ar.value || []);
      if (sc.status === 'fulfilled') setScenarioSim(sc.value || []);
    } catch (e) { console.error(e); }
    setLoading(false);
  }, []);

  useEffect(() => { load(); const iv = setInterval(load, 30000); return () => clearInterval(iv); }, [load]);

  const handleRecalibrate = async () => {
    try {
      const res = await api.emergencyRecalibrate();
      setRecalResult(`Emergency recalibration applied: ${res.notes?.join(', ') || 'done'}`);
      load();
    } catch (e: any) { setRecalResult(`Error: ${e.message}`); }
  };

  const handleRunStress = async (name: string) => {
    setStressRunning(name);
    try {
      const res = await api.runStressScenario(name);
      setStressResults(prev => [res, ...prev.slice(0, 4)]);
    } catch (e: any) { console.error(e); }
    setStressRunning(null);
  };

  const riskColor = (level: string) => {
    if (level === 'CRITICAL') return 'text-accent-crimson';
    if (level === 'ELEVATED') return 'text-accent-amber';
    return 'text-accent-emerald';
  };
  const trendIcon = (t: string) => t === 'IMPROVING' ? '↑' : t === 'DEGRADING' ? '↓' : '→';
  const trustColor = (s: number) => s >= 1.2 ? 'bg-accent-emerald' : s <= 0.7 ? 'bg-accent-crimson' : s <= 0.9 ? 'bg-accent-amber' : 'bg-accent-violet';
  const pct = (n: number) => `${(n * 100).toFixed(1)}%`;
  const fmt = (n: any) => typeof n === 'number' ? n.toFixed(3) : n;

  if (loading) return <AppShell><div className="flex items-center justify-center h-64 text-text-muted">Loading intelligence data...</div></AppShell>;

  return (
    <AppShell>
      <div className="space-y-5">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div>
              <h1 className="text-2xl font-bold">Learning Lab</h1>
              <p className="text-sm text-text-secondary mt-1">Self-learning intelligence • {fitness?.total_closed_trades || 0} trades analyzed</p>
            </div>
            {readiness && (
              <span className={`text-xs font-mono font-semibold px-2.5 py-1 rounded-full ${
                readiness.overall === 'READY' ? 'bg-accent-emerald/20 text-accent-emerald' :
                readiness.overall === 'CAUTION' ? 'bg-accent-amber/20 text-accent-amber' :
                'bg-accent-crimson/20 text-accent-crimson'
              }`}>{readiness.overall} ({readiness.pass_count}/{readiness.pass_count + readiness.warn_count + readiness.fail_count})</span>
            )}
          </div>
          <button onClick={handleRecalibrate}
            className="bg-accent-amber hover:bg-accent-amber/90 text-black font-semibold px-4 py-1.5 rounded-md text-sm">
            Emergency Recalibrate
          </button>
        </div>

        {recalResult && (
          <div className="p-3 bg-accent-amber/10 border border-accent-amber/30 rounded-md text-accent-amber text-sm">{recalResult}</div>
        )}

        {/* System Health (Meta-Learning) */}
        {meta && (
          <div className="bg-bg-secondary border border-border-default rounded-lg p-4">
            <div className="flex items-center gap-2 mb-3">
              <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wide">System Health</h2>
              <span className={`text-xs font-mono px-2 py-0.5 rounded ${riskColor(meta.risk_level)} bg-bg-primary`}>{meta.risk_level}</span>
            </div>
            <div className="grid grid-cols-4 gap-4">
              <div>
                <div className="text-xs text-text-muted">Trend</div>
                <div className="text-lg font-mono font-semibold">{trendIcon(meta.trend)} {meta.trend}</div>
                <div className="text-xs text-text-muted">score: {meta.trend_score > 0 ? '+' : ''}{meta.trend_score}</div>
              </div>
              <div>
                <div className="text-xs text-text-muted">Consensus Quality</div>
                <div className={`text-lg font-mono font-semibold ${meta.consensus_quality > 0.5 ? 'text-accent-emerald' : 'text-accent-crimson'}`}>{fmt(meta.consensus_quality)}</div>
                <div className="text-xs text-text-muted">{meta.consensus_quality > 0.6 ? 'Scores predict outcomes' : meta.consensus_quality > 0.4 ? 'Moderate' : 'Scores don\'t predict wins'}</div>
              </div>
              <div>
                <div className="text-xs text-text-muted">Agent Diversity</div>
                <div className={`text-lg font-mono font-semibold ${meta.agent_diversity_score > 0.5 ? 'text-accent-emerald' : 'text-accent-amber'}`}>{fmt(meta.agent_diversity_score)}</div>
                <div className="text-xs text-text-muted">{meta.agent_diversity_score > 0.7 ? 'Diverse opinions' : meta.agent_diversity_score > 0.4 ? 'Moderate' : 'Herding detected'}</div>
              </div>
              <div>
                <div className="text-xs text-text-muted">Model Freshness</div>
                <div className="text-lg font-mono font-semibold">{fitness?.model_freshness || 'cold_start'}</div>
                <div className="text-xs text-text-muted">{fitness?.avg_samples?.toFixed(0) || 0} avg samples</div>
              </div>
            </div>
            {meta.recommended_actions?.length > 0 && (
              <div className="mt-3 pt-3 border-t border-border-default">
                <div className="text-xs text-text-muted mb-1">Recommended Actions</div>
                {meta.recommended_actions.map((a: any, i: number) => (
                  <div key={i} className="text-xs font-mono text-accent-amber">{a.action}: {a.reason}</div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Strategy Fitness */}
        {fitness && (
          <div className="grid grid-cols-5 gap-3">
            {[
              { label: 'Win Rate', value: pct(fitness.win_rate || 0), good: (fitness.win_rate || 0) > 0.50 },
              { label: 'Profit Factor', value: (fitness.profit_factor || 0).toFixed(2), good: (fitness.profit_factor || 0) > 1.0 },
              { label: 'Closed Trades', value: fitness.total_closed_trades || 0, good: (fitness.total_closed_trades || 0) >= 10 },
              { label: 'Avg Trust', value: (fitness.avg_trust_score || 1).toFixed(3), good: (fitness.avg_trust_score || 1) >= 0.9 },
              { label: 'Trust Range', value: `${(fitness.trust_range?.min || 1).toFixed(2)}–${(fitness.trust_range?.max || 1).toFixed(2)}`, good: (fitness.trust_range?.min || 1) > 0.5 },
            ].map((m, i) => (
              <div key={i} className="bg-bg-secondary border border-border-default rounded-lg p-3 text-center">
                <div className="text-xs text-text-muted mb-1">{m.label}</div>
                <div className={`text-lg font-mono font-semibold ${m.good ? 'text-accent-emerald' : 'text-accent-crimson'}`}>{m.value}</div>
              </div>
            ))}
          </div>
        )}

        <div className="grid grid-cols-2 gap-5">
          {/* Trust Scores */}
          <div className="bg-bg-secondary border border-border-default rounded-lg p-4">
            <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wide mb-3">Agent Trust Scores</h2>
            <div className="space-y-2">
              {trust.map((a: any) => (
                <div key={a.agent_id} className="flex items-center gap-3">
                  <div className="text-xs font-mono w-28 truncate">{a.agent_id?.replace('_agent', '')}</div>
                  <div className="flex-1 bg-bg-primary rounded-full h-2.5 overflow-hidden">
                    <div className={`h-full rounded-full ${trustColor(a.global_trust)}`}
                         style={{ width: `${Math.min(100, (a.global_trust / 2) * 100)}%` }} />
                  </div>
                  <div className="text-xs font-mono w-12 text-right">{a.global_trust?.toFixed(3)}</div>
                  {a.provisional && <span className="text-[10px] text-text-muted">cold</span>}
                </div>
              ))}
            </div>
          </div>

          {/* Agent Leaderboard */}
          <div className="bg-bg-secondary border border-border-default rounded-lg p-4">
            <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wide mb-3">Agent Leaderboard</h2>
            {leaderboard.length === 0 ? (
              <div className="text-xs text-text-muted">No trade data yet</div>
            ) : (
              <table className="w-full text-xs">
                <thead><tr className="text-text-muted">
                  <th className="text-left pb-2">Agent</th>
                  <th className="text-right pb-2">Accuracy</th>
                  <th className="text-right pb-2">Trades</th>
                  <th className="text-right pb-2">Streak</th>
                </tr></thead>
                <tbody>
                  {leaderboard.map((a: any, i: number) => (
                    <tr key={i} className="border-t border-border-default/50">
                      <td className="py-1.5 font-mono">{a.agent}</td>
                      <td className={`py-1.5 text-right font-mono ${a.accuracy > 0.55 ? 'text-accent-emerald' : a.accuracy < 0.45 ? 'text-accent-crimson' : 'text-text-primary'}`}>{pct(a.accuracy)}</td>
                      <td className="py-1.5 text-right text-text-muted">{a.total_signals}</td>
                      <td className="py-1.5 text-right font-mono">{a.best_streak > 0 ? `+${a.best_streak}` : a.worst_streak}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-5">
          {/* Trust History */}
          <div className="bg-bg-secondary border border-border-default rounded-lg p-4">
            <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wide mb-3">Recent Trust Changes</h2>
            {trustHistory.length === 0 ? (
              <div className="text-xs text-text-muted">No trust updates yet</div>
            ) : (
              <div className="space-y-1.5 max-h-48 overflow-y-auto">
                {trustHistory.slice(0, 15).map((h: any, i: number) => {
                  const delta = (h.new_score || 0) - (h.old_score || 0);
                  return (
                    <div key={i} className="flex items-center gap-2 text-xs">
                      <span className="font-mono w-20 truncate">{h.agent_id?.replace('_agent', '')}</span>
                      <span className="text-text-muted w-24 truncate">{h.dimension}</span>
                      <span className={`font-mono ${delta > 0 ? 'text-accent-emerald' : 'text-accent-crimson'}`}>
                        {delta > 0 ? '+' : ''}{delta.toFixed(4)}
                      </span>
                      <span className="text-text-muted ml-auto">{h.change_reason}</span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Calibration History */}
          <div className="bg-bg-secondary border border-border-default rounded-lg p-4">
            <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wide mb-3">Calibration Runs</h2>
            {calibrations.length === 0 ? (
              <div className="text-xs text-text-muted">No calibrations yet</div>
            ) : (
              <div className="space-y-2 max-h-48 overflow-y-auto">
                {calibrations.map((c: any, i: number) => (
                  <div key={i} className="text-xs border-b border-border-default/30 pb-1.5">
                    <div className="flex justify-between">
                      <span className="font-mono font-semibold">{c.cadence}</span>
                      <span className="text-text-muted">{c.trades_analyzed} trades</span>
                    </div>
                    <div className="text-text-muted mt-0.5 truncate">{c.notes?.split?.('\n')?.[0] || ''}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Thresholds */}
        {thresholds?.current && (
          <div className="bg-bg-secondary border border-border-default rounded-lg p-4">
            <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wide mb-3">Consensus Thresholds</h2>
            <div className="grid grid-cols-3 gap-4">
              {Object.entries(thresholds.current as Record<string, any>).map(([profile, t]: [string, any]) => {
                const base = thresholds.baseline?.[profile] || {};
                return (
                  <div key={profile}>
                    <div className="text-xs font-semibold mb-2">{profile}</div>
                    {['strong_signal', 'signal', 'weak_signal', 'min_confidence'].map(k => {
                      const cur = t[k];
                      const orig = base[k];
                      const changed = orig !== undefined && Math.abs(cur - orig) > 0.001;
                      return (
                        <div key={k} className="flex justify-between text-xs py-0.5">
                          <span className="text-text-muted">{k.replace('_', ' ')}</span>
                          <span className={`font-mono ${changed ? 'text-accent-amber' : ''}`}>
                            {cur?.toFixed(3)}{changed && <span className="text-text-muted ml-1">(was {orig?.toFixed(3)})</span>}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Portfolio Intelligence */}
        {(portfolioExp || portfolioFrag) && (
          <div className="bg-bg-secondary border border-border-default rounded-lg p-4">
            <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wide mb-3">Portfolio Intelligence</h2>
            <div className="grid grid-cols-2 gap-4">
              {portfolioExp && (
                <div>
                  <div className="text-xs text-text-muted mb-2">Exposure</div>
                  <div className="grid grid-cols-2 gap-2">
                    {[
                      { label: 'Gross', val: portfolioExp.gross, limit: 0.80, color: portfolioExp.gross > 0.6 ? 'text-accent-amber' : 'text-accent-emerald' },
                      { label: 'Net', val: Math.abs(portfolioExp.net), limit: 0.50, color: Math.abs(portfolioExp.net) > 0.3 ? 'text-accent-amber' : 'text-accent-emerald' },
                      { label: 'Long', val: portfolioExp.long_pct, color: 'text-text-primary' },
                      { label: 'Short', val: portfolioExp.short_pct, color: 'text-text-primary' },
                    ].map((m, i) => (
                      <div key={i} className="text-center">
                        <div className="text-[10px] text-text-muted">{m.label}</div>
                        <div className={`text-sm font-mono font-semibold ${m.color}`}>{(m.val * 100).toFixed(1)}%</div>
                      </div>
                    ))}
                  </div>
                  {Object.keys(portfolioExp.by_class || {}).length > 0 && (
                    <div className="mt-2">
                      <div className="text-[10px] text-text-muted mb-1">By Class</div>
                      {Object.entries(portfolioExp.by_class as Record<string, number>).map(([cls, val]) => (
                        <div key={cls} className="flex justify-between text-xs py-0.5">
                          <span className="text-text-muted">{cls}</span>
                          <span className="font-mono">{(val * 100).toFixed(1)}%</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
              {portfolioFrag && (
                <div>
                  <div className="text-xs text-text-muted mb-2">Fragility</div>
                  <div className="grid grid-cols-2 gap-2">
                    {[
                      { label: 'Overall', val: portfolioFrag.portfolio_fragility },
                      { label: 'Concentration', val: portfolioFrag.concentration_risk },
                      { label: 'Directional', val: portfolioFrag.directional_risk },
                      { label: 'DD Proximity', val: portfolioFrag.drawdown_proximity },
                    ].map((m, i) => {
                      const color = m.val > 0.6 ? 'text-accent-crimson' : m.val > 0.4 ? 'text-accent-amber' : 'text-accent-emerald';
                      return (
                        <div key={i} className="text-center">
                          <div className="text-[10px] text-text-muted">{m.label}</div>
                          <div className={`text-sm font-mono font-semibold ${color}`}>{(m.val * 100).toFixed(0)}%</div>
                        </div>
                      );
                    })}
                  </div>
                  <div className="mt-2 text-center">
                    <div className="text-[10px] text-text-muted">Avg Position Quality</div>
                    <div className={`text-sm font-mono ${portfolioFrag.avg_position_quality > 0.6 ? 'text-accent-emerald' : 'text-accent-amber'}`}>
                      {(portfolioFrag.avg_position_quality * 100).toFixed(0)}%
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Scenario Risk Simulation */}
        {scenarioSim.length > 0 && (
          <div className="bg-bg-secondary border border-border-default rounded-lg p-4">
            <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wide mb-3">Scenario Risk Simulation</h2>
            <div className="grid grid-cols-5 gap-2">
              {scenarioSim.map((s: any, i: number) => {
                const pnl = s.portfolio_pnl || 0;
                const pct = s.portfolio_pnl_pct || 0;
                const color = pnl >= 0 ? 'text-accent-emerald' : pct < -0.05 ? 'text-accent-crimson' : 'text-accent-amber';
                const bg = pnl >= 0 ? 'bg-accent-emerald/5 border-accent-emerald/20' : pct < -0.05 ? 'bg-accent-crimson/5 border-accent-crimson/20' : 'bg-accent-amber/5 border-accent-amber/20';
                return (
                  <div key={i} className={`rounded border p-2 text-center ${bg}`}>
                    <div className="text-[10px] text-text-muted">{s.scenario?.replace(/_/g, ' ')}</div>
                    <div className={`text-sm font-mono font-semibold ${color}`}>{pnl >= 0 ? '+' : ''}{pnl.toFixed(0)}</div>
                    <div className={`text-[10px] font-mono ${color}`}>{(pct * 100).toFixed(1)}%</div>
                    <div className="text-[9px] text-text-muted mt-0.5">{s.impacts?.length || 0} positions</div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Position Rankings + Reallocation Log */}
        <div className="grid grid-cols-2 gap-5">
          {rankings.length > 0 && (
            <div className="bg-bg-secondary border border-border-default rounded-lg p-4">
              <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wide mb-3">Position Quality Rankings</h2>
              <div className="space-y-1.5">
                {rankings.map((r: any, i: number) => {
                  const qColor = r.quality_score >= 0.6 ? 'text-accent-emerald' : r.quality_score >= 0.35 ? 'text-accent-amber' : 'text-accent-crimson';
                  const bgColor = r.quality_score < 0.35 ? 'bg-accent-crimson/5' : '';
                  return (
                    <div key={i} className={`flex items-center gap-2 text-xs py-1 px-1.5 rounded ${bgColor}`}>
                      <span className="w-4 text-text-muted font-mono">#{i + 1}</span>
                      <span className={`w-1.5 h-1.5 rounded-full ${r.direction === 'LONG' ? 'bg-accent-emerald' : 'bg-accent-crimson'}`} />
                      <span className="w-16 font-mono font-semibold">{r.asset}</span>
                      <span className={`w-12 text-right font-mono font-semibold ${qColor}`}>{(r.quality_score * 100).toFixed(0)}</span>
                      <div className="flex-1 flex gap-1">
                        {[
                          { label: 'Sig', val: r.signal_quality },
                          { label: 'PnL', val: r.pnl_trajectory },
                          { label: 'R/R', val: r.risk_reward },
                          { label: 'Age', val: r.time_decay },
                        ].map((c, j) => (
                          <span key={j} className="text-[9px] text-text-muted">{c.label}:{(c.val * 100).toFixed(0)}</span>
                        ))}
                      </div>
                      <span className={`text-[10px] font-mono ${r.unrealized_pnl >= 0 ? 'text-accent-emerald' : 'text-accent-crimson'}`}>
                        {r.unrealized_pnl >= 0 ? '+' : ''}{r.unrealized_pnl.toFixed(0)}
                      </span>
                    </div>
                  );
                })}
              </div>
              {rankings.length > 0 && rankings[rankings.length - 1].quality_score < 0.35 && (
                <div className="mt-2 text-[10px] text-accent-crimson">⚠ Bottom position eligible for reallocation</div>
              )}
            </div>
          )}

          {reallocLog.length > 0 && (
            <div className="bg-bg-secondary border border-border-default rounded-lg p-4">
              <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wide mb-3">Reallocation Log</h2>
              <div className="space-y-1.5">
                {reallocLog.map((r: any, i: number) => (
                  <div key={i} className="text-xs border-b border-border-default pb-1.5">
                    <div className="flex justify-between">
                      <span className="font-mono font-semibold">{r.asset} {r.direction}</span>
                      <span className={`font-mono ${r.pnl >= 0 ? 'text-accent-emerald' : 'text-accent-crimson'}`}>
                        {r.pnl >= 0 ? '+' : ''}{r.pnl?.toFixed(2)}
                      </span>
                    </div>
                    <div className="text-[10px] text-text-muted mt-0.5 truncate">{r.reason}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Adaptive Portfolio Rules */}
        {adaptiveRules.length > 0 && (
          <div className="bg-bg-secondary border border-border-default rounded-lg p-4">
            <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wide mb-3">Learned Portfolio Rules</h2>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {adaptiveRules.map((r: any, i: number) => {
                const isReductive = r.adjustment_type === 'size_mult' && r.adjustment_value < 1.0;
                const isBoost = r.adjustment_type === 'size_mult' && r.adjustment_value > 1.0;
                const border = isReductive ? 'border-accent-amber/30 bg-accent-amber/5' :
                               isBoost ? 'border-accent-emerald/30 bg-accent-emerald/5' :
                               r.adjustment_type === 'approval' ? 'border-accent-crimson/30 bg-accent-crimson/5' :
                               'border-border-default';
                return (
                  <div key={i} className={`rounded border p-2 ${border}`}>
                    <div className="text-[10px] text-text-muted">{r.pattern_key.replace(/_/g, ' ')}</div>
                    <div className="flex items-baseline gap-1 mt-0.5">
                      <span className={`text-sm font-mono font-semibold ${
                        isReductive ? 'text-accent-amber' : isBoost ? 'text-accent-emerald' : 'text-accent-crimson'
                      }`}>
                        {r.adjustment_type === 'approval' ? 'APPROVAL' : `×${r.adjustment_value.toFixed(2)}`}
                      </span>
                      <span className="text-[9px] text-text-muted">WR:{(r.win_rate * 100).toFixed(0)}%</span>
                    </div>
                    <div className="text-[9px] text-text-muted mt-0.5">{r.sample_count} trades • conf {(r.confidence * 100).toFixed(0)}%</div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        <div className="grid grid-cols-2 gap-5">
          {/* Readiness Checklist */}
          {readiness && (
            <div className="bg-bg-secondary border border-border-default rounded-lg p-4">
              <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wide mb-3">Trading Readiness</h2>
              <div className="space-y-1">
                {readiness.checks?.map((c: any, i: number) => (
                  <div key={i} className="flex items-center gap-2 text-xs">
                    <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                      c.status === 'PASS' ? 'bg-accent-emerald' : c.status === 'WARN' ? 'bg-accent-amber' : 'bg-accent-crimson'
                    }`} />
                    <span className="w-36 truncate text-text-muted">{c.name}</span>
                    <span className="font-mono flex-1 truncate">{c.value}</span>
                    <span className={`w-10 text-right font-semibold ${
                      c.status === 'PASS' ? 'text-accent-emerald' : c.status === 'WARN' ? 'text-accent-amber' : 'text-accent-crimson'
                    }`}>{c.status}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Stress Testing */}
          <div className="bg-bg-secondary border border-border-default rounded-lg p-4">
            <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wide mb-3">Stress Testing</h2>
            {stressScenarios.length === 0 ? (
              <div className="text-xs text-text-muted">Loading scenarios...</div>
            ) : (
              <div className="space-y-1.5">
                {stressScenarios.map((s: any) => (
                  <div key={s.name} className="flex items-center gap-2">
                    <button
                      onClick={() => handleRunStress(s.name)}
                      disabled={stressRunning !== null}
                      className={`text-xs font-mono px-2 py-0.5 rounded border ${
                        stressRunning === s.name
                          ? 'border-accent-violet text-accent-violet animate-pulse'
                          : 'border-border-default text-text-secondary hover:border-accent-violet hover:text-accent-violet'
                      }`}>
                      {stressRunning === s.name ? 'Running...' : 'Run'}
                    </button>
                    <span className="text-xs truncate" title={s.description}>{s.name.replace(/_/g, ' ')}</span>
                  </div>
                ))}
              </div>
            )}
            {stressResults.length > 0 && (
              <div className="mt-3 pt-3 border-t border-border-default">
                <div className="text-xs text-text-muted mb-1">Recent Results</div>
                {stressResults.slice(0, 3).map((r: any, i: number) => (
                  <div key={i} className="text-xs flex justify-between py-0.5">
                    <span className="font-mono">{r.scenario_name?.replace(/_/g, ' ')}</span>
                    <span>
                      <span className="text-accent-emerald">{r.would_open || 0} open</span>
                      {' / '}
                      <span className="text-accent-crimson">{r.would_block || 0} block</span>
                      {r.changed_decisions > 0 && (
                        <span className="text-accent-amber ml-1">({r.changed_decisions} changed)</span>
                      )}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </AppShell>
  );
}
