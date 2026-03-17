'use client';

import { useEffect, useState } from 'react';
import AppShell from '@/components/layout/AppShell';
import { api } from '@/lib/api';
import { AGENT_META } from '@/lib/types';

function MetricCard({ label, value, sub, variant = 'neutral' }: {
  label: string; value: string; sub?: string; variant?: 'positive' | 'negative' | 'neutral';
}) {
  const colors = { positive: 'text-accent-emerald', negative: 'text-accent-crimson', neutral: 'text-text-primary' };
  return (
    <div className="bg-bg-secondary border border-border-default rounded-lg p-4">
      <div className="text-xs text-text-muted uppercase tracking-wider mb-1">{label}</div>
      <div className={`text-2xl font-mono font-semibold ${colors[variant]}`}>{value}</div>
      {sub && <div className="text-xs text-text-secondary mt-0.5">{sub}</div>}
    </div>
  );
}

function DrawdownBar({ label, value, max }: { label: string; value: number; max: number }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  const color = pct > 80 ? 'bg-accent-crimson' : pct > 50 ? 'bg-accent-amber' : 'bg-accent-emerald';
  return (
    <div className="flex items-center gap-3 text-sm">
      <span className="w-16 text-text-secondary">{label}</span>
      <div className="flex-1 h-2 bg-bg-surface rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all duration-500 ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="font-mono text-xs text-text-secondary w-24 text-right">
        {(value * 100).toFixed(1)}% / {(max * 100).toFixed(1)}%
      </span>
    </div>
  );
}

function SignalCard({ asset, direction, score, decision, mode }: any) {
  return (
    <a href="/agent-council" className="flex items-center justify-between p-3 bg-bg-tertiary rounded-md border border-border-default mb-2 hover:border-border-focus transition-colors cursor-pointer">
      <div className="flex items-center gap-3">
        <span className={direction === 'LONG' ? 'text-accent-emerald text-lg' : direction === 'SHORT' ? 'text-accent-crimson text-lg' : 'text-text-muted text-lg'}>
          {direction === 'LONG' ? '▲' : direction === 'SHORT' ? '▼' : '─'}
        </span>
        <div>
          <div className="font-semibold text-sm">{asset} <span className="text-text-muted font-normal">{direction}</span></div>
          <div className="text-xs text-text-muted">{decision}</div>
        </div>
      </div>
      <div className="text-right">
        <div className="font-mono text-lg font-semibold text-accent-violet">{typeof score === 'number' ? score.toFixed(2) : score}</div>
        <div className={`text-xs ${mode === 'APPROVAL' ? 'text-accent-amber' : mode === 'AUTO' ? 'text-accent-emerald' : 'text-text-muted'}`}>{mode}</div>
      </div>
    </a>
  );
}

