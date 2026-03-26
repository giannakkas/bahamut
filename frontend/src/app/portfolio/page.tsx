'use client';
import { useState, useEffect } from 'react';
import AppShell from '@/components/layout/AppShell';
import { PieChart, Pie, Cell, ResponsiveContainer, AreaChart, Area, Tooltip, XAxis } from 'recharts';

const POSITIONS = [
  { id:1, asset:"BTC / USD", dir:"Long", entry:67240, current:68105, qty:0.037, alloc:2500, pnl:412.50, pnlPct:1.28, sl:65800, tp:70200, time:"6h 23m", cls:"crypto" },
  { id:2, asset:"ETH / USD", dir:"Long", entry:3380, current:3421, qty:0.74, alloc:2500, pnl:30.34, pnlPct:1.21, sl:3280, tp:3620, time:"4h 10m", cls:"crypto" },
  { id:3, asset:"Gold", dir:"Long", entry:2385, current:2412, qty:1.05, alloc:2500, pnl:28.35, pnlPct:1.13, sl:2340, tp:2480, time:"12h 45m", cls:"commodity" },
  { id:4, asset:"EUR / USD", dir:"Short", entry:1.0892, current:1.0841, qty:23000, alloc:2300, pnl:117.30, pnlPct:5.10, sl:1.0960, tp:1.0750, time:"1d 3h", cls:"fx" },
];

const ALLOC_DATA = [
  { name:"BTC / USD", value:2500, color:"#f7931a" },
  { name:"ETH / USD", value:2500, color:"#627eea" },
  { name:"Gold", value:2500, color:"#ffd700" },
  { name:"EUR / USD", value:2300, color:"#0984e3" },
  { name:"Available", value:90200, color:"#1C1C35" },
];

const CLASS_DATA = [
  { name:"Crypto", value:5000, color:"#6c5ce7" },
  { name:"Commodity", value:2500, color:"#fdcb6e" },
  { name:"FX", value:2300, color:"#0984e3" },
];

const EQUITY = Array.from({length:24}, (_, i) => ({ t:`${i}:00`, v:100000 + Math.sin(i*0.3)*800 + i*45 + (Math.random()-0.3)*200 }));

const fm = (n: number) => { const a = Math.abs(n); if (a >= 1e6) return `$${(n/1e6).toFixed(2)}M`; if (a >= 1e3) return `$${(n/1e3).toFixed(1)}K`; return `$${n.toFixed(2)}`; };

