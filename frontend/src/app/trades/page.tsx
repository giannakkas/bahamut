'use client';
import { useState, useEffect } from 'react';
import AppShell from '@/components/layout/AppShell';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts';
import { fetchClosedTrades, fetchTradeStats } from '@/lib/traderApi';

const fm = (n: number) => { const a = Math.abs(n); if (a >= 1e6) return `$${(n/1e6).toFixed(2)}M`; if (a >= 1e3) return `$${(n/1e3).toFixed(1)}K`; return `$${n.toFixed(2)}`; };

export default function Trades() {
  const [trades, setTrades] = useState<any[]>([]);
  const [stats, setStats] = useState<any>(null);
  const [loaded, setLoaded] = useState(false);
  const [filter, setFilter] = useState<'all'|'wins'|'losses'>('all');

  useEffect(() => {
    (async () => {
      const [t, s] = await Promise.all([fetchClosedTrades(), fetchTradeStats()]);
      if (t) setTrades(t);
      if (s) setStats(s);
      setLoaded(true);
    })();
  }, []);

  const wins = trades.filter(t => (t.realized_pnl || 0) > 0);
  const losses = trades.filter(t => (t.realized_pnl || 0) <= 0);
  const totalPnl = stats?.portfolio?.total_pnl || trades.reduce((s, t) => s + (t.realized_pnl || 0), 0);
  const winRate = stats?.portfolio?.win_rate || (trades.length > 0 ? wins.length / trades.length * 100 : 0);
  const avgWin = stats?.averages?.avg_win || (wins.length > 0 ? wins.reduce((s, t) => s + (t.realized_pnl||0), 0) / wins.length : 0);
  const avgLoss = stats?.averages?.avg_loss || (losses.length > 0 ? losses.reduce((s, t) => s + (t.realized_pnl||0), 0) / losses.length : 0);
  const profitFactor = Math.abs(wins.reduce((s, t) => s + (t.realized_pnl||0), 0)) / (Math.abs(losses.reduce((s, t) => s + (t.realized_pnl||0), 0)) || 1);
  const totalTrades = stats?.portfolio?.total_trades || trades.length;

  const barData = trades.slice(-20).map(t => ({ name: (t.asset||'').replace('USD','').slice(0,6), pnl: t.realized_pnl || 0 }));
  const pieData = [{ name:"Wins", value: wins.length || 0, color:"#10B981" },{ name:"Losses", value: losses.length || 0, color:"#E94560" }];
  const shown = filter === 'wins' ? wins : filter === 'losses' ? losses : trades;

  return (
    <AppShell>
      <div className="w-full space-y-5">
        <div className={`transition-all duration-700 ${loaded ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-3'}`}>
          <h1 className="text-xl sm:text-2xl font-bold">Trade History</h1>
          <p className="text-xs text-text-muted mt-1">{totalTrades} completed trades</p>
        </div>

        <div className={`grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 transition-all duration-700 delay-100 ${loaded ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-3'}`}>
          {[
            { l:"Total P&L", v:`${totalPnl >= 0 ? "+" : ""}${fm(totalPnl)}`, c: totalPnl >= 0 ? "text-accent-emerald" : "text-accent-crimson" },
            { l:"Win Rate", v:`${winRate.toFixed(0)}%`, c: winRate >= 60 ? "text-accent-emerald" : winRate >= 45 ? "text-accent-amber" : "text-accent-crimson" },
            { l:"Profit Factor", v:profitFactor.toFixed(2), c: profitFactor >= 1.5 ? "text-accent-emerald" : "text-text-primary" },
            { l:"Avg Win", v:`+${fm(avgWin)}`, c:"text-accent-emerald" },
            { l:"Avg Loss", v:fm(avgLoss), c:"text-accent-crimson" },
            { l:"Total Trades", v:totalTrades, c:"text-accent-cyan" },
          ].map(s => (
            <div key={s.l} className="bg-bg-secondary/60 border border-border-default rounded-xl p-3 sm:p-4 text-center">
              <div className={`text-base sm:text-lg font-bold tabular-nums ${s.c}`}>{s.v}</div>
              <div className="text-[8px] sm:text-[9px] text-text-muted uppercase tracking-wider font-semibold mt-0.5">{s.l}</div>
            </div>
          ))}
        </div>

        <div className={`grid grid-cols-1 lg:grid-cols-[1fr_240px] 2xl:grid-cols-[1fr_300px] gap-4 transition-all duration-700 delay-200 ${loaded ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-3'}`}>
          <div className="bg-bg-secondary/60 border border-border-default rounded-xl p-4">
            <div className="text-xs font-bold mb-3">P&L by Trade</div>
            <div className="h-[200px] 2xl:h-[280px]">
              {barData.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={barData} barSize={20}>
                    <XAxis dataKey="name" tick={{ fontSize:9, fill:'#555570' }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize:9, fill:'#555570' }} axisLine={false} tickLine={false} tickFormatter={(v) => `$${v}`} />
                    <Tooltip contentStyle={{ background:'#1C1C35', border:'1px solid #2A2A4A', borderRadius:8, fontSize:12 }} formatter={(v: number) => [`$${v.toFixed(2)}`, 'P&L']} />
                    <Bar dataKey="pnl" animationDuration={1200}>{barData.map((d, i) => <Cell key={i} fill={d.pnl >= 0 ? '#10B981' : '#E94560'} />)}</Bar>
                  </BarChart>
                </ResponsiveContainer>
              ) : <div className="flex items-center justify-center h-full text-text-muted text-sm">{loaded ? 'No trades yet' : 'Loading...'}</div>}
            </div>
          </div>
          <div className="bg-bg-secondary/60 border border-border-default rounded-xl p-4 flex flex-col items-center">
            <div className="text-xs font-bold mb-2 self-start">Win / Loss</div>
            <div className="h-[140px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart><Pie data={pieData} cx="50%" cy="50%" innerRadius={35} outerRadius={55} dataKey="value" animationDuration={1200} startAngle={90} endAngle={-270}>{pieData.map((d, i) => <Cell key={i} fill={d.color} stroke="transparent" />)}</Pie></PieChart>
              </ResponsiveContainer>
            </div>
            <div className="text-2xl font-black text-text-primary -mt-2">{winRate.toFixed(0)}%</div>
            <div className="text-[9px] text-text-muted uppercase tracking-wider font-semibold">Win Rate</div>
            <div className="flex gap-4 mt-3">
              <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-accent-emerald" /><span className="text-[10px] text-text-muted">{wins.length} Wins</span></div>
              <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-accent-crimson" /><span className="text-[10px] text-text-muted">{losses.length} Losses</span></div>
            </div>
          </div>
        </div>

        <div className="flex gap-2 items-center">
          <div className="text-[10px] text-text-muted uppercase tracking-widest font-semibold">Completed Trades</div>
          <div className="flex gap-1 ml-3">
            {(['all','wins','losses'] as const).map(f => (
              <button key={f} onClick={() => setFilter(f)} className={`px-3 py-1 rounded-md text-[10px] font-semibold transition-all ${filter === f ? 'bg-accent-cyan/10 text-accent-cyan border border-accent-cyan/25' : 'text-text-muted border border-transparent hover:text-text-secondary'}`}>{f === 'all' ? `All (${trades.length})` : f === 'wins' ? `Wins (${wins.length})` : `Losses (${losses.length})`}</button>
            ))}
          </div>
        </div>

        {shown.length === 0 && loaded && <div className="bg-bg-secondary/60 border border-border-default rounded-xl p-8 text-center text-text-muted">No completed trades yet. Bahamut is in learning phase...</div>}

        <div className="space-y-2">
          {shown.map((t, i) => (
            <div key={t.id || i} className={`bg-bg-secondary/60 border border-border-default rounded-xl p-4 hover:border-accent-violet/15 transition-all duration-300 ${loaded ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'}`} style={{ transitionDelay: `${400 + i * 60}ms` }}>
              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 mb-2">
                <div className="flex items-center gap-3">
                  <div className={`w-8 h-8 rounded-lg flex items-center justify-center text-sm font-black ${(t.realized_pnl||0) >= 0 ? "bg-accent-emerald/15 text-accent-emerald" : "bg-accent-crimson/15 text-accent-crimson"}`}>
                    {(t.realized_pnl||0) >= 0 ? "✓" : "✕"}
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-bold">{t.asset}</span>
                      <span className={`px-1.5 py-0.5 text-[8px] font-bold rounded-full ${t.direction === "LONG" ? "bg-accent-emerald/10 text-accent-emerald" : "bg-accent-crimson/10 text-accent-crimson"}`}>{t.direction}</span>
                      <span className={`px-1.5 py-0.5 text-[8px] font-bold rounded-full ${t.status?.includes('TP') ? "bg-accent-emerald/10 text-accent-emerald" : "bg-accent-crimson/10 text-accent-crimson"}`}>{t.status?.replace('CLOSED_','') || '—'}</span>
                    </div>
                    <div className="text-[10px] text-text-muted mt-0.5">{t.closed_at ? new Date(t.closed_at).toLocaleDateString('en-GB',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}) : ''} · Score: {t.signal_score || '—'}</div>
                  </div>
                </div>
                <div className="text-right">
                  <div className={`text-base font-bold tabular-nums ${(t.realized_pnl||0) >= 0 ? "text-accent-emerald" : "text-accent-crimson"}`}>{(t.realized_pnl||0) >= 0 ? "+" : ""}{fm(t.realized_pnl||0)}</div>
                  <div className={`text-xs tabular-nums ${(t.realized_pnl_pct||0) >= 0 ? "text-accent-emerald/50" : "text-accent-crimson/50"}`}>{(t.realized_pnl_pct||0) >= 0 ? "+" : ""}{(t.realized_pnl_pct||0).toFixed(2)}%</div>
                </div>
              </div>
              <div className="grid grid-cols-3 sm:grid-cols-5 gap-3 pt-2 border-t border-border-default/30">
                <div><div className="text-[8px] text-text-muted uppercase">Entry</div><div className="text-xs font-semibold tabular-nums text-text-secondary">${(t.entry_price||0).toFixed(2)}</div></div>
                <div><div className="text-[8px] text-text-muted uppercase">Exit</div><div className="text-xs font-semibold tabular-nums text-text-secondary">${(t.exit_price||0).toFixed(2)}</div></div>
                <div><div className="text-[8px] text-text-muted uppercase">Qty</div><div className="text-xs font-semibold tabular-nums text-text-secondary">{(t.quantity||0).toFixed(4)}</div></div>
                <div className="hidden sm:block"><div className="text-[8px] text-text-muted uppercase">Label</div><div className="text-xs font-semibold text-text-secondary">{t.signal_label || '—'}</div></div>
                <div className="hidden sm:block"><div className="text-[8px] text-text-muted uppercase">Consensus</div><div className="text-xs font-semibold text-text-secondary">{t.consensus_score ? `${(t.consensus_score*100).toFixed(0)}%` : '—'}</div></div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </AppShell>
  );
}