export default function DashboardPage() {
  const [risk, setRisk] = useState<any>(null);
  const [brief, setBrief] = useState<any>(null);
  const [cycles, setCycles] = useState<any>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const [r, b, c] = await Promise.allSettled([
          api.getRiskDashboard(),
          api.getDailyBrief(),
          api.getAllLatestCycles(),
        ]);
        if (r.status === 'fulfilled') setRisk(r.value);
        if (b.status === 'fulfilled') setBrief(b.value);
        if (c.status === 'fulfilled') setCycles(c.value);
      } catch (e) { console.error(e); }
      setLoading(false);
    };
    load();
    // Refresh every 60 seconds
    const interval = setInterval(load, 60000);
    return () => clearInterval(interval);
  }, []);

  const dd = risk?.drawdown || { daily: 0, weekly: 0, total: 0 };
  const limits = risk?.limits || { daily: 0.03, weekly: 0.06, total: 0.15 };

  // Build signals from real cycle results
  const signals = Object.entries(cycles).map(([asset, cycle]: [string, any]) => {
    const d = cycle?.decision || {};
    return {
      asset,
      direction: d.direction || 'NO_TRADE',
      score: d.final_score || 0,
      decision: d.decision || 'NO_TRADE',
      mode: d.execution_mode || 'WATCH',
    };
  }).filter(s => s.decision !== 'NO_TRADE');

  // Build agent consensus from most recent cycle
  const latestCycle = Object.values(cycles)[0] as any;
  const agentOutputs = latestCycle?.agent_outputs || [];
  const consensusScore = latestCycle?.decision?.final_score || 0;
  const agreementPct = latestCycle?.decision?.agreement_pct || 0;
  const latestAsset = latestCycle?.decision?.asset || '';

  // Count active signals
  const signalCount = Object.keys(cycles).length;
  const strongSignals = signals.filter(s => s.decision === 'STRONG_SIGNAL' || s.decision === 'SIGNAL').length;

  return (
    <AppShell>
      <div className="space-y-6">
        {/* Regime Banner */}
        <div className="bg-bg-secondary border border-border-default rounded-lg p-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <span className="px-3 py-1 rounded-full text-sm font-semibold bg-accent-emerald/20 text-accent-emerald border border-accent-emerald/30">RISK_ON</span>
            <span className="text-sm text-text-secondary">Confidence: <span className="font-mono text-text-primary">78%</span></span>
            {signalCount > 0 && (
              <span className="flex items-center gap-1.5 text-sm text-accent-emerald">
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent-emerald opacity-75" style={{ animationDuration: '3s' }}></span>
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-accent-emerald"></span>
                </span>
                Live Data
              </span>
            )}
          </div>
          {brief && <div className="text-xs text-text-muted max-w-lg truncate">{brief.summary?.slice(0, 120)}...</div>}
        </div>

        {/* Metrics */}
        <div className="grid grid-cols-4 gap-4">
          <MetricCard label="Active Signals" value={String(signalCount)} sub={strongSignals > 0 ? strongSignals + ' actionable' : 'Monitoring'} variant={strongSignals > 0 ? 'positive' : 'neutral'} />
          <MetricCard label="Agents Online" value="6 / 6" sub="All operational" variant="positive" />
          <MetricCard label="Consensus Cycles" value={String(signalCount)} sub="Last 30 min" />
          <MetricCard label="Risk Status" value={dd.daily > limits.daily * 0.8 ? 'CAUTION' : 'CLEAR'} sub={'Daily DD: ' + (dd.daily * 100).toFixed(1) + '%'} variant={dd.daily > limits.daily * 0.8 ? 'negative' : 'positive'} />
        </div>

        <div className="grid grid-cols-2 gap-4">
          {/* Active Signals - LIVE */}
          <div className="bg-bg-secondary border border-border-default rounded-lg p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold">Active Signals</h3>
              {signalCount > 0 && <span className="text-[10px] text-accent-emerald">LIVE</span>}
            </div>
            {signals.length > 0 ? (
              signals.map((s, i) => <SignalCard key={i} {...s} />)
            ) : loading ? (
              <div className="text-sm text-text-muted p-4 text-center">Loading signals...</div>
            ) : (
              <div className="text-sm text-text-muted p-4 text-center">
                No active signals. Cycles run every 15 minutes.
                <a href="/agent-council" className="block text-accent-violet mt-2 hover:underline">Trigger manually in Agent Council</a>
              </div>
            )}
          </div>

          {/* Risk Status - LIVE */}
          <div className="bg-bg-secondary border border-border-default rounded-lg p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold">Risk Status</h3>
              {risk && <span className="text-[10px] text-accent-emerald">LIVE</span>}
            </div>
            <div className="space-y-3">
              <DrawdownBar label="Daily" value={dd.daily} max={limits.daily} />
              <DrawdownBar label="Weekly" value={dd.weekly} max={limits.weekly} />
              <DrawdownBar label="Total" value={dd.total} max={limits.total} />
            </div>
            <div className="mt-4 grid grid-cols-2 gap-2 text-sm">
              {risk?.circuit_breakers?.map((cb: any, i: number) => (
                <div key={i} className="flex items-center gap-2">
                  <span className={`w-2 h-2 rounded-full ${cb.active ? 'bg-accent-amber' : 'bg-accent-emerald'}`} />
                  <span className="text-text-secondary text-xs">{cb.name}: <span className={cb.active ? 'text-accent-amber' : 'text-accent-emerald'}>{cb.active ? cb.reason || 'ON' : 'OK'}</span></span>
                </div>
              ))}
            </div>
          </div>

          {/* Agent Consensus - LIVE from latest cycle */}
          <div className="bg-bg-secondary border border-border-default rounded-lg p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold">Agent Consensus {latestAsset && <span className="text-text-muted font-normal">({latestAsset})</span>}</h3>
              {agentOutputs.length > 0 && <span className="text-[10px] text-accent-emerald">LIVE</span>}
            </div>
            {agentOutputs.length > 0 ? (
              <>
                <div className="grid grid-cols-3 gap-2 mb-3">
                  {agentOutputs.slice(0, 6).map((a: any, i: number) => {
                    const meta = AGENT_META[a.agent_id] || { name: a.agent_id, icon: '?', color: '#888' };
                    const arrow = a.directional_bias === 'LONG' ? '▲' : a.directional_bias === 'SHORT' ? '▼' : '─';
                    const arrowColor = a.directional_bias === 'LONG' ? 'text-accent-emerald' : a.directional_bias === 'SHORT' ? 'text-accent-crimson' : 'text-text-muted';
                    return (
                      <div key={i} className="bg-bg-tertiary border border-border-default rounded-md p-2 text-center">
                        <div className="w-7 h-7 rounded-full mx-auto mb-1 flex items-center justify-center text-[10px] font-bold text-white" style={{ backgroundColor: meta.color }}>{meta.icon}</div>
                        <div className="text-[10px] text-text-secondary">{meta.name}</div>
                        <div className={`text-sm font-semibold ${arrowColor}`}>{arrow} {(a.confidence * 100).toFixed(0)}%</div>
                      </div>
                    );
                  })}
                </div>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-text-secondary">Agreement: <span className="font-mono text-text-primary">{(agreementPct * 100).toFixed(0)}%</span></span>
                  <span className="text-text-secondary">Score: <span className="font-mono text-accent-violet font-semibold">{consensusScore.toFixed(2)}</span></span>
                </div>
                <div className="mt-2 h-2 bg-bg-surface rounded-full overflow-hidden">
                  <div className="h-full bg-accent-violet rounded-full transition-all duration-700" style={{ width: `${consensusScore * 100}%` }} />
                </div>
              </>
            ) : (
              <div className="text-sm text-text-muted p-4 text-center">No cycle results yet</div>
            )}
            <a href="/agent-council" className="block mt-3 text-xs text-accent-violet hover:underline text-center">View full Agent Council →</a>
          </div>

          {/* Daily Brief - LIVE */}
          <div className="bg-bg-secondary border border-border-default rounded-lg p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold">Daily Intelligence Brief</h3>
              {brief && <span className="text-[10px] text-accent-emerald">LIVE</span>}
            </div>
            {brief ? (
              <>
                <p className="text-sm text-text-secondary leading-relaxed">{brief.summary}</p>
                <div className="mt-3 flex items-center gap-4 text-xs text-text-muted">
                  <span>Signals: <span className="font-mono text-text-primary">{brief.signals_generated}</span></span>
                  <span>Trades: <span className="font-mono text-text-primary">{brief.trades_executed}</span></span>
                  <span>Risk Events: <span className="font-mono text-text-primary">{brief.risk_events}</span></span>
                </div>
                <a href="/intel-reports" className="block mt-2 text-xs text-accent-violet hover:underline">Full report →</a>
              </>
            ) : (
              <div className="text-sm text-text-muted p-4 text-center">Loading brief...</div>
            )}
          </div>
        </div>
      </div>
    </AppShell>
  );
}
