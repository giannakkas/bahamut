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
  const pct = Math.min(100, (value / max) * 100);
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

function AgentMiniCard({ agentId, bias, confidence }: { agentId: string; bias: string; confidence: number }) {
  const meta = AGENT_META[agentId] || { name: agentId, icon: '?', color: '#888' };
  const arrow = bias === 'LONG' ? '▲' : bias === 'SHORT' ? '▼' : '─';
  const arrowColor = bias === 'LONG' ? 'text-accent-emerald' : bias === 'SHORT' ? 'text-accent-crimson' : 'text-text-muted';
  return (
    <div className="bg-bg-tertiary border border-border-default rounded-md p-2 text-center">
      <div className="w-8 h-8 rounded-full mx-auto mb-1 flex items-center justify-center text-xs font-bold text-white"
        style={{ backgroundColor: meta.color }}>{meta.icon}</div>
      <div className="text-[10px] text-text-secondary">{meta.name}</div>
      <div className={`text-sm font-semibold ${arrowColor}`}>{arrow} {(confidence * 100).toFixed(0)}%</div>
    </div>
  );
}

export default function DashboardPage() {
  const [risk, setRisk] = useState<any>(null);
  const [brief, setBrief] = useState<any>(null);
  const [agents, setAgents] = useState<any>(null);

  useEffect(() => {
    const load = async () => {
      try {
        const [r, b, a] = await Promise.allSettled([
          api.getRiskDashboard(),
          api.getDailyBrief(),
          api.getAgentHealth(),
        ]);
        if (r.status === 'fulfilled') setRisk(r.value);
        if (b.status === 'fulfilled') setBrief(b.value);
        if (a.status === 'fulfilled') setAgents(a.value);
      } catch (e) { console.error(e); }
    };
    load();
  }, []);

  const dd = risk?.drawdown || { daily: 0, weekly: 0, total: 0 };
  const limits = risk?.limits || { daily: 0.03, weekly: 0.06, total: 0.15 };

  return (
    <AppShell>
      <div className="space-y-6">
        {/* Regime Banner */}
        <div className="bg-bg-secondary border border-border-default rounded-lg p-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <span className="px-3 py-1 rounded-full text-sm font-semibold bg-accent-emerald/20 text-accent-emerald border border-accent-emerald/30">RISK_ON</span>
            <span className="text-sm text-text-secondary">Confidence: <span className="font-mono text-text-primary">78%</span></span>
          </div>
          {brief && <div className="text-xs text-text-muted max-w-md truncate">{brief.summary?.slice(0, 100)}...</div>}
        </div>

        {/* Metrics */}
        <div className="grid grid-cols-4 gap-4">
          <MetricCard label="Equity" value="$124,350" sub="+2.1% this week" variant="positive" />
          <MetricCard label="Day PnL" value="+$1,240" sub="+0.99%" variant="positive" />
          <MetricCard label="Win Rate" value="67.3%" sub="Last 30 trades" />
          <MetricCard label="Open Trades" value="4 / 6" sub="BALANCED profile" />
        </div>

        <div className="grid grid-cols-2 gap-4">
          {/* Active Signals */}
          <div className="bg-bg-secondary border border-border-default rounded-lg p-4">
            <h3 className="text-sm font-semibold mb-3">Active Signals</h3>
            {[
              { asset: 'EURUSD', dir: 'LONG', score: 0.74, decision: 'SIGNAL', mode: 'APPROVAL' },
              { asset: 'XAUUSD', dir: 'SHORT', score: 0.68, decision: 'WEAK_SIGNAL', mode: 'WATCH' },
            ].map((s, i) => (
              <div key={i} className="flex items-center justify-between p-3 bg-bg-tertiary rounded-md border border-border-default mb-2 hover:border-border-focus transition-colors cursor-pointer">
                <div className="flex items-center gap-3">
                  <span className={s.dir === 'LONG' ? 'text-accent-emerald text-lg' : 'text-accent-crimson text-lg'}>{s.dir === 'LONG' ? '▲' : '▼'}</span>
                  <div>
                    <div className="font-semibold text-sm">{s.asset} <span className="text-text-muted font-normal">{s.dir}</span></div>
                    <div className="text-xs text-text-muted">{s.decision}</div>
                  </div>
                </div>
                <div className="text-right">
                  <div className="font-mono text-lg font-semibold text-accent-violet">{s.score.toFixed(2)}</div>
                  <div className={`text-xs ${s.mode === 'APPROVAL' ? 'text-accent-amber' : 'text-text-muted'}`}>{s.mode}</div>
                </div>
              </div>
            ))}
          </div>

          {/* Risk Status - LIVE DATA */}
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

          {/* Agent Consensus */}
          <div className="bg-bg-secondary border border-border-default rounded-lg p-4">
            <h3 className="text-sm font-semibold mb-3">Agent Consensus</h3>
            <div className="grid grid-cols-3 gap-2 mb-3">
              {[
                { agentId: 'macro_agent', bias: 'LONG', confidence: 0.82 },
                { agentId: 'technical_agent', bias: 'LONG', confidence: 0.69 },
                { agentId: 'risk_agent', bias: 'NEUTRAL', confidence: 0.80 },
              ].map((a, i) => <AgentMiniCard key={i} {...a} />)}
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-text-secondary">Agreement: <span className="font-mono text-text-primary">78%</span></span>
              <span className="text-text-secondary">Score: <span className="font-mono text-accent-violet font-semibold">0.74</span></span>
            </div>
            <div className="mt-2 h-2 bg-bg-surface rounded-full overflow-hidden">
              <div className="h-full bg-accent-violet rounded-full" style={{ width: '78%' }} />
            </div>
            <a href="/agent-council" className="block mt-3 text-xs text-accent-violet hover:underline text-center">View full Agent Council →</a>
          </div>

          {/* Recent Trades */}
          <div className="bg-bg-secondary border border-border-default rounded-lg p-4">
            <h3 className="text-sm font-semibold mb-3">Recent Trades</h3>
            {[
              { asset: 'GBPUSD', dir: 'LONG', pnl: '+1.2%', time: '3h ago', reason: 'TP hit' },
              { asset: 'SPX', dir: 'SHORT', pnl: '-0.4%', time: '6h ago', reason: 'SL hit' },
              { asset: 'USDJPY', dir: 'LONG', pnl: '+0.3%', time: '1h ago', reason: 'Running' },
            ].map((t, i) => (
              <div key={i} className="flex items-center justify-between py-2 border-b border-border-default last:border-0">
                <div className="flex items-center gap-3">
                  <span className={t.dir === 'LONG' ? 'text-accent-emerald' : 'text-accent-crimson'}>{t.dir === 'LONG' ? '▲' : '▼'}</span>
                  <span className="text-sm font-medium">{t.asset}</span>
                </div>
                <div className="flex items-center gap-4">
                  <span className={`font-mono text-sm ${t.pnl.startsWith('+') ? 'text-accent-emerald' : 'text-accent-crimson'}`}>{t.pnl}</span>
                  <span className="text-xs text-text-muted w-14 text-right">{t.time}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </AppShell>
  );
}
