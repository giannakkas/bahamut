'use client';
import { useState, useEffect } from 'react';
import AppShell from '@/components/layout/AppShell';
import { AreaChart, Area, ResponsiveContainer, Tooltip, XAxis } from 'recharts';

const fm = (n: number) => { if (n == null) return "$0"; const a = Math.abs(n); if (a >= 1e6) return `$${(n/1e6).toFixed(2)}M`; if (a >= 1e3) return `$${(n/1e3).toFixed(1)}K`; return `$${n.toFixed(2)}`; };
const fp = (n: number) => `${n >= 0 ? "+" : ""}${n.toFixed(1)}%`;

const DATA = { balance:100000, available:72000, todayPnl:1842.50, todayPnlPct:1.84, tradingAmount:50000, winRate:67, tradesClosed:23, riskLevel:"Low", systemStatus:"Online" };

const EQUITY = Array.from({length:24}, (_, i) => ({ t:`${String(i).padStart(2,'0')}:00`, v:98200 + Math.sin(i*0.25)*600 + i*75 + (Math.random()-0.3)*150 }));

const OPPS = [
  { asset:"BTC / USD", dir:"Long", status:"Ready", chance:85, risk:"Medium", desc:"Strong uptrend forming with high momentum" },
  { asset:"ETH / USD", dir:"Long", status:"Close", chance:72, risk:"Medium", desc:"Approaching key breakout level" },
  { asset:"EUR / USD", dir:"Short", status:"Watching", chance:58, risk:"Low", desc:"Dollar strength building gradually" },
  { asset:"Gold", dir:"Long", status:"Ready", chance:81, risk:"Low", desc:"Safe haven demand increasing" },
  { asset:"SPY", dir:"Watching", status:"Blocked", chance:35, risk:"High", desc:"Market closed — waiting for open" },
  { asset:"GBP / USD", dir:"Long", status:"Watching", chance:44, risk:"Medium", desc:"BoE decision pending tomorrow" },
];

const TRADES = [{ asset:"BTC / USD", dir:"Long", entry:67240, pnl:412.50, pnlPct:1.28, alloc:2500, sl:65800, tp:70200, time:"6h 23m" }];

const NEWS = [
  { hl:"Fed Holds Rates Steady", sum:"Markets rally as the Fed maintains interest rates.", t:"2h ago", impact:78, dir:"Bullish" },
  { hl:"Bitcoin Breaks $68K Resistance", sum:"BTC surges past key resistance with strong volume.", t:"3h ago", impact:85, dir:"Bullish" },
  { hl:"EU Manufacturing Disappoints", sum:"Eurozone PMI falls below expectations.", t:"4h ago", impact:62, dir:"Bearish" },
  { hl:"Oil Rises on Supply Concerns", sum:"Brent crude climbs 2% as OPEC+ signals cuts.", t:"5h ago", impact:71, dir:"Bullish" },
  { hl:"Tech Earnings Beat Estimates", sum:"Major tech companies beat Q1 estimates.", t:"6h ago", impact:74, dir:"Bullish" },
  { hl:"China GDP Growth Slows", sum:"Q1 growth misses target.", t:"8h ago", impact:68, dir:"Bearish" },
  { hl:"Gold Hits All-Time High", sum:"Safe haven demand pushes gold past $2,400.", t:"10h ago", impact:80, dir:"Bullish" },
];

const ACTIVITY = [
  { icon:"✓", text:"BTC/USD trade closed — +$287.50 profit", t:"2h ago", cls:"bg-accent-emerald/15 text-accent-emerald" },
  { icon:"→", text:"ETH/USD trade opened — Long position", t:"4h ago", cls:"bg-accent-cyan/15 text-accent-cyan" },
  { icon:"↕", text:"Trading amount updated to $50,000", t:"1d ago", cls:"bg-accent-violet/15 text-accent-violet" },
  { icon:"+", text:"Balance topped up — +$25,000", t:"2d ago", cls:"bg-blue-500/15 text-blue-400" },
  { icon:"✓", text:"Gold trade closed — +$142.00 profit", t:"3d ago", cls:"bg-accent-emerald/15 text-accent-emerald" },
];

