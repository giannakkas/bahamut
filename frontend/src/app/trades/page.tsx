'use client';
import { useState, useEffect } from 'react';
import AppShell from '@/components/layout/AppShell';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts';

const CLOSED = [
  { id:1, asset:"BTC / USD", dir:"Long", entry:65200, exit:67240, pnl:287.50, pnlPct:3.13, alloc:2500, duration:"18h 12m", exitReason:"TP", closedAt:"Mar 26, 14:22", cls:"crypto" },
  { id:2, asset:"Gold", dir:"Long", entry:2340, exit:2385, pnl:142.00, pnlPct:1.92, alloc:2500, duration:"2d 6h", exitReason:"TP", closedAt:"Mar 25, 20:15", cls:"commodity" },
  { id:3, asset:"EUR / USD", dir:"Short", entry:1.0920, exit:1.0892, pnl:64.40, pnlPct:2.56, alloc:2300, duration:"8h 30m", exitReason:"TP", closedAt:"Mar 25, 11:44", cls:"fx" },
  { id:4, asset:"ETH / USD", dir:"Long", entry:3450, exit:3380, pnl:-51.80, pnlPct:-2.03, alloc:2500, duration:"12h 5m", exitReason:"SL", closedAt:"Mar 24, 19:30", cls:"crypto" },
  { id:5, asset:"SPY", dir:"Long", entry:572.40, exit:575.10, pnl:23.50, pnlPct:0.47, alloc:2500, duration:"4h 20m", exitReason:"TP", closedAt:"Mar 24, 16:00", cls:"stock" },
  { id:6, asset:"GBP / USD", dir:"Long", entry:1.2680, exit:1.2620, pnl:-138.00, pnlPct:-6.00, alloc:2300, duration:"1d 2h", exitReason:"SL", closedAt:"Mar 23, 22:10", cls:"fx" },
  { id:7, asset:"BTC / USD", dir:"Short", entry:69100, exit:67500, pnl:232.00, pnlPct:2.32, alloc:2500, duration:"14h 48m", exitReason:"TP", closedAt:"Mar 23, 08:55", cls:"crypto" },
  { id:8, asset:"TSLA", dir:"Short", entry:382.50, exit:370.20, pnl:80.50, pnlPct:3.22, alloc:2500, duration:"6h 15m", exitReason:"TP", closedAt:"Mar 22, 16:30", cls:"stock" },
  { id:9, asset:"Gold", dir:"Long", entry:2310, exit:2340, pnl:78.00, pnlPct:1.30, alloc:2500, duration:"1d 14h", exitReason:"TP", closedAt:"Mar 22, 10:45", cls:"commodity" },
  { id:10, asset:"NFLX", dir:"Short", entry:1025, exit:1040, pnl:-36.50, pnlPct:-1.46, alloc:2500, duration:"3h 40m", exitReason:"SL", closedAt:"Mar 21, 19:20", cls:"stock" },
];

const fm = (n: number) => { const a = Math.abs(n); if (a >= 1e6) return `$${(n/1e6).toFixed(2)}M`; if (a >= 1e3) return `$${(n/1e3).toFixed(1)}K`; return `$${n.toFixed(2)}`; };

