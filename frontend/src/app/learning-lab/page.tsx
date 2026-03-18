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
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const [f, m, t, l, c, th, h] = await Promise.allSettled([
        api.getStrategyFitness(),
        api.getMetaEvaluation(),
        api.getTrustSummary(),
        api.getAgentLeaderboard(),
        api.getCalibrationHistory(5),
        api.getThresholds(),
        api.getTrustHistory(undefined, 20),
      ]);
      if (f.status === 'fulfilled') setFitness(f.value);
      if (m.status === 'fulfilled') setMeta(m.value);
      if (t.status === 'fulfilled') setTrust(t.value);
      if (l.status === 'fulfilled') setLeaderboard(l.value);
      if (c.status === 'fulfilled') setCalibrations(c.value);
      if (th.status === 'fulfilled') setThresholds(th.value);
      if (h.status === 'fulfilled') setTrustHistory(h.value);
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
          <div>
            <h1 className="text-2xl font-bold">Learning Lab</h1>
            <p className="text-sm text-text-secondary mt-1">Self-learning intelligence • {fitness?.total_closed_trades || 0} trades analyzed</p>
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
      </div>
    </AppShell>
  );
}