function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`bg-bg-secondary/60 border border-border-default rounded-xl ${className}`}>{children}</div>;
}

export default function Dashboard() {
  const [showTopUp, setShowTopUp] = useState(false);
  const [topUpAmt, setTopUpAmt] = useState("");
  const [tradingAmt, setTradingAmt] = useState(DATA.tradingAmount);
  const [newsIdx, setNewsIdx] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const d = DATA;

  useEffect(() => { setTimeout(() => setLoaded(true), 100); }, []);
  useEffect(() => { const iv = setInterval(() => setNewsIdx(i => (i+1) % NEWS.length), 5000); return () => clearInterval(iv); }, []);

  return (
    <AppShell>
      <div className="space-y-4 sm:space-y-5 max-w-[1400px]">
        {/* Hero */}
        <Card className={`p-5 sm:p-7 relative overflow-hidden transition-all duration-700 ${loaded ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'}`}>
          <div className="absolute top-[-60px] right-[-20px] w-48 h-48 bg-accent-violet/5 rounded-full blur-[40px]" />
          <div className="relative flex flex-col sm:flex-row sm:justify-between sm:items-start gap-4">
            <div>
              <div className="text-[10px] text-text-muted uppercase tracking-widest font-semibold mb-1">Total Balance</div>
              <div className="text-3xl sm:text-4xl lg:text-[42px] font-black tracking-tight tabular-nums">{fm(d.balance)}</div>
              <div className="mt-1.5 text-sm text-text-secondary">Available: <span className="text-text-primary font-semibold">{fm(d.available)}</span></div>
            </div>
            <div className="sm:text-right">
              <div className="flex items-center gap-2 sm:justify-end">
                <span className="w-2 h-2 rounded-full bg-accent-emerald animate-pulse" />
                <span className="text-sm font-semibold text-accent-emerald">Trading Active</span>
              </div>
              <div className="mt-2">
                <span className="text-xl sm:text-2xl font-bold text-accent-emerald tabular-nums">+{fm(d.todayPnl)}</span>
                <span className="text-sm text-accent-emerald/50 ml-1">{fp(d.todayPnlPct)}</span>
              </div>
              <div className="text-[10px] text-text-muted mt-0.5">Today&apos;s profit</div>
            </div>
          </div>
        </Card>

        {/* Equity Chart */}
        <Card className={`p-4 transition-all duration-700 delay-100 ${loaded ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'}`}>
          <div className="flex justify-between items-center mb-2">
            <div className="text-xs font-bold">Portfolio Equity — Today</div>
            <div className="text-xs text-text-muted tabular-nums">24h</div>
          </div>
          <div className="h-[120px] sm:h-[160px]">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={EQUITY}>
                <defs><linearGradient id="dashGrad" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#6c5ce7" stopOpacity={0.25} /><stop offset="100%" stopColor="#6c5ce7" stopOpacity={0} /></linearGradient></defs>
                <XAxis dataKey="t" tick={{ fontSize:9, fill:'#555570' }} axisLine={false} tickLine={false} interval={5} />
                <Tooltip contentStyle={{ background:'#1C1C35', border:'1px solid #2A2A4A', borderRadius:8, fontSize:12 }} labelStyle={{ color:'#8888AA' }} formatter={(v: number) => [`$${v.toFixed(0)}`, 'Equity']} />
                <Area type="monotone" dataKey="v" stroke="#6c5ce7" strokeWidth={2} fill="url(#dashGrad)" animationDuration={1500} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Card>

        {/* Top-Up + Trading Amount */}
        <div className={`grid grid-cols-1 md:grid-cols-2 gap-4 transition-all duration-700 delay-200 ${loaded ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'}`}>
          <Card className="p-5">
            <div className="text-[10px] text-text-muted uppercase tracking-widest font-semibold mb-4">Add Funds</div>
            {!showTopUp ? (
              <button onClick={() => setShowTopUp(true)} className="w-full py-3 rounded-xl bg-gradient-to-r from-accent-violet to-[#4c3ad1] text-white font-bold text-sm shadow-lg shadow-accent-violet/20 hover:brightness-110 active:scale-[0.98] transition-all">Add Virtual Funds</button>
            ) : (
              <div className="space-y-3">
                <input type="number" value={topUpAmt} onChange={e => setTopUpAmt(e.target.value)} placeholder="Enter amount" className="w-full px-4 py-3 rounded-xl bg-bg-primary border border-border-default text-white text-lg font-semibold placeholder:text-text-muted focus:outline-none focus:border-accent-violet/40" />
                <div className="flex gap-2">
                  <button onClick={() => { setShowTopUp(false); setTopUpAmt(""); }} className="flex-1 py-2.5 rounded-xl border border-border-default text-text-secondary text-sm hover:bg-bg-tertiary">Cancel</button>
                  <button className="flex-1 py-2.5 rounded-xl bg-accent-violet text-white text-sm font-bold hover:brightness-110">Confirm</button>
                </div>
              </div>
            )}
          </Card>
          <Card className="p-5">
            <div className="text-[10px] text-text-muted uppercase tracking-widest font-semibold mb-0.5">Trading Allocation</div>
            <div className="text-xs text-text-muted mb-3">How much should Bahamut trade for you?</div>
            <div className="relative mb-2">
              <span className="absolute left-4 top-1/2 -translate-y-1/2 text-text-muted text-lg font-bold">$</span>
              <input type="number" value={tradingAmt} onChange={e => setTradingAmt(Number(e.target.value))} className="w-full pl-9 pr-4 py-3 rounded-xl bg-bg-primary border border-border-default text-white text-xl font-bold focus:outline-none focus:border-accent-violet/40 tabular-nums" />
            </div>
            <input type="range" min={0} max={d.balance} step={100} value={tradingAmt} onChange={e => setTradingAmt(Number(e.target.value))} className="w-full mb-2 accent-accent-violet" />
            <div className="flex gap-1.5 mb-3">
              {[100,500,1000,5000].map(v => (
                <button key={v} onClick={() => setTradingAmt(v)} className={`flex-1 py-1.5 rounded-lg text-[10px] sm:text-[11px] font-semibold border transition-all ${tradingAmt === v ? 'bg-accent-violet/15 text-accent-violet border-accent-violet/30' : 'bg-bg-primary text-text-muted border-border-default hover:text-text-secondary'}`}>{fm(v)}</button>
              ))}
              <button onClick={() => setTradingAmt(d.balance)} className="flex-1 py-1.5 rounded-lg text-[10px] sm:text-[11px] font-semibold border border-border-default bg-bg-primary text-text-muted">Max</button>
            </div>
            <button className="w-full py-2.5 rounded-xl bg-bg-tertiary border border-border-default text-white font-semibold text-sm hover:bg-bg-surface transition-all">Update Trading Amount</button>
            <div className="text-[9px] text-text-muted text-center mt-2">Bahamut will only trade with this amount.</div>
          </Card>
        </div>

        {/* Trust Strip */}
        <div className={`grid grid-cols-2 sm:grid-cols-4 gap-3 transition-all duration-700 delay-300 ${loaded ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'}`}>
          {[
            { l:"Win Rate", v:`${d.winRate}%`, c: d.winRate >= 60 ? "text-accent-emerald" : "text-accent-amber" },
            { l:"Trades Closed", v:d.tradesClosed, c:"text-text-primary" },
            { l:"Risk Level", v:d.riskLevel, c:"text-accent-emerald" },
            { l:"System", v:d.systemStatus, c:"text-accent-emerald" },
          ].map(s => (
            <Card key={s.l} className="p-3 sm:p-4 text-center">
              <div className={`text-lg sm:text-xl font-bold ${s.c}`}>{s.v}</div>
              <div className="text-[9px] text-text-muted uppercase tracking-wider font-semibold mt-0.5">{s.l}</div>
            </Card>
          ))}
        </div>

        {/* News + Risk */}
        <div className={`grid grid-cols-1 lg:grid-cols-[1fr_300px] gap-4 transition-all duration-700 delay-[400ms] ${loaded ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'}`}>
          <Card className="p-4">
            <div className="flex justify-between items-center mb-3">
              <div className="flex items-center gap-2"><span className="w-1.5 h-1.5 rounded-full bg-accent-emerald" /><span className="text-xs font-bold">News Feed</span></div>
              <div className="flex gap-1">{NEWS.map((_, i) => <button key={i} onClick={() => setNewsIdx(i)} className={`h-1.5 rounded-full transition-all ${i === newsIdx ? 'w-3.5 bg-accent-cyan' : 'w-1.5 bg-border-default'}`} />)}</div>
            </div>
            <div className="relative h-[60px] overflow-hidden">
              {NEWS.map((n, i) => (
                <div key={i} className={`absolute inset-0 transition-all duration-400 flex justify-between gap-4 ${i === newsIdx ? 'opacity-100 translate-x-0' : 'opacity-0 translate-x-6'}`}>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold text-text-primary truncate">{n.hl}</div>
                    <div className="text-xs text-text-muted mt-0.5 line-clamp-1">{n.sum}</div>
                    <div className="flex items-center gap-2 mt-1">
                      <span className="text-[10px] text-text-muted">{n.t}</span>
                      <span className={`text-[9px] font-bold px-2 py-0.5 rounded-full ${n.dir === "Bullish" ? "bg-accent-emerald/10 text-accent-emerald" : n.dir === "Bearish" ? "bg-accent-crimson/10 text-accent-crimson" : "bg-bg-tertiary text-text-muted"}`}>{n.dir}</span>
                    </div>
                  </div>
                  <div className="text-right shrink-0">
                    <div className={`text-lg font-bold tabular-nums ${n.impact >= 75 ? "text-accent-cyan" : "text-text-secondary"}`}>{n.impact}%</div>
                    <div className="text-[8px] text-text-muted uppercase">Impact</div>
                  </div>
                </div>
              ))}
            </div>
          </Card>
          <Card className="p-4">
            <div className="text-xs font-bold mb-3">Risk Status</div>
            {["Daily","Weekly","Total"].map((l, i) => { const v = [{c:0,m:3},{c:0,m:6},{c:0,m:15}][i]; return (
              <div key={l} className="mb-2.5">
                <div className="flex justify-between text-xs mb-1"><span className="text-text-muted">{l}</span><span className="text-text-secondary tabular-nums">{v.c.toFixed(1)}% / {v.m}.0%</span></div>
                <div className="h-1 bg-bg-tertiary rounded-full"><div className="h-full rounded-full bg-accent-emerald" style={{ width: `${(v.c/v.m)*100}%` }} /></div>
              </div>
            ); })}
            <div className="flex gap-4 mt-2">
              <div className="flex items-center gap-1.5"><span className="w-1.5 h-1.5 rounded-full bg-accent-emerald" /><span className="text-[10px] text-text-muted">Drawdown: OK</span></div>
              <div className="flex items-center gap-1.5"><span className="w-1.5 h-1.5 rounded-full bg-accent-emerald" /><span className="text-[10px] text-text-muted">Positions: OK</span></div>
            </div>
          </Card>
        </div>

        {/* Opportunities */}
        <div>
          <div className="text-[10px] text-text-muted uppercase tracking-widest font-semibold mb-2.5">Top Opportunities</div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {OPPS.map((o, i) => (
              <Card key={i} className="p-3.5">
                <div className="flex justify-between items-center mb-1.5">
                  <span className="text-sm font-bold">{o.asset}</span>
                  <span className={`px-2 py-0.5 text-[9px] font-bold rounded-full border ${o.status === "Ready" ? "bg-accent-emerald/10 text-accent-emerald border-accent-emerald/20" : o.status === "Close" ? "bg-accent-cyan/10 text-accent-cyan border-accent-cyan/20" : o.status === "Blocked" ? "bg-accent-crimson/10 text-accent-crimson/50 border-accent-crimson/15" : "bg-bg-tertiary text-text-muted border-border-default"}`}>{o.status}</span>
                </div>
                <div className="flex items-center gap-2 mb-2.5">
                  <span className={`text-xs font-bold ${o.dir === "Long" ? "text-accent-emerald" : o.dir === "Short" ? "text-accent-crimson" : "text-text-muted"}`}>{o.dir}</span>
                  <span className={`text-[10px] ${o.risk === "Low" ? "text-accent-emerald" : o.risk === "Medium" ? "text-accent-amber" : "text-accent-crimson"}`}>{o.risk} risk</span>
                </div>
                <div className="mb-1.5">
                  <div className="flex justify-between mb-1"><span className="text-[9px] text-text-muted">Chance</span><span className="text-xs font-bold text-text-secondary tabular-nums">{o.chance}%</span></div>
                  <div className="h-1 bg-bg-tertiary rounded-full"><div className={`h-full rounded-full ${o.chance >= 75 ? "bg-accent-emerald" : o.chance >= 50 ? "bg-accent-cyan" : "bg-border-default"}`} style={{ width: `${o.chance}%` }} /></div>
                </div>
                <div className="text-[10px] text-text-muted leading-relaxed">{o.desc}</div>
              </Card>
            ))}
          </div>
        </div>

        {/* Open Trades */}
        {TRADES.length > 0 && (
          <div>
            <div className="text-[10px] text-text-muted uppercase tracking-widest font-semibold mb-2.5">Open Trades</div>
            {TRADES.map((t, i) => (
              <Card key={i} className="p-4 sm:p-5">
                <div className="flex justify-between items-center mb-3">
                  <div className="flex items-center gap-2.5"><span className="text-base font-bold">{t.asset}</span><span className="px-2 py-0.5 text-[10px] font-bold rounded-full bg-accent-emerald/10 text-accent-emerald">{t.dir}</span></div>
                  <button className="px-3 py-1.5 rounded-lg border border-border-default text-xs text-text-muted hover:bg-bg-tertiary">Close Trade</button>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
                  {[{ l:"Entry", v:fm(t.entry), c:"text-text-primary" },{ l:"Live P&L", v:`+${fm(t.pnl)}`, c:"text-accent-emerald" },{ l:"Allocated", v:fm(t.alloc), c:"text-text-secondary" },{ l:"Stop / Target", v:`${fm(t.sl)} / ${fm(t.tp)}`, c:"text-text-muted" },{ l:"Time Open", v:t.time, c:"text-text-muted" }].map(c => (
                    <div key={c.l}><div className="text-[9px] text-text-muted uppercase mb-0.5">{c.l}</div><div className={`text-sm font-bold tabular-nums ${c.c}`}>{c.v}</div></div>
                  ))}
                </div>
              </Card>
            ))}
          </div>
        )}

        {/* Activity */}
        <Card className="p-4">
          <div className="text-[10px] text-text-muted uppercase tracking-widest font-semibold mb-3">Recent Activity</div>
          {ACTIVITY.map((a, i) => (
            <div key={i} className={`flex items-center gap-3 py-2.5 ${i < ACTIVITY.length-1 ? "border-b border-border-default/50" : ""}`}>
              <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold shrink-0 ${a.cls}`}>{a.icon}</div>
              <div className="flex-1 text-sm text-text-secondary">{a.text}</div>
              <span className="text-[10px] text-text-muted shrink-0">{a.t}</span>
            </div>
          ))}
        </Card>
      </div>
    </AppShell>
  );
}