export default function Trades() {
  const [loaded, setLoaded] = useState(false);
  const [filter, setFilter] = useState<'all'|'wins'|'losses'>('all');
  useEffect(() => { setTimeout(() => setLoaded(true), 100); }, []);

  const wins = CLOSED.filter(t => t.pnl > 0);
  const losses = CLOSED.filter(t => t.pnl <= 0);
  const totalPnl = CLOSED.reduce((s, t) => s + t.pnl, 0);
  const winRate = wins.length / CLOSED.length * 100;
  const avgWin = wins.reduce((s, t) => s + t.pnl, 0) / (wins.length || 1);
  const avgLoss = losses.reduce((s, t) => s + t.pnl, 0) / (losses.length || 1);
  const profitFactor = Math.abs(wins.reduce((s, t) => s + t.pnl, 0)) / (Math.abs(losses.reduce((s, t) => s + t.pnl, 0)) || 1);

  const barData = CLOSED.slice().reverse().map(t => ({ name:t.asset.split(' / ')[0], pnl:t.pnl }));
  const pieData = [{ name:"Wins", value:wins.length, color:"#10B981" },{ name:"Losses", value:losses.length, color:"#E94560" }];

  const shown = filter === 'wins' ? wins : filter === 'losses' ? losses : CLOSED;

  return (
    <AppShell>
      <div className="max-w-[1400px] space-y-5">
        <div className={`transition-all duration-700 ${loaded ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-3'}`}>
          <h1 className="text-xl sm:text-2xl font-bold">Trade History</h1>
          <p className="text-xs text-text-muted mt-1">{CLOSED.length} completed trades</p>
        </div>

        {/* Stats */}
        <div className={`grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 transition-all duration-700 delay-100 ${loaded ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-3'}`}>
          {[
            { l:"Total P&L", v:`${totalPnl >= 0 ? "+" : ""}${fm(totalPnl)}`, c: totalPnl >= 0 ? "text-accent-emerald" : "text-accent-crimson" },
            { l:"Win Rate", v:`${winRate.toFixed(0)}%`, c: winRate >= 60 ? "text-accent-emerald" : winRate >= 45 ? "text-accent-amber" : "text-accent-crimson" },
            { l:"Profit Factor", v:profitFactor.toFixed(2), c: profitFactor >= 1.5 ? "text-accent-emerald" : "text-text-primary" },
            { l:"Avg Win", v:`+${fm(avgWin)}`, c:"text-accent-emerald" },
            { l:"Avg Loss", v:fm(avgLoss), c:"text-accent-crimson" },
            { l:"Total Trades", v:CLOSED.length, c:"text-accent-cyan" },
          ].map(s => (
            <div key={s.l} className="bg-bg-secondary/60 border border-border-default rounded-xl p-3 sm:p-4 text-center">
              <div className={`text-base sm:text-lg font-bold tabular-nums ${s.c}`}>{s.v}</div>
              <div className="text-[8px] sm:text-[9px] text-text-muted uppercase tracking-wider font-semibold mt-0.5">{s.l}</div>
            </div>
          ))}
        </div>

        {/* Charts */}
        <div className={`grid grid-cols-1 lg:grid-cols-[1fr_240px] gap-4 transition-all duration-700 delay-200 ${loaded ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-3'}`}>
          <div className="bg-bg-secondary/60 border border-border-default rounded-xl p-4">
            <div className="text-xs font-bold mb-3">P&L by Trade</div>
            <div className="h-[200px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={barData} barSize={20}>
                  <XAxis dataKey="name" tick={{ fontSize:9, fill:'#555570' }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize:9, fill:'#555570' }} axisLine={false} tickLine={false} tickFormatter={(v) => `$${v}`} />
                  <Tooltip contentStyle={{ background:'#1C1C35', border:'1px solid #2A2A4A', borderRadius:8, fontSize:12 }} formatter={(v: number) => [`$${v.toFixed(2)}`, 'P&L']} />
                  <Bar dataKey="pnl" animationDuration={1200}>
                    {barData.map((d, i) => <Cell key={i} fill={d.pnl >= 0 ? '#10B981' : '#E94560'} radius={[4,4,0,0] as any} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
          <div className="bg-bg-secondary/60 border border-border-default rounded-xl p-4 flex flex-col items-center">
            <div className="text-xs font-bold mb-2 self-start">Win / Loss</div>
            <div className="h-[140px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={pieData} cx="50%" cy="50%" innerRadius={35} outerRadius={55} dataKey="value" animationDuration={1200} startAngle={90} endAngle={-270}>
                    {pieData.map((d, i) => <Cell key={i} fill={d.color} stroke="transparent" />)}
                  </Pie>
                </PieChart>
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

        {/* Filter + Trade list */}
        <div className="flex gap-2 items-center">
          <div className="text-[10px] text-text-muted uppercase tracking-widest font-semibold">Completed Trades</div>
          <div className="flex gap-1 ml-3">
            {(['all','wins','losses'] as const).map(f => (
              <button key={f} onClick={() => setFilter(f)} className={`px-3 py-1 rounded-md text-[10px] font-semibold transition-all ${filter === f ? 'bg-accent-cyan/10 text-accent-cyan border border-accent-cyan/25' : 'text-text-muted border border-transparent hover:text-text-secondary'}`}>{f === 'all' ? `All (${CLOSED.length})` : f === 'wins' ? `Wins (${wins.length})` : `Losses (${losses.length})`}</button>
            ))}
          </div>
        </div>

        <div className="space-y-2">
          {shown.map((t, i) => (
            <div key={t.id} className={`bg-bg-secondary/60 border border-border-default rounded-xl p-4 hover:border-accent-violet/15 transition-all duration-300 ${loaded ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'}`} style={{ transitionDelay: `${400 + i * 60}ms` }}>
              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 mb-2">
                <div className="flex items-center gap-3">
                  <div className={`w-8 h-8 rounded-lg flex items-center justify-center text-sm font-black ${t.pnl >= 0 ? "bg-accent-emerald/15 text-accent-emerald" : "bg-accent-crimson/15 text-accent-crimson"}`}>
                    {t.pnl >= 0 ? "✓" : "✕"}
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-bold">{t.asset}</span>
                      <span className={`px-1.5 py-0.5 text-[8px] font-bold rounded-full ${t.dir === "Long" ? "bg-accent-emerald/10 text-accent-emerald" : "bg-accent-crimson/10 text-accent-crimson"}`}>{t.dir}</span>
                      <span className={`px-1.5 py-0.5 text-[8px] font-bold rounded-full ${t.exitReason === "TP" ? "bg-accent-emerald/10 text-accent-emerald" : "bg-accent-crimson/10 text-accent-crimson"}`}>{t.exitReason}</span>
                    </div>
                    <div className="text-[10px] text-text-muted mt-0.5">{t.closedAt} · {t.duration}</div>
                  </div>
                </div>
                <div className="text-right">
                  <div className={`text-base font-bold tabular-nums ${t.pnl >= 0 ? "text-accent-emerald" : "text-accent-crimson"}`}>{t.pnl >= 0 ? "+" : ""}{fm(t.pnl)}</div>
                  <div className={`text-xs tabular-nums ${t.pnl >= 0 ? "text-accent-emerald/50" : "text-accent-crimson/50"}`}>{t.pnl >= 0 ? "+" : ""}{t.pnlPct.toFixed(2)}%</div>
                </div>
              </div>
              <div className="grid grid-cols-3 sm:grid-cols-4 gap-3 pt-2 border-t border-border-default/30">
                <div><div className="text-[8px] text-text-muted uppercase">Entry</div><div className="text-xs font-semibold tabular-nums text-text-secondary">{fm(t.entry)}</div></div>
                <div><div className="text-[8px] text-text-muted uppercase">Exit</div><div className="text-xs font-semibold tabular-nums text-text-secondary">{fm(t.exit)}</div></div>
                <div><div className="text-[8px] text-text-muted uppercase">Allocated</div><div className="text-xs font-semibold tabular-nums text-text-secondary">{fm(t.alloc)}</div></div>
                <div className="hidden sm:block"><div className="text-[8px] text-text-muted uppercase">Duration</div><div className="text-xs font-semibold text-text-secondary">{t.duration}</div></div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </AppShell>
  );
}