export default function Portfolio() {
  const [loaded, setLoaded] = useState(false);
  useEffect(() => { setTimeout(() => setLoaded(true), 100); }, []);

  const totalValue = POSITIONS.reduce((s, p) => s + p.alloc, 0);
  const totalPnl = POSITIONS.reduce((s, p) => s + p.pnl, 0);
  const totalPnlPct = (totalPnl / totalValue) * 100;

  return (
    <AppShell>
      <div className="w-full space-y-5">
        {/* Header */}
        <div className={`transition-all duration-700 ${loaded ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-3'}`}>
          <h1 className="text-xl sm:text-2xl font-bold">Portfolio</h1>
          <p className="text-xs text-text-muted mt-1">{POSITIONS.length} open positions · {fm(totalValue)} allocated</p>
        </div>

        {/* Summary Cards */}
        <div className={`grid grid-cols-2 sm:grid-cols-4 gap-3 transition-all duration-700 delay-100 ${loaded ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-3'}`}>
          {[
            { l:"Total Value", v:fm(totalValue), c:"text-text-primary" },
            { l:"Unrealized P&L", v:`${totalPnl >= 0 ? "+" : ""}${fm(totalPnl)}`, c: totalPnl >= 0 ? "text-accent-emerald" : "text-accent-crimson" },
            { l:"Return", v:`${totalPnlPct >= 0 ? "+" : ""}${totalPnlPct.toFixed(2)}%`, c: totalPnlPct >= 0 ? "text-accent-emerald" : "text-accent-crimson" },
            { l:"Positions", v:POSITIONS.length, c:"text-accent-cyan" },
          ].map(s => (
            <div key={s.l} className="bg-bg-secondary/60 border border-border-default rounded-xl p-4 text-center">
              <div className={`text-lg sm:text-xl font-bold tabular-nums ${s.c}`}>{s.v}</div>
              <div className="text-[9px] text-text-muted uppercase tracking-wider font-semibold mt-0.5">{s.l}</div>
            </div>
          ))}
        </div>

        {/* Charts Row */}
        <div className={`grid grid-cols-1 lg:grid-cols-3 2xl:grid-cols-4 gap-4 transition-all duration-700 delay-200 ${loaded ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-3'}`}>
          {/* Equity Curve */}
          <div className="lg:col-span-2 2xl:col-span-3 bg-bg-secondary/60 border border-border-default rounded-xl p-4">
            <div className="text-xs font-bold mb-3">Portfolio Equity — Today</div>
            <div className="h-[180px] 2xl:h-[240px]">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={EQUITY}>
                  <defs>
                    <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#6c5ce7" stopOpacity={0.3} />
                      <stop offset="100%" stopColor="#6c5ce7" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <XAxis dataKey="t" tick={{ fontSize:9, fill:'#555570' }} axisLine={false} tickLine={false} interval={5} />
                  <Tooltip contentStyle={{ background:'#1C1C35', border:'1px solid #2A2A4A', borderRadius:8, fontSize:12 }} labelStyle={{ color:'#8888AA' }} formatter={(v: number) => [`$${v.toFixed(0)}`, 'Equity']} />
                  <Area type="monotone" dataKey="v" stroke="#6c5ce7" strokeWidth={2} fill="url(#eqGrad)" animationDuration={1500} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Allocation Pies */}
          <div className="bg-bg-secondary/60 border border-border-default rounded-xl p-4 space-y-4">
            <div>
              <div className="text-xs font-bold mb-2">Allocation</div>
              <div className="h-[100px]">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={ALLOC_DATA} cx="50%" cy="50%" innerRadius={28} outerRadius={45} dataKey="value" animationDuration={1200}>
                      {ALLOC_DATA.map((d, i) => <Cell key={i} fill={d.color} stroke="transparent" />)}
                    </Pie>
                    <Tooltip contentStyle={{ background:'#1C1C35', border:'1px solid #2A2A4A', borderRadius:8, fontSize:11 }} formatter={(v: number) => [fm(v), '']} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <div className="flex flex-wrap gap-x-3 gap-y-1 justify-center">
                {ALLOC_DATA.filter(d => d.name !== "Available").map(d => (
                  <div key={d.name} className="flex items-center gap-1"><span className="w-2 h-2 rounded-full shrink-0" style={{ background:d.color }} /><span className="text-[9px] text-text-muted">{d.name}</span></div>
                ))}
              </div>
            </div>
            <div>
              <div className="text-xs font-bold mb-2">By Class</div>
              <div className="h-[100px]">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={CLASS_DATA} cx="50%" cy="50%" innerRadius={28} outerRadius={45} dataKey="value" animationDuration={1200} animationBegin={400}>
                      {CLASS_DATA.map((d, i) => <Cell key={i} fill={d.color} stroke="transparent" />)}
                    </Pie>
                    <Tooltip contentStyle={{ background:'#1C1C35', border:'1px solid #2A2A4A', borderRadius:8, fontSize:11 }} formatter={(v: number) => [fm(v), '']} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <div className="flex flex-wrap gap-x-3 gap-y-1 justify-center">
                {CLASS_DATA.map(d => (
                  <div key={d.name} className="flex items-center gap-1"><span className="w-2 h-2 rounded-full shrink-0" style={{ background:d.color }} /><span className="text-[9px] text-text-muted">{d.name}</span></div>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* Position Cards */}
        <div className="space-y-3">
          <div className="text-[10px] text-text-muted uppercase tracking-widest font-semibold">Open Positions</div>
          {POSITIONS.map((p, i) => (
            <div key={p.id} className={`bg-bg-secondary/60 border border-border-default rounded-xl p-4 sm:p-5 hover:border-accent-violet/20 transition-all duration-300 ${loaded ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'}`} style={{ transitionDelay: `${300 + i * 100}ms` }}>
              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-3">
                <div className="flex items-center gap-3">
                  <div className={`w-10 h-10 rounded-xl flex items-center justify-center text-lg font-black ${p.cls === "crypto" ? "bg-accent-violet/15 text-accent-violet" : p.cls === "fx" ? "bg-accent-cyan/15 text-accent-cyan" : "bg-accent-amber/15 text-accent-amber"}`}>
                    {p.asset[0]}
                  </div>
                  <div>
                    <div className="text-sm font-bold">{p.asset}</div>
                    <div className="flex items-center gap-2 mt-0.5">
                      <span className={`px-2 py-0.5 text-[9px] font-bold rounded-full ${p.dir === "Long" ? "bg-accent-emerald/15 text-accent-emerald" : "bg-accent-crimson/15 text-accent-crimson"}`}>{p.dir}</span>
                      <span className="text-[10px] text-text-muted">{p.time} open</span>
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-4 sm:gap-6">
                  <div className="text-right">
                    <div className={`text-lg font-bold tabular-nums ${p.pnl >= 0 ? "text-accent-emerald" : "text-accent-crimson"}`}>{p.pnl >= 0 ? "+" : ""}{fm(p.pnl)}</div>
                    <div className={`text-xs tabular-nums ${p.pnl >= 0 ? "text-accent-emerald/50" : "text-accent-crimson/50"}`}>{p.pnl >= 0 ? "+" : ""}{p.pnlPct.toFixed(2)}%</div>
                  </div>
                  <button className="px-3 py-1.5 rounded-lg border border-border-default text-xs text-text-muted hover:bg-bg-tertiary hover:text-text-primary transition-colors">Close</button>
                </div>
              </div>
              {/* Details row */}
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 pt-3 border-t border-border-default/40">
                {[
                  { l:"Entry", v:fm(p.entry) },
                  { l:"Current", v:fm(p.current) },
                  { l:"Quantity", v:p.qty.toString() },
                  { l:"Allocated", v:fm(p.alloc) },
                  { l:"Stop Loss", v:fm(p.sl), c:"text-accent-crimson/60" },
                  { l:"Take Profit", v:fm(p.tp), c:"text-accent-emerald/60" },
                ].map(d => (
                  <div key={d.l}>
                    <div className="text-[9px] text-text-muted uppercase">{d.l}</div>
                    <div className={`text-sm font-semibold tabular-nums ${d.c || "text-text-secondary"}`}>{d.v}</div>
                  </div>
                ))}
              </div>
              {/* Mini P&L bar */}
              <div className="mt-3 h-1 bg-bg-tertiary rounded-full overflow-hidden">
                <div className={`h-full rounded-full transition-all duration-1000 ${p.pnl >= 0 ? "bg-accent-emerald" : "bg-accent-crimson"}`} style={{ width: `${Math.min(100, Math.abs(p.pnlPct) * 10)}%`, transitionDelay: `${500 + i * 100}ms` }} />
              </div>
            </div>
          ))}
        </div>
      </div>
    </AppShell>
  );
}
