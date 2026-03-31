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
const fp = (n: number) => `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`;

export default function PerformancePage() {
  const [data, setData] = useState<any>({});
  const [loading, setLoading] = useState(true);
  const [allocation, setAllocation] = useState(0);

  const load = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/v1/training/operations`, { headers: getH() });
      if (r.ok) setData(await r.json());
    } catch {}
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    if (typeof window !== 'undefined') {
      const a = localStorage.getItem('bahamut_demo_allocation');
      if (a) setAllocation(parseFloat(a));
    }
  }, [load]);

  const k = data.kpi || {};
  const strats = data.strategy_breakdown || {};
  const classes = data.class_breakdown || {};

  const systemPnl = k.net_pnl || 0;
  const systemCapital = 100000;
  const ratio = systemCapital > 0 ? allocation / systemCapital : 0;
  const userPnl = Math.round(systemPnl * ratio * 100) / 100;
  const userEquity = allocation + userPnl;
  const userReturn = allocation > 0 ? (userPnl / allocation) * 100 : 0;
  const wr = (k.win_rate || 0) * 100;

  if (loading) return <AppShell><div className="flex items-center justify-center min-h-[60vh]"><div className="w-8 h-8 border-2 border-accent-violet/30 border-t-accent-violet rounded-full animate-spin" /></div></AppShell>;

  return (
    <AppShell>
      <div className="max-w-[1000px] mx-auto space-y-4 px-2 sm:px-0">
        <h1 className="text-lg font-bold text-text-primary">Performance</h1>

        {/* Summary Cards */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 sm:gap-3">
          {[
            { l: 'Your Equity', v: fm(userEquity), c: 'text-text-primary' },
            { l: 'Your P&L', v: fmS(userPnl), c: userPnl >= 0 ? 'text-accent-emerald' : 'text-accent-crimson' },
            { l: 'Your Return', v: fp(userReturn), c: userReturn >= 0 ? 'text-accent-emerald' : 'text-accent-crimson' },
            { l: 'System Win Rate', v: `${wr.toFixed(1)}%`, c: wr >= 50 ? 'text-accent-emerald' : 'text-accent-amber' },
          ].map((s, i) => (
            <div key={i} className="bg-bg-secondary/60 border border-border-default rounded-xl p-3 text-center">
              <div className={`text-lg sm:text-xl font-bold ${s.c}`}>{s.v}</div>
              <div className="text-[9px] text-text-muted uppercase tracking-wider mt-1">{s.l}</div>
            </div>
          ))}
        </div>

        {/* How It Works */}
        <div className="bg-bg-secondary/60 border border-border-default rounded-xl p-4">
          <h2 className="text-sm font-bold text-text-primary mb-2">How Your Returns Are Calculated</h2>
          <div className="text-xs text-text-secondary space-y-1.5">
            <p>Bahamut trades a diversified portfolio of 40+ assets across crypto, stocks, forex, commodities, and indices using AI-powered strategies.</p>
            <p>Your returns are proportional to your allocation. With <span className="text-accent-violet font-bold">{fm(allocation)}</span> allocated out of <span className="text-text-primary font-bold">{fm(systemCapital)}</span> system capital, you receive <span className="text-accent-cyan font-bold">{(ratio * 100).toFixed(1)}%</span> of all trading profits and losses.</p>
            {allocation === 0 && <p className="text-accent-amber font-semibold">You have no allocation set. Go to Dashboard or Wallet to add funds and allocate.</p>}
          </div>
        </div>

        {/* Strategy Performance */}
        <div className="bg-bg-secondary/60 border border-border-default rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-border-default">
            <span className="text-sm font-bold text-text-primary">Strategy Performance</span>
          </div>
          <div className="p-4 overflow-x-auto">
            <table className="w-full text-[10px] sm:text-xs">
              <thead><tr className="border-b border-border-default text-[9px] text-text-muted uppercase tracking-wider text-left">
                <th className="py-2 pr-3">Strategy</th><th className="py-2 pr-3">Trades</th>
                <th className="py-2 pr-3">Win Rate</th><th className="py-2 pr-3">PF</th>
                <th className="py-2 pr-3">Total PnL</th><th className="py-2 pr-3">Your Share</th>
              </tr></thead>
              <tbody>
                {Object.entries(strats).map(([name, s]: [string, any]) => (
                  <tr key={name} className="border-b border-border-default/50">
                    <td className="py-2 pr-3 text-text-primary font-semibold">{name}</td>
                    <td className="py-2 pr-3 text-text-secondary">{s.closed_trades}</td>
                    <td className="py-2 pr-3 text-text-primary">{(s.win_rate * 100).toFixed(1)}%</td>
                    <td className="py-2 pr-3 text-text-primary">{s.profit_factor?.toFixed(2)}</td>
                    <td className={`py-2 pr-3 font-bold ${s.total_pnl >= 0 ? 'text-accent-emerald' : 'text-accent-crimson'}`}>{fmS(s.total_pnl)}</td>
                    <td className={`py-2 pr-3 font-bold ${s.total_pnl * ratio >= 0 ? 'text-accent-emerald' : 'text-accent-crimson'}`}>{fmS(Math.round(s.total_pnl * ratio * 100) / 100)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Asset Class Performance */}
        <div className="bg-bg-secondary/60 border border-border-default rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-border-default">
            <span className="text-sm font-bold text-text-primary">Asset Class Performance</span>
          </div>
          <div className="p-4">
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
              {Object.entries(classes).map(([cls, s]: [string, any]) => (
                <div key={cls} className="bg-bg-tertiary/50 border border-border-default rounded-lg p-3">
                  <div className="text-[9px] text-text-muted uppercase tracking-wider font-bold mb-1">{cls}</div>
                  <div className="text-xs text-text-primary font-semibold">{s.closed_trades} trades</div>
                  <div className={`text-[11px] font-bold mt-0.5 ${s.pnl >= 0 ? 'text-accent-emerald' : 'text-accent-crimson'}`}>{fmS(s.pnl)}</div>
                  <div className="text-[9px] text-text-muted">Your share: {fmS(Math.round(s.pnl * ratio * 100) / 100)}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
