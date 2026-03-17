'use client';

import { useEffect, useState } from 'react';
import AppShell from '@/components/layout/AppShell';
import { api } from '@/lib/api';

export default function TradeJournalPage() {
  const [history, setHistory] = useState<any[]>([]);
  const [filterAsset, setFilterAsset] = useState<string>('ALL');
  const [filterDirection, setFilterDirection] = useState<string>('ALL');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const asset = filterAsset === 'ALL' ? undefined : filterAsset;
        const data = await api.getCycleHistory(asset, 100);
        setHistory(data);
      } catch (e) { console.error(e); }
      setLoading(false);
    };
    load();
  }, [filterAsset]);

  const filtered = history.filter(h => {
    if (filterDirection !== 'ALL' && h.direction !== filterDirection) return false;
    return true;
  });

  // Stats
  const total = filtered.length;
  const longs = filtered.filter(h => h.direction === 'LONG').length;
  const shorts = filtered.filter(h => h.direction === 'SHORT').length;
  const noTrade = filtered.filter(h => h.direction === 'NO_TRADE').length;
  const avgScore = total > 0 ? filtered.reduce((s, h) => s + (h.score || 0), 0) / total : 0;
  const signals = filtered.filter(h => h.decision === 'SIGNAL' || h.decision === 'STRONG_SIGNAL').length;

  return (
    <AppShell>
      <div className="space-y-5">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold">Trade Journal</h1>
            <p className="text-sm text-text-secondary mt-1">Historical signal cycle results and analysis</p>
          </div>
          <div className="flex items-center gap-3">
            <select value={filterAsset} onChange={e => { setFilterAsset(e.target.value); setLoading(true); }}
              className="bg-bg-surface border border-border-default rounded-md px-3 py-1.5 text-sm text-text-primary">
              {['ALL', 'EURUSD', 'GBPUSD', 'USDJPY', 'XAUUSD'].map(v => <option key={v} value={v}>{v === 'ALL' ? 'All Assets' : v}</option>)}
            </select>
            <select value={filterDirection} onChange={e => setFilterDirection(e.target.value)}
              className="bg-bg-surface border border-border-default rounded-md px-3 py-1.5 text-sm text-text-primary">
              {['ALL', 'LONG', 'SHORT', 'NO_TRADE'].map(v => <option key={v} value={v}>{v === 'ALL' ? 'All Directions' : v}</option>)}
            </select>
          </div>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-6 gap-3">
          {[
            { label: 'Total Cycles', value: total, color: 'text-text-primary' },
            { label: 'LONG', value: longs, color: 'text-accent-emerald' },
            { label: 'SHORT', value: shorts, color: 'text-accent-crimson' },
            { label: 'NO_TRADE', value: noTrade, color: 'text-text-muted' },
            { label: 'Avg Score', value: avgScore.toFixed(2), color: 'text-accent-violet' },
            { label: 'Signals', value: signals, color: 'text-accent-amber' },
          ].map((s, i) => (
            <div key={i} className="bg-bg-secondary border border-border-default rounded-lg p-3 text-center">
              <div className={`text-xl font-mono font-semibold ${s.color}`}>{s.value}</div>
              <div className="text-[10px] text-text-muted uppercase tracking-wider mt-0.5">{s.label}</div>
            </div>
          ))}
        </div>

        {/* History Table */}
        <div className="bg-bg-secondary border border-border-default rounded-lg overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-border-default text-xs text-text-muted uppercase tracking-wider">
                <th className="text-left py-3 px-4">Time</th>
                <th className="text-left py-3 px-4">Asset</th>
                <th className="text-left py-3 px-4">Direction</th>
                <th className="text-left py-3 px-4">Score</th>
                <th className="text-left py-3 px-4">Decision</th>
                <th className="text-left py-3 px-4">Agreement</th>
                <th className="text-left py-3 px-4">Regime</th>
                <th className="text-left py-3 px-4">Profile</th>
                <th className="text-left py-3 px-4">Mode</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={9} className="py-8 text-center text-text-muted text-sm">Loading history...</td></tr>
              ) : filtered.length === 0 ? (
                <tr><td colSpan={9} className="py-8 text-center text-text-muted text-sm">
                  No cycle history yet. Trigger cycles from Agent Council to build history.
                </td></tr>
              ) : (
                filtered.map((h, i) => {
                  const dirColor = h.direction === 'LONG' ? 'text-accent-emerald' : h.direction === 'SHORT' ? 'text-accent-crimson' : 'text-text-muted';
                  const arrow = h.direction === 'LONG' ? '▲' : h.direction === 'SHORT' ? '▼' : '─';
                  const decColor = h.decision === 'STRONG_SIGNAL' || h.decision === 'SIGNAL' ? 'text-accent-violet' : h.decision === 'WEAK_SIGNAL' ? 'text-accent-amber' : 'text-text-muted';
                  const time = h.created_at ? new Date(h.created_at).toLocaleString('en-GB', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—';

                  return (
                    <tr key={h.id || i} className="border-b border-border-default hover:bg-bg-tertiary/50 transition-colors">
                      <td className="py-2.5 px-4 text-xs text-text-secondary font-mono">{time}</td>
                      <td className="py-2.5 px-4 text-sm font-semibold">{h.asset}</td>
                      <td className={`py-2.5 px-4 text-sm font-bold ${dirColor}`}>{arrow} {h.direction}</td>
                      <td className="py-2.5 px-4 font-mono text-sm text-accent-violet">{h.score?.toFixed(2)}</td>
                      <td className={`py-2.5 px-4 text-xs font-semibold ${decColor}`}>{h.decision}</td>
                      <td className="py-2.5 px-4 font-mono text-sm">{(h.agreement * 100).toFixed(0)}%</td>
                      <td className="py-2.5 px-4 text-xs text-text-secondary">{h.regime}</td>
                      <td className="py-2.5 px-4 text-xs text-text-secondary">{h.profile}</td>
                      <td className="py-2.5 px-4 text-xs text-text-muted">{h.mode}</td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </AppShell>
  );
}
