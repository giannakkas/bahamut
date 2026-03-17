'use client';

import { useEffect, useState } from 'react';
import AppShell from '@/components/layout/AppShell';
import { api } from '@/lib/api';
import { AGENT_META } from '@/lib/types';

function TradeCard({ cycle, onApprove, onReject, onSnooze }: {
  cycle: any; onApprove: () => void; onReject: (reason: string) => void; onSnooze: () => void;
}) {
  const d = cycle.decision || {};
  const agents = cycle.agent_outputs || [];
  const challenges = cycle.challenges || [];
  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectReason, setRejectReason] = useState('');
  const [expanded, setExpanded] = useState(true);

  const scoreColor = d.final_score > 0.7 ? 'text-accent-emerald' : d.final_score > 0.5 ? 'text-accent-amber' : 'text-accent-crimson';
  const dirColor = d.direction === 'LONG' ? 'text-accent-emerald' : d.direction === 'SHORT' ? 'text-accent-crimson' : 'text-text-muted';
  const dirArrow = d.direction === 'LONG' ? '▲' : d.direction === 'SHORT' ? '▼' : '─';

  return (
    <div className="bg-bg-secondary border border-border-default rounded-lg overflow-hidden">
      {/* Header */}
      <div className={`p-4 flex items-center justify-between cursor-pointer ${d.direction === 'LONG' ? 'border-l-4 border-accent-emerald' : d.direction === 'SHORT' ? 'border-l-4 border-accent-crimson' : 'border-l-4 border-border-default'}`}
        onClick={() => setExpanded(!expanded)}>
        <div className="flex items-center gap-4">
          <div className={`text-3xl font-bold ${dirColor}`}>{dirArrow}</div>
          <div>
            <div className="text-lg font-bold">{d.asset} <span className={`${dirColor}`}>{d.direction}</span></div>
            <div className="text-xs text-text-muted">{d.decision} · {d.trading_profile} · {d.execution_mode}</div>
          </div>
        </div>
        <div className="flex items-center gap-6">
          {/* Score ring */}
          <div className="relative w-16 h-16">
            <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90">
              <circle cx="50" cy="50" r="40" stroke="#2A2A4A" strokeWidth="6" fill="none" />
              <circle cx="50" cy="50" r="40" strokeWidth="6" fill="none"
                stroke={d.final_score > 0.7 ? '#10B981' : d.final_score > 0.5 ? '#F59E0B' : '#E94560'}
                strokeDasharray={`${d.final_score * 251} 251`} strokeLinecap="round" />
            </svg>
            <div className="absolute inset-0 flex items-center justify-center">
              <span className={`font-mono text-lg font-bold ${scoreColor}`}>{(d.final_score * 100).toFixed(0)}</span>
            </div>
          </div>
          <div className="text-right">
            <div className="text-sm text-text-muted">Agreement</div>
            <div className="font-mono text-lg font-semibold">{(d.agreement_pct * 100).toFixed(0)}%</div>
          </div>
          <span className="text-text-muted">{expanded ? '▾' : '▸'}</span>
        </div>
      </div>

      {expanded && (
        <div className="border-t border-border-default">
          {/* Agent mini grid */}
          <div className="p-4">
            <div className="text-xs text-text-muted mb-2 font-semibold uppercase tracking-wider">Agent Council</div>
            <div className="flex gap-2 flex-wrap">
              {agents.map((a: any) => {
                const meta = AGENT_META[a.agent_id] || { name: a.agent_id, icon: '?', color: '#888' };
                const arrow = a.directional_bias === 'LONG' ? '▲' : a.directional_bias === 'SHORT' ? '▼' : '─';
                const ac = a.directional_bias === 'LONG' ? 'text-accent-emerald' : a.directional_bias === 'SHORT' ? 'text-accent-crimson' : 'text-text-muted';
                return (
                  <div key={a.agent_id} className="flex items-center gap-1.5 bg-bg-tertiary rounded-md px-2.5 py-1.5 border border-border-default">
                    <div className="w-5 h-5 rounded-full flex items-center justify-center text-[8px] font-bold text-white" style={{ backgroundColor: meta.color }}>{meta.icon}</div>
                    <span className="text-xs text-text-secondary">{meta.name}</span>
                    <span className={`text-xs font-semibold ${ac}`}>{arrow}{(a.confidence * 100).toFixed(0)}%</span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Trade Plan */}
          {d.trade_plan && (
            <div className="px-4 pb-3">
              <div className="text-xs text-text-muted mb-2 font-semibold uppercase tracking-wider">Trade Plan</div>
              <div className="grid grid-cols-4 gap-3 text-sm">
                <div><span className="text-text-muted text-xs">Entry</span><div className="font-mono">{d.trade_plan.entry_price || 'Market'}</div></div>
                <div><span className="text-text-muted text-xs">Stop Loss</span><div className="font-mono text-accent-crimson">{d.trade_plan.stop_loss}</div></div>
                <div><span className="text-text-muted text-xs">Take Profit</span><div className="font-mono text-accent-emerald">{d.trade_plan.take_profit}</div></div>
                <div><span className="text-text-muted text-xs">R:R</span><div className="font-mono">{d.trade_plan.risk_reward_ratio}:1</div></div>
              </div>
            </div>
          )}

          {/* Challenges */}
          {challenges.length > 0 && (
            <div className="px-4 pb-3">
              <div className="text-xs text-text-muted mb-2 font-semibold uppercase tracking-wider">Challenges ({challenges.length})</div>
              {challenges.map((ch: any, i: number) => (
                <div key={i} className="flex items-center gap-2 text-xs py-1">
                  <span className="text-accent-amber font-mono">[{i + 1}]</span>
                  <span className="text-text-secondary">{ch.challenger} → {ch.target_agent}</span>
                  <span className="text-text-muted">({ch.challenge_type})</span>
                  <span className={`ml-auto font-semibold ${ch.response === 'VETO' ? 'text-accent-crimson' : ch.response === 'PARTIAL' ? 'text-accent-amber' : 'text-text-muted'}`}>{ch.response}</span>
                </div>
              ))}
            </div>
          )}

          {/* Risk flags */}
          {d.risk_flags?.length > 0 && (
            <div className="px-4 pb-3">
              <div className="text-xs text-accent-amber">Risk flags: {d.risk_flags.join(', ')}</div>
            </div>
          )}

          {/* Price + timing */}
          <div className="px-4 pb-3 flex items-center gap-4 text-xs text-text-muted">
            {cycle.market_price && <span>Price: <span className="font-mono text-text-primary">{cycle.market_price}</span></span>}
            <span>Elapsed: <span className="font-mono">{cycle.elapsed_ms}ms</span></span>
            <span className="flex items-center gap-1">
              <span className="relative flex h-1.5 w-1.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent-emerald opacity-75" style={{ animationDuration: '3s' }}></span>
                <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-accent-emerald"></span>
              </span>
              Live Data
            </span>
          </div>

          {/* Actions */}
          <div className="p-4 border-t border-border-default bg-bg-tertiary/50 flex items-center gap-3">
            <button onClick={onApprove}
              className="bg-accent-emerald hover:bg-accent-emerald/90 text-white font-semibold px-6 py-2 rounded-md text-sm transition-colors">
              Approve Trade
            </button>
            <button onClick={() => setRejectOpen(!rejectOpen)}
              className="bg-accent-crimson hover:bg-accent-crimson/90 text-white font-semibold px-6 py-2 rounded-md text-sm transition-colors">
              Reject
            </button>
            <button onClick={onSnooze}
              className="bg-bg-surface hover:bg-bg-tertiary text-text-secondary font-semibold px-6 py-2 rounded-md text-sm border border-border-default transition-colors">
              Snooze 30m
            </button>
            <a href="/agent-council" className="ml-auto text-xs text-accent-violet hover:underline">View in Agent Council →</a>
          </div>

          {/* Reject reason */}
          {rejectOpen && (
            <div className="p-4 border-t border-border-default bg-bg-tertiary/30">
              <textarea value={rejectReason} onChange={e => setRejectReason(e.target.value)}
                className="w-full bg-bg-surface border border-border-default rounded-md px-3 py-2 text-sm text-text-primary focus:border-border-focus focus:outline-none mb-2"
                placeholder="Reason for rejection (optional - helps the learning engine)" rows={2} />
              <button onClick={() => { onReject(rejectReason); setRejectOpen(false); setRejectReason(''); }}
                className="bg-accent-crimson hover:bg-accent-crimson/90 text-white text-sm px-4 py-1.5 rounded-md">
                Confirm Rejection
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function ExecutionPage() {
  const [cycles, setCycles] = useState<any>({});
  const [actions, setActions] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const c = await api.getAllLatestCycles();
        setCycles(c);
      } catch (e) { console.error(e); }
      setLoading(false);
    };
    load();
    const interval = setInterval(load, 30000);
    return () => clearInterval(interval);
  }, []);

  const handleApprove = (asset: string) => {
    setActions(prev => ({ ...prev, [asset]: 'APPROVED' }));
    // In production: POST to /execution/approve with trade details
  };

  const handleReject = (asset: string, reason: string) => {
    setActions(prev => ({ ...prev, [asset]: 'REJECTED' }));
    // In production: POST to /execution/reject with reason
  };

  const handleSnooze = (asset: string) => {
    setActions(prev => ({ ...prev, [asset]: 'SNOOZED' }));
    setTimeout(() => {
      setActions(prev => { const n = { ...prev }; delete n[asset]; return n; });
    }, 30 * 60 * 1000);
  };

  // Split into actionable signals and others
  const allCycles = Object.entries(cycles);
  const pendingApproval = allCycles.filter(([asset, c]: [string, any]) =>
    c?.decision?.execution_mode === 'APPROVAL' && !actions[asset]
  );
  const autoEligible = allCycles.filter(([asset, c]: [string, any]) =>
    c?.decision?.execution_mode === 'AUTO' && !actions[asset]
  );
  const watchOnly = allCycles.filter(([asset, c]: [string, any]) =>
    c?.decision?.execution_mode === 'WATCH' || c?.decision?.decision === 'NO_TRADE'
  );
  const acted = allCycles.filter(([asset]) => actions[asset]);

  return (
    <AppShell>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold">Execution Engine</h1>
            <p className="text-sm text-text-secondary mt-1">
              {pendingApproval.length} pending approval · {autoEligible.length} auto-eligible · {watchOnly.length} watch
            </p>
          </div>
          <div className="flex items-center gap-3">
            <a href="/risk-control" className="text-sm text-accent-crimson hover:underline">Risk Control →</a>
          </div>
        </div>

        {/* Pending Approval */}
        {pendingApproval.length > 0 && (
          <div>
            <h2 className="text-sm font-semibold text-accent-amber mb-3 flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-accent-amber animate-pulse" />
              Pending Approval ({pendingApproval.length})
            </h2>
            <div className="space-y-4">
              {pendingApproval.map(([asset, cycle]: [string, any]) => (
                <TradeCard key={asset} cycle={cycle}
                  onApprove={() => handleApprove(asset)}
                  onReject={(reason) => handleReject(asset, reason)}
                  onSnooze={() => handleSnooze(asset)} />
              ))}
            </div>
          </div>
        )}

        {/* Auto-Eligible */}
        {autoEligible.length > 0 && (
          <div>
            <h2 className="text-sm font-semibold text-accent-emerald mb-3 flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-accent-emerald" />
              Auto-Eligible ({autoEligible.length})
            </h2>
            <div className="space-y-4">
              {autoEligible.map(([asset, cycle]: [string, any]) => (
                <TradeCard key={asset} cycle={cycle}
                  onApprove={() => handleApprove(asset)}
                  onReject={(reason) => handleReject(asset, reason)}
                  onSnooze={() => handleSnooze(asset)} />
              ))}
            </div>
          </div>
        )}

        {/* Watch Only */}
        {watchOnly.length > 0 && (
          <div>
            <h2 className="text-sm font-semibold text-text-muted mb-3">Watch Only ({watchOnly.length})</h2>
            <div className="space-y-3">
              {watchOnly.map(([asset, cycle]: [string, any]) => {
                const d = cycle?.decision || {};
                const dirColor = d.direction === 'LONG' ? 'text-accent-emerald' : d.direction === 'SHORT' ? 'text-accent-crimson' : 'text-text-muted';
                return (
                  <div key={asset} className="bg-bg-secondary border border-border-default rounded-lg p-3 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <span className={dirColor}>{d.direction === 'LONG' ? '▲' : d.direction === 'SHORT' ? '▼' : '─'}</span>
                      <span className="font-semibold text-sm">{asset}</span>
                      <span className="text-xs text-text-muted">{d.direction} · {d.decision}</span>
                    </div>
                    <div className="flex items-center gap-4">
                      <span className="font-mono text-sm text-accent-violet">{d.final_score?.toFixed(2)}</span>
                      <span className="text-xs text-text-muted">WATCH</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Acted upon */}
        {acted.length > 0 && (
          <div>
            <h2 className="text-sm font-semibold text-text-muted mb-3">Session Actions</h2>
            <div className="space-y-2">
              {acted.map(([asset]) => (
                <div key={asset} className="bg-bg-secondary border border-border-default rounded-lg p-3 flex items-center justify-between">
                  <span className="font-semibold text-sm">{asset}</span>
                  <span className={`text-sm font-semibold ${actions[asset] === 'APPROVED' ? 'text-accent-emerald' : actions[asset] === 'REJECTED' ? 'text-accent-crimson' : 'text-accent-amber'}`}>
                    {actions[asset]}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Empty state */}
        {allCycles.length === 0 && !loading && (
          <div className="bg-bg-secondary border border-border-default rounded-lg p-8 text-center">
            <div className="text-text-secondary">No signal cycles have run yet.</div>
            <div className="text-text-muted text-sm mt-1">Cycles run automatically every 15 minutes, or trigger one manually.</div>
            <a href="/agent-council" className="text-sm text-accent-violet hover:underline mt-3 inline-block">Go to Agent Council →</a>
          </div>
        )}
      </div>
    </AppShell>
  );
}
