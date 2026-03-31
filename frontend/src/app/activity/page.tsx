'use client';
import { useState, useEffect, useCallback } from 'react';
import AppShell from '@/components/layout/AppShell';

const API = process.env.NEXT_PUBLIC_API_URL || '';
const getH = (): Record<string, string> => {
  const t = typeof window !== 'undefined' ? localStorage.getItem('bahamut_token') : null;
  return t ? { Authorization: `Bearer ${t}` } : {};
};
const fm = (n: number) => `$${Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const fmS = (n: number) => `${n >= 0 ? '+' : '-'}${fm(n)}`;
const STRAT_NAMES: Record<string, string> = { v5_base: "S1 · EMA Trend", v5_tuned: "S2 · EMA Tuned", v9_breakout: "S3 · Breakout", v10_mean_reversion: "S4 · Mean Reversion" };
const sn = (s: string) => STRAT_NAMES[s] || s;

interface WalletEntry {
  type: string; amount: number; balance_after: number; allocation_after: number; timestamp: string; mode: string;
}

export default function ActivityPage() {
  const [trades, setTrades] = useState<any[]>([]);
  const [walletHistory, setWalletHistory] = useState<WalletEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<'all' | 'trades' | 'wallet'>('all');

  const load = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/v1/training/operations`, { headers: getH() });
      if (r.ok) {
        const d = await r.json();
        setTrades((d.closed_trades || []).slice(0, 50));
      }
    } catch {}
    if (typeof window !== 'undefined') {
      try {
        import('@/lib/walletApi').then(({ fetchWallet }) => {
          fetchWallet().then(w => {
            if (w) setWalletHistory(w.transactions.map(t => ({
              type: t.type, amount: t.amount, balance_after: t.balance_after,
              allocation_after: t.allocation_after, timestamp: t.timestamp, mode: t.mode,
            })));
          });
        });
      } catch {}
    }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  // Merge trades + wallet into unified timeline
  const tradeEvents = trades.map(t => ({
    type: 'trade' as const,
    timestamp: t.exit_time || t.entry_time || '',
    data: t,
  }));

  const walletEvents = walletHistory.map(w => ({
    type: 'wallet' as const,
    timestamp: w.timestamp,
    data: w,
  }));

  let allEvents = [...tradeEvents, ...walletEvents]
    .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());

  if (filter === 'trades') allEvents = allEvents.filter(e => e.type === 'trade');
  if (filter === 'wallet') allEvents = allEvents.filter(e => e.type === 'wallet');

  const fmtTime = (iso: string) => {
    if (!iso) return '';
    const d = new Date(iso);
    return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) + ' ' +
           d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false });
  };

  if (loading) return <AppShell><div className="flex items-center justify-center min-h-[60vh]"><div className="w-8 h-8 border-2 border-accent-violet/30 border-t-accent-violet rounded-full animate-spin" /></div></AppShell>;

  return (
    <AppShell>
      <div className="max-w-[900px] mx-auto space-y-4 px-2 sm:px-0">
        <div className="flex items-center justify-between">
          <h1 className="text-lg font-bold text-text-primary">Activity</h1>
          <div className="flex gap-1 bg-bg-tertiary rounded-lg border border-border-default p-0.5">
            {(['all', 'trades', 'wallet'] as const).map(f => (
              <button key={f} onClick={() => setFilter(f)}
                className={`px-3 py-1 text-[10px] font-bold rounded-md transition-all capitalize ${filter === f ? 'bg-accent-violet/20 text-accent-violet' : 'text-text-muted hover:text-text-secondary'}`}>
                {f}
              </button>
            ))}
          </div>
        </div>

        {allEvents.length === 0 ? (
          <div className="bg-bg-secondary/60 border border-border-default rounded-xl p-8 text-center">
            <p className="text-sm text-text-muted">No activity yet</p>
            <p className="text-xs text-text-muted mt-1">Trades and wallet events will appear here</p>
          </div>
        ) : (
          <div className="space-y-2">
            {allEvents.slice(0, 100).map((e, i) => {
              if (e.type === 'trade') {
                const t = e.data;
                const pnl = t.pnl || 0;
                const isFlat = Math.abs(pnl) < 0.01;
                return (
                  <div key={`t-${i}`} className="bg-bg-secondary/60 border border-border-default rounded-xl p-3 flex items-center gap-3">
                    <span className={`w-8 h-8 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0 ${
                      isFlat ? 'bg-border-default text-text-muted' : pnl > 0 ? 'bg-accent-emerald/15 text-accent-emerald' : 'bg-accent-crimson/15 text-accent-crimson'
                    }`}>
                      {isFlat ? '—' : pnl > 0 ? '↑' : '↓'}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-text-primary font-bold">{t.asset}</span>
                        <span className="text-[9px] text-text-muted">{sn(t.strategy)}</span>
                        <span className={`text-[9px] font-bold ${t.direction === 'LONG' ? 'text-accent-emerald' : 'text-accent-crimson'}`}>{t.direction}</span>
                        <span className={`px-1.5 py-0.5 rounded text-[8px] font-bold ${
                          isFlat ? 'bg-border-default text-text-muted' : pnl > 0 ? 'bg-accent-emerald/15 text-accent-emerald' : 'bg-accent-crimson/15 text-accent-crimson'
                        }`}>{isFlat ? 'FLAT' : pnl > 0 ? 'WIN' : 'LOSS'}</span>
                      </div>
                      <div className="text-[9px] text-text-muted mt-0.5">
                        {t.exit_reason} · {t.bars_held} bars · Entry {fm(t.entry_price)} → Exit {fm(t.exit_price)}
                      </div>
                    </div>
                    <div className="text-right shrink-0">
                      <div className={`text-xs font-bold ${isFlat ? 'text-text-muted' : pnl > 0 ? 'text-accent-emerald' : 'text-accent-crimson'}`}>{fmS(pnl)}</div>
                      <div className="text-[9px] text-text-muted">{fmtTime(e.timestamp)}</div>
                    </div>
                  </div>
                );
              } else {
                const w = e.data as WalletEntry;
                return (
                  <div key={`w-${i}`} className="bg-bg-secondary/60 border border-accent-violet/20 rounded-xl p-3 flex items-center gap-3">
                    <span className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold shrink-0 ${
                      w.type === 'deposit' ? 'bg-accent-emerald/15 text-accent-emerald' : 'bg-accent-violet/15 text-accent-violet'
                    }`}>
                      {w.type === 'deposit' ? '↓' : '↕'}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="text-xs text-text-primary font-bold">
                        {w.type === 'deposit' ? 'Deposit' : 'Allocation Change'}
                      </div>
                      <div className="text-[9px] text-text-muted mt-0.5">
                        {w.type === 'deposit' ? `Added ${fm(w.amount)}` : `Set allocation to ${fm(w.amount)}`} · Balance: {fm(w.balance_after)}
                      </div>
                    </div>
                    <div className="text-right shrink-0">
                      <div className={`text-xs font-bold ${w.type === 'deposit' ? 'text-accent-emerald' : 'text-accent-violet'}`}>
                        {w.type === 'deposit' ? fmS(w.amount) : fm(w.amount)}
                      </div>
                      <div className="text-[9px] text-text-muted">{fmtTime(e.timestamp)}</div>
                    </div>
                  </div>
                );
              }
            })}
          </div>
        )}
      </div>
    </AppShell>
  );
}
