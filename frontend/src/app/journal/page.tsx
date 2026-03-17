'use client';

import { useEffect, useState } from 'react';
import AppShell from '@/components/layout/AppShell';
import { api } from '@/lib/api';

export default function TradeJournalPage() {
  const [history, setHistory] = useState<any[]>([]);
  const [paperTrades, setPaperTrades] = useState<any[]>([]);
  const [filterAsset, setFilterAsset] = useState<string>('ALL');
  const [filterDirection, setFilterDirection] = useState<string>('ALL');
  const [tab, setTab] = useState<'signals' | 'trades'>('trades');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const [cycleData, paperData] = await Promise.allSettled([
          api.getCycleHistory(filterAsset === 'ALL' ? undefined : filterAsset, 100),
          api.getPaperPositions(undefined, filterAsset === 'ALL' ? undefined : filterAsset, 100),
        ]);
        if (cycleData.status === 'fulfilled') setHistory(cycleData.value || []);
        if (paperData.status === 'fulfilled') setPaperTrades(paperData.value?.positions || []);
      } catch (e) { console.error(e); }
      setLoading(false);
    };
    load();
  }, [filterAsset]);

  const filtered = history.filter(h => {
    if (filterDirection !== 'ALL' && h.direction !== filterDirection) return false;
    return true;
  });

  const closedTrades = paperTrades.filter(t => t.status !== 'OPEN');
  const total = filtered.length;
  const longs = filtered.filter(h => h.direction === 'LONG').length;
  const shorts = filtered.filter(h => h.direction === 'SHORT').length;
  const avgScore = total > 0 ? filtered.reduce((s: number, h: any) => s + (h.score || 0), 0) / total : 0;
  const signals = filtered.filter(h => h.decision === 'SIGNAL' || h.decision === 'STRONG_SIGNAL').length;

  const tradeWins = closedTrades.filter(t => t.realized_pnl > 0).length;
  const tradeLosses = closedTrades.filter(t => t.realized_pnl <= 0).length;
  const totalPnl = closedTrades.reduce((s: number, t: any) => s + (t.realized_pnl || 0), 0);

  return (
    <AppShell>
      <div className="space-y-5">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold">Trade Journal</h1>
            <p className="text-sm text-text-secondary mt-1">Signal history + paper trading results</p>
          </div>
          <div className="flex items-center gap-3">
            <select value={filterAsset} onChange={e => { setFilterAsset(e.target.value); setLoading(true); }}
              className="bg-bg-surface border border-border-default rounded-md px-3 py-1.5 text-sm text-text-primary">
              {['ALL', 'EURUSD', 'GBPUSD', 'USDJPY', 'XAUUSD', 'BTCUSD', 'ETHUSD', 'AAPL', 'TSLA', 'NVDA', 'META'].map(v => <option key={v} value={v}>{v === 'ALL' ? 'All Assets' : v}</option>)}
            </select>
            <select value={filterDirection} onChange={e => setFilterDirection(e.target.value)}
              className="bg-bg-surface border border-border-default rounded-md px-3 py-1.5 text-sm text-text-primary">
              {['ALL', 'LONG', 'SHORT', 'NO_TRADE'].map(v => <option key={v} value={v}>{v === 'ALL' ? 'All Directions' : v}</option>)}
            </select>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 bg-bg-secondary border border-border-default rounded-lg p-1 w-fit">
          <button onClick={() => setTab('trades')} className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${tab === 'trades' ? 'bg-accent-violet/20 text-accent-violet' : 'text-text-secondary hover:text-text-primary'}`}>
            Paper Trades ({closedTrades.length})
          </button>
          <button onClick={() => setTab('signals')} className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${tab === 'signals' ? 'bg-accent-violet/20 text-accent-violet' : 'text-text-secondary hover:text-text-primary'}`}>
            Signal Cycles ({total})
          </button>
        </div>

        {/* Paper Trades Tab */}
        {tab === 'trades' && (
          <>
            <div className="grid grid-cols-3 sm:grid-cols-6 gap-3">
              {[
                { label: 'Total Trades', value: closedTrades.length, color: 'text-text-primary' },
                { label: 'Wins', value: tradeWins, color: 'text-accent-emerald' },
                { label: 'Losses', value: tradeLosses, color: 'text-accent-crimson' },
                { label: 'Win Rate', value: closedTrades.length > 0 ? `${(tradeWins / closedTrades.length * 100).toFixed(0)}%` : '—', color: 'text-accent-violet' },
                { label: 'Total P&L', value: `$${totalPnl.toFixed(0)}`, color: totalPnl >= 0 ? 'text-accent-emerald' : 'text-accent-crimson' },
                { label: 'Open', value: paperTrades.filter(t => t.status === 'OPEN').length, color: 'text-accent-amber' },
              ].map((s, i) => (
                <div key={i} className="bg-bg-secondary border border-border-default rounded-lg p-3 text-center">
                  <div className={`text-xl font-mono font-semibold ${s.color}`}>{s.value}</div>
                  <div className="text-[10px] text-text-muted uppercase tracking-wider mt-0.5">{s.label}</div>
                </div>
              ))}
            </div>

            <div className="bg-bg-secondary border border-border-default rounded-lg overflow-x-auto">
              <table className="w-full min-w-[600px]">
                <thead>
                  <tr className="border-b border-border-default text-xs text-text-muted uppercase tracking-wider">
                    <th className="text-left py-3 px-4">Asset</th>
                    <th className="text-left py-3 px-4">Direction</th>
                    <th className="text-right py-3 px-4">Entry</th>
                    <th className="text-right py-3 px-4">Exit</th>
                    <th className="text-right py-3 px-4">P&L</th>
                    <th className="text-center py-3 px-4">Status</th>
                    <th className="text-right py-3 px-4">Score</th>
                    <th className="text-right py-3 px-4">Closed</th>
                  </tr>
                </thead>
                <tbody>
                  {loading ? (
                    <tr><td colSpan={8} className="py-8 text-center text-text-muted text-sm">Loading...</td></tr>
                  ) : closedTrades.length === 0 ? (
                    <tr><td colSpan={8} className="py-8 text-center text-text-muted text-sm">
                      No closed paper trades yet. Trades open automatically when signal consensus ≥ 0.58.
                    </td></tr>
                  ) : (
                    closedTrades.map((t: any) => {
                      const isWin = t.realized_pnl > 0;
                      return (
                        <tr key={t.id} className="border-b border-border-default hover:bg-bg-tertiary/50">
                          <td className="py-2.5 px-4 text-sm font-semibold">{t.asset}</td>
                          <td className={`py-2.5 px-4 text-sm font-bold ${t.direction === 'LONG' ? 'text-accent-emerald' : 'text-accent-crimson'}`}>
                            {t.direction === 'LONG' ? '▲' : '▼'} {t.direction}
                          </td>
                          <td className="py-2.5 px-4 text-right font-mono text-sm">{t.entry_price}</td>
                          <td className="py-2.5 px-4 text-right font-mono text-sm">{t.exit_price || '—'}</td>
                          <td className={`py-2.5 px-4 text-right font-mono text-sm ${isWin ? 'text-accent-emerald' : 'text-accent-crimson'}`}>
                            {isWin ? '+' : ''}${(t.realized_pnl || 0).toFixed(2)}
                          </td>
                          <td className="py-2.5 px-4 text-center">
                            <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                              t.status === 'CLOSED_TP' ? 'bg-accent-emerald/20 text-accent-emerald' :
                              t.status === 'CLOSED_SL' ? 'bg-accent-crimson/20 text-accent-crimson' :
                              'bg-accent-amber/20 text-accent-amber'
                            }`}>{t.status?.replace('CLOSED_', '')}</span>
                          </td>
                          <td className="py-2.5 px-4 text-right font-mono text-sm text-accent-violet">{t.signal_score?.toFixed(2)}</td>
                          <td className="py-2.5 px-4 text-right text-xs text-text-muted">
                            {t.closed_at ? new Date(t.closed_at).toLocaleDateString('en-GB', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'}
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </>
        )}

        {/* Signal Cycles Tab */}
        {tab === 'signals' && (
          <>
            <div className="grid grid-cols-3 sm:grid-cols-6 gap-3">
              {[
                { label: 'Total Cycles', value: total, color: 'text-text-primary' },
                { label: 'LONG', value: longs, color: 'text-accent-emerald' },
                { label: 'SHORT', value: shorts, color: 'text-accent-crimson' },
                { label: 'NO_TRADE', value: filtered.filter(h => h.direction === 'NO_TRADE').length, color: 'text-text-muted' },
                { label: 'Avg Score', value: avgScore.toFixed(2), color: 'text-accent-violet' },
                { label: 'Signals', value: signals, color: 'text-accent-amber' },
              ].map((s, i) => (
                <div key={i} className="bg-bg-secondary border border-border-default rounded-lg p-3 text-center">
                  <div className={`text-xl font-mono font-semibold ${s.color}`}>{s.value}</div>
                  <div className="text-[10px] text-text-muted uppercase tracking-wider mt-0.5">{s.label}</div>
                </div>
              ))}
            </div>

            <div className="bg-bg-secondary border border-border-default rounded-lg overflow-x-auto">
              <table className="w-full min-w-[600px]">
                <thead>
                  <tr className="border-b border-border-default text-xs text-text-muted uppercase tracking-wider">
                    <th className="text-left py-3 px-4">Time</th>
                    <th className="text-left py-3 px-4">Asset</th>
                    <th className="text-left py-3 px-4">Direction</th>
                    <th className="text-left py-3 px-4">Score</th>
                    <th className="text-left py-3 px-4">Decision</th>
                    <th className="text-left py-3 px-4">Agreement</th>
                    <th className="text-left py-3 px-4">Mode</th>
                  </tr>
                </thead>
                <tbody>
                  {loading ? (
                    <tr><td colSpan={7} className="py-8 text-center text-text-muted text-sm">Loading history...</td></tr>
                  ) : filtered.length === 0 ? (
                    <tr><td colSpan={7} className="py-8 text-center text-text-muted text-sm">
                      No cycle history yet. Cycles run automatically every 15 minutes.
                    </td></tr>
                  ) : (
                    filtered.map((h: any, i: number) => {
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
                          <td className="py-2.5 px-4 text-xs text-text-muted">{h.mode}</td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </AppShell>
  );
}
