'use client';
import { useState, useEffect } from 'react';
import AppShell from '@/components/layout/AppShell';
import { PieChart, Pie, Cell, ResponsiveContainer, AreaChart, Area, Tooltip, XAxis } from 'recharts';
import { fetchPositions, fetchCandles, fetchTradeStats } from '@/lib/traderApi';

const fm = (n: number) => { const a = Math.abs(n); if (a >= 1e6) return `$${(n/1e6).toFixed(2)}M`; if (a >= 1e3) return `$${(n/1e3).toFixed(1)}K`; return `$${n.toFixed(2)}`; };
const COLORS = ['#6c5ce7','#f7931a','#627eea','#ffd700','#0984e3','#e94560','#10B981','#F59E0B'];

export default function Portfolio() {
  const [positions, setPositions] = useState<any[]>([]);
  const [equity, setEquity] = useState<any[]>([]);
  const [stats, setStats] = useState<any>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    (async () => {
      const [pos, candles, st] = await Promise.all([
        fetchPositions(),
        fetchCandles('BTCUSD', '1h', 24),
        fetchTradeStats(),
      ]);
      if (pos) setPositions(pos);
      if (st) setStats(st);
      if (candles?.length > 0) {
        const base = st?.portfolio?.balance || 100000;
        const fc = candles[0]?.close || 1;
        setEquity(candles.map((c: any) => ({ t: c.datetime?.split(' ')[1]?.slice(0,5) || '', v: Math.round(base * (c.close / fc)) })));
      }
      setLoaded(true);
    })();
    const iv = setInterval(async () => { const pos = await fetchPositions(); if (pos) setPositions(pos); }, 30000);
    return () => clearInterval(iv);
  }, []);

  const totalValue = positions.reduce((s, p) => s + (p.quantity || 0) * (p.entry_price || 0), 0);
  const totalPnl = positions.reduce((s, p) => s + (p.unrealized_pnl || 0), 0);
  const totalPnlPct = totalValue > 0 ? (totalPnl / totalValue) * 100 : 0;
  const balance = stats?.portfolio?.balance || 100000;

  const allocData = positions.length > 0
    ? [...positions.map((p, i) => ({ name: p.asset, value: Math.round((p.quantity||0) * (p.entry_price||0)), color: COLORS[i % COLORS.length] })), { name: "Available", value: Math.max(0, balance - totalValue), color: "#1C1C35" }]
    : [{ name: "Available", value: balance, color: "#1C1C35" }];

  const classMap: Record<string, number> = {};
  positions.forEach(p => {
    const cls = ['BTC','ETH','SOL','XRP'].some(c => p.asset?.includes(c)) ? 'Crypto' : ['EUR','GBP','USD','JPY','AUD','NZD','CAD','CHF'].some(c => p.asset?.startsWith(c)) ? 'FX' : ['XAU','XAG'].some(c => p.asset?.includes(c)) ? 'Commodity' : 'Stock';
    classMap[cls] = (classMap[cls] || 0) + (p.quantity||0) * (p.entry_price||0);
  });
  const classColors: Record<string,string> = { Crypto:'#6c5ce7', FX:'#0984e3', Commodity:'#fdcb6e', Stock:'#e94560' };
  const classData = Object.entries(classMap).map(([name, value]) => ({ name, value: Math.round(value), color: classColors[name] || '#636e72' }));

  return (
    <AppShell>
      <div className="w-full space-y-5">
        <div className={`transition-all duration-700 ${loaded ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-3'}`}>
          <h1 className="text-xl sm:text-2xl font-bold">Portfolio</h1>
          <p className="text-xs text-text-muted mt-1">{positions.length} open positions · {fm(totalValue)} allocated</p>
        </div>

        <div className={`grid grid-cols-2 sm:grid-cols-4 gap-3 transition-all duration-700 delay-100 ${loaded ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-3'}`}>
          {[
            { l:"Total Value", v:fm(totalValue), c:"text-text-primary" },
            { l:"Unrealized P&L", v:`${totalPnl >= 0 ? "+" : ""}${fm(totalPnl)}`, c: totalPnl >= 0 ? "text-accent-emerald" : "text-accent-crimson" },
            { l:"Return", v:`${totalPnlPct >= 0 ? "+" : ""}${totalPnlPct.toFixed(2)}%`, c: totalPnlPct >= 0 ? "text-accent-emerald" : "text-accent-crimson" },
            { l:"Positions", v:positions.length, c:"text-accent-cyan" },
          ].map(s => (
            <div key={s.l} className="bg-bg-secondary/60 border border-border-default rounded-xl p-4 text-center">
              <div className={`text-lg sm:text-xl font-bold tabular-nums ${s.c}`}>{s.v}</div>
              <div className="text-[9px] text-text-muted uppercase tracking-wider font-semibold mt-0.5">{s.l}</div>
            </div>
          ))}
        </div>

        <div className={`grid grid-cols-1 lg:grid-cols-3 2xl:grid-cols-4 gap-4 transition-all duration-700 delay-200 ${loaded ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-3'}`}>
          <div className="lg:col-span-2 2xl:col-span-3 bg-bg-secondary/60 border border-border-default rounded-xl p-4">
            <div className="text-xs font-bold mb-3">Portfolio Equity — Today</div>
            <div className="h-[180px] 2xl:h-[240px]">
              {equity.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={equity}>
                    <defs><linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#6c5ce7" stopOpacity={0.3} /><stop offset="100%" stopColor="#6c5ce7" stopOpacity={0} /></linearGradient></defs>
                    <XAxis dataKey="t" tick={{ fontSize:9, fill:'#555570' }} axisLine={false} tickLine={false} interval={5} />
                    <Tooltip contentStyle={{ background:'#1C1C35', border:'1px solid #2A2A4A', borderRadius:8, fontSize:12 }} formatter={(v: number) => [`$${v.toFixed(0)}`, 'Equity']} />
                    <Area type="monotone" dataKey="v" stroke="#6c5ce7" strokeWidth={2} fill="url(#eqGrad)" animationDuration={1500} />
                  </AreaChart>
                </ResponsiveContainer>
              ) : <div className="flex items-center justify-center h-full text-text-muted text-sm">Loading chart data...</div>}
            </div>
          </div>
          <div className="bg-bg-secondary/60 border border-border-default rounded-xl p-4 space-y-4">
            <div>
              <div className="text-xs font-bold mb-2">Allocation</div>
              <div className="h-[100px]">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart><Pie data={allocData} cx="50%" cy="50%" innerRadius={28} outerRadius={45} dataKey="value" animationDuration={1200}>{allocData.map((d, i) => <Cell key={i} fill={d.color} stroke="transparent" />)}</Pie></PieChart>
                </ResponsiveContainer>
              </div>
              <div className="flex flex-wrap gap-x-3 gap-y-1 justify-center">{allocData.filter(d => d.name !== "Available").map(d => (<div key={d.name} className="flex items-center gap-1"><span className="w-2 h-2 rounded-full shrink-0" style={{ background:d.color }} /><span className="text-[9px] text-text-muted">{d.name}</span></div>))}</div>
            </div>
            {classData.length > 0 && <div>
              <div className="text-xs font-bold mb-2">By Class</div>
              <div className="h-[100px]">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart><Pie data={classData} cx="50%" cy="50%" innerRadius={28} outerRadius={45} dataKey="value" animationDuration={1200} animationBegin={400}>{classData.map((d, i) => <Cell key={i} fill={d.color} stroke="transparent" />)}</Pie></PieChart>
                </ResponsiveContainer>
              </div>
              <div className="flex flex-wrap gap-x-3 gap-y-1 justify-center">{classData.map(d => (<div key={d.name} className="flex items-center gap-1"><span className="w-2 h-2 rounded-full shrink-0" style={{ background:d.color }} /><span className="text-[9px] text-text-muted">{d.name}</span></div>))}</div>
            </div>}
          </div>
        </div>

        <div className="space-y-3">
          <div className="text-[10px] text-text-muted uppercase tracking-widest font-semibold">Open Positions</div>
          {positions.length === 0 && loaded && <div className="bg-bg-secondary/60 border border-border-default rounded-xl p-8 text-center text-text-muted">No open positions. Bahamut is scanning for opportunities...</div>}
          {positions.map((p, i) => (
            <div key={p.id || i} className={`bg-bg-secondary/60 border border-border-default rounded-xl p-4 sm:p-5 hover:border-accent-violet/20 transition-all duration-300 ${loaded ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'}`} style={{ transitionDelay: `${300 + i * 100}ms` }}>
              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-3">
                <div className="flex items-center gap-3">
                  <div className={`w-10 h-10 rounded-xl flex items-center justify-center text-lg font-black ${['BTC','ETH','SOL'].some(c => p.asset?.includes(c)) ? "bg-accent-violet/15 text-accent-violet" : ['EUR','GBP','USD'].some(c => p.asset?.startsWith(c)) ? "bg-accent-cyan/15 text-accent-cyan" : "bg-accent-amber/15 text-accent-amber"}`}>{(p.asset||'?')[0]}</div>
                  <div>
                    <div className="text-sm font-bold">{p.asset}</div>
                    <div className="flex items-center gap-2 mt-0.5">
                      <span className={`px-2 py-0.5 text-[9px] font-bold rounded-full ${p.direction === "LONG" ? "bg-accent-emerald/15 text-accent-emerald" : "bg-accent-crimson/15 text-accent-crimson"}`}>{p.direction}</span>
                      <span className="text-[10px] text-text-muted">Score: {p.signal_score || '—'}</span>
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-4 sm:gap-6">
                  <div className="text-right">
                    <div className={`text-lg font-bold tabular-nums ${(p.unrealized_pnl||0) >= 0 ? "text-accent-emerald" : "text-accent-crimson"}`}>{(p.unrealized_pnl||0) >= 0 ? "+" : ""}{fm(p.unrealized_pnl||0)}</div>
                    <div className={`text-xs tabular-nums ${(p.unrealized_pnl_pct||0) >= 0 ? "text-accent-emerald/50" : "text-accent-crimson/50"}`}>{(p.unrealized_pnl_pct||0) >= 0 ? "+" : ""}{(p.unrealized_pnl_pct||0).toFixed(2)}%</div>
                  </div>
                </div>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 pt-3 border-t border-border-default/40">
                {[
                  { l:"Entry", v:`$${(p.entry_price||0).toFixed(2)}` },
                  { l:"Current", v:`$${(p.current_price||0).toFixed(2)}` },
                  { l:"Quantity", v:(p.quantity||0).toFixed(4) },
                  { l:"Stop Loss", v:`$${(p.stop_loss||0).toFixed(2)}`, c:"text-accent-crimson/60" },
                  { l:"Take Profit", v:`$${(p.take_profit||0).toFixed(2)}`, c:"text-accent-emerald/60" },
                  { l:"Opened", v:p.opened_at ? new Date(p.opened_at).toLocaleDateString('en-GB',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}) : '—' },
                ].map(d => (<div key={d.l}><div className="text-[9px] text-text-muted uppercase">{d.l}</div><div className={`text-sm font-semibold tabular-nums ${d.c || "text-text-secondary"}`}>{d.v}</div></div>))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </AppShell>
  );
}
