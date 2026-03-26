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


function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`bg-bg-secondary/60 border border-border-default rounded-xl ${className}`}>{children}</div>;
}

// ─── Demo state helpers ───
const DEMO_KEY = 'bahamut_demo_state';
const ACTIVITY_KEY = 'bahamut_demo_activity';

function loadDemoState() {
  if (typeof window === 'undefined') return null;
  try { const raw = localStorage.getItem(DEMO_KEY); return raw ? JSON.parse(raw) : null; } catch { return null; }
}
function saveDemoState(state: any) {
  if (typeof window !== 'undefined') localStorage.setItem(DEMO_KEY, JSON.stringify(state));
}
function loadActivity(): any[] {
  if (typeof window === 'undefined') return [];
  try { const raw = localStorage.getItem(ACTIVITY_KEY); return raw ? JSON.parse(raw) : []; } catch { return []; }
}
function saveActivity(items: any[]) {
  if (typeof window !== 'undefined') localStorage.setItem(ACTIVITY_KEY, JSON.stringify(items.slice(0, 20)));
}
function addActivity(items: any[], type: string, text: string) {
  const now = new Date();
  const timeStr = now.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
  return [{ icon: type === 'topup' ? '+' : type === 'amount' ? '↕' : '✓', text, t: timeStr, cls: type === 'topup' ? 'bg-blue-500/15 text-blue-400' : type === 'amount' ? 'bg-accent-violet/15 text-accent-violet' : 'bg-accent-emerald/15 text-accent-emerald' }, ...items].slice(0, 20);
}

const DEFAULT_ACTIVITY = [
  { icon: "✓", text: "Demo account created with $100,000", t: "Now", cls: "bg-accent-emerald/15 text-accent-emerald" },
];

export default function Dashboard() {
  const [showTopUp, setShowTopUp] = useState(false);
  const [topUpAmt, setTopUpAmt] = useState("");
  const [newsIdx, setNewsIdx] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  // Demo state — persisted in localStorage
  const [balance, setBalance] = useState(DATA.balance);
  const [available, setAvailable] = useState(DATA.available);
  const [tradingAmt, setTradingAmt] = useState(DATA.tradingAmount);
  const [activity, setActivity] = useState<any[]>(DEFAULT_ACTIVITY);

  // Load persisted demo state on mount
  useEffect(() => {
    const saved = loadDemoState();
    if (saved) {
      setBalance(saved.balance ?? DATA.balance);
      setAvailable(saved.available ?? DATA.available);
      setTradingAmt(saved.tradingAmt ?? DATA.tradingAmount);
    }
    const savedAct = loadActivity();
    if (savedAct.length > 0) setActivity(savedAct);
    setTimeout(() => setLoaded(true), 100);
  }, []);

  // Persist on change
  useEffect(() => { saveDemoState({ balance, available, tradingAmt }); }, [balance, available, tradingAmt]);
  useEffect(() => { saveActivity(activity); }, [activity]);
  useEffect(() => { const iv = setInterval(() => setNewsIdx(i => (i+1) % NEWS.length), 5000); return () => clearInterval(iv); }, []);

  // Toast auto-dismiss
  useEffect(() => { if (toast) { const t = setTimeout(() => setToast(null), 3000); return () => clearTimeout(t); } }, [toast]);

  const handleTopUp = () => {
    const amt = parseFloat(topUpAmt);
    if (!amt || amt <= 0 || isNaN(amt)) { setToast("Enter a valid amount"); return; }
    setBalance(b => b + amt);
    setAvailable(a => a + amt);
    const newAct = addActivity(activity, 'topup', `Balance topped up — +${fm(amt)}`);
    setActivity(newAct);
    setShowTopUp(false);
    setTopUpAmt("");
    setToast(`+${fm(amt)} added to your balance!`);
  };

  const handleUpdateAllocation = () => {
    if (tradingAmt > balance) { setToast("Trading amount can't exceed balance"); return; }
    if (tradingAmt < 0) { setToast("Amount must be positive"); return; }
    const newAvail = balance - tradingAmt;
    setAvailable(newAvail);
    const newAct = addActivity(activity, 'amount', `Trading amount updated to ${fm(tradingAmt)}`);
    setActivity(newAct);
    setToast(`Trading allocation set to ${fm(tradingAmt)}`);
  };

  const d = { ...DATA, balance, available, tradingAmount: tradingAmt };

  return (
    <AppShell>
      <div className="space-y-3 w-full">
        {/* ═══ ROW 1: Hero + Equity Chart side by side ═══ */}
        <div className={`grid grid-cols-1 lg:grid-cols-[380px_1fr] 2xl:grid-cols-[420px_1fr] gap-3 transition-all duration-700 ${loaded ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'}`}>
          <Card className="p-4 relative overflow-hidden">
            <div className="absolute top-[-40px] right-[-20px] w-32 h-32 bg-accent-violet/5 rounded-full blur-[30px]" />
            <div className="relative">
              <div className="text-[9px] text-text-muted uppercase tracking-widest font-semibold mb-0.5">Total Balance</div>
              <div className="text-3xl sm:text-4xl font-black tracking-tight tabular-nums">{fm(balance)}</div>
              <div className="mt-1 text-xs text-text-secondary">Available: <span className="text-text-primary font-semibold">{fm(available)}</span></div>
              <div className="flex items-center justify-between mt-3 pt-3 border-t border-border-default/40">
                <div className="flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-accent-emerald animate-pulse" />
                  <span className="text-xs font-semibold text-accent-emerald">Trading Active</span>
                </div>
                <div className="text-right">
                  <span className="text-lg font-bold text-accent-emerald tabular-nums">+{fm(d.todayPnl)}</span>
                  <span className="text-xs text-accent-emerald/50 ml-1">{fp(d.todayPnlPct)}</span>
                </div>
              </div>
            </div>
          </Card>
          <Card className="p-3">
            <div className="flex justify-between items-center mb-1">
              <div className="text-[10px] font-bold text-text-secondary">Portfolio Equity — Today</div>
              <div className="text-[10px] text-text-muted tabular-nums">24h</div>
            </div>
            <div className="h-[100px] sm:h-[120px] 2xl:h-[130px]">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={EQUITY}>
                  <defs><linearGradient id="dashGrad" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#6c5ce7" stopOpacity={0.25} /><stop offset="100%" stopColor="#6c5ce7" stopOpacity={0} /></linearGradient></defs>
                  <XAxis dataKey="t" tick={{ fontSize:9, fill:'#555570' }} axisLine={false} tickLine={false} interval={5} />
                  <Tooltip contentStyle={{ background:'#1C1C35', border:'1px solid #2A2A4A', borderRadius:8, fontSize:11 }} labelStyle={{ color:'#8888AA' }} formatter={(v: number) => [`$${v.toFixed(0)}`, 'Equity']} />
                  <Area type="monotone" dataKey="v" stroke="#6c5ce7" strokeWidth={2} fill="url(#dashGrad)" animationDuration={1500} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </Card>
        </div>

        {/* ═══ ROW 2: Add Funds + Allocation + Trust Strip ═══ */}
        <div className={`grid grid-cols-1 lg:grid-cols-[1fr_1fr_auto] gap-3 transition-all duration-700 delay-100 ${loaded ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'}`}>
          <Card className="p-3.5">
            <div className="text-[9px] text-text-muted uppercase tracking-widest font-semibold mb-2">Add Funds</div>
            {!showTopUp ? (
              <button onClick={() => setShowTopUp(true)} className="w-full py-2.5 rounded-lg bg-gradient-to-r from-accent-violet to-[#4c3ad1] text-white font-bold text-xs shadow-lg shadow-accent-violet/20 hover:brightness-110 active:scale-[0.98] transition-all">Add Virtual Funds</button>
            ) : (
              <div className="space-y-2">
                <input type="number" value={topUpAmt} onChange={e => setTopUpAmt(e.target.value)} placeholder="Enter amount" className="w-full px-3 py-2 rounded-lg bg-bg-primary border border-border-default text-white text-base font-semibold placeholder:text-text-muted focus:outline-none focus:border-accent-violet/40" />
                <div className="flex gap-2">
                  <button onClick={() => { setShowTopUp(false); setTopUpAmt(""); }} className="flex-1 py-2 rounded-lg border border-border-default text-text-secondary text-xs hover:bg-bg-tertiary">Cancel</button>
                  <button onClick={handleTopUp} className="flex-1 py-2 rounded-lg bg-accent-violet text-white text-xs font-bold hover:brightness-110 active:scale-[0.97] transition-all">Confirm</button>
                </div>
              </div>
            )}
          </Card>
          <Card className="p-3.5">
            <div className="flex items-center justify-between mb-1.5">
              <div className="text-[9px] text-text-muted uppercase tracking-widest font-semibold">Trading Allocation</div>
              <div className="text-[9px] text-text-muted">How much to trade?</div>
            </div>
            <div className="relative mb-1.5">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted text-sm font-bold">$</span>
              <input type="number" value={tradingAmt} onChange={e => setTradingAmt(Number(e.target.value))} className="w-full pl-7 pr-3 py-2 rounded-lg bg-bg-primary border border-border-default text-white text-lg font-bold focus:outline-none focus:border-accent-violet/40 tabular-nums" />
            </div>
            <input type="range" min={0} max={balance} step={100} value={tradingAmt} onChange={e => setTradingAmt(Number(e.target.value))} className="w-full mb-1.5 accent-accent-violet h-1" />
            <div className="flex gap-1 mb-2">
              {[100,500,1000,5000].map(v => (
                <button key={v} onClick={() => setTradingAmt(v)} className={`flex-1 py-1 rounded text-[9px] font-semibold border transition-all ${tradingAmt === v ? 'bg-accent-violet/15 text-accent-violet border-accent-violet/30' : 'bg-bg-primary text-text-muted border-border-default'}`}>{fm(v)}</button>
              ))}
              <button onClick={() => setTradingAmt(balance)} className="flex-1 py-1 rounded text-[9px] font-semibold border border-border-default bg-bg-primary text-text-muted">Max</button>
            </div>
            <button onClick={handleUpdateAllocation} className="w-full py-2 rounded-lg bg-bg-tertiary border border-border-default text-white font-semibold text-xs hover:bg-bg-surface active:scale-[0.98] transition-all">Update Trading Amount</button>
          </Card>
          {/* Trust strip — vertical on lg, horizontal otherwise */}
          <div className="grid grid-cols-4 lg:grid-cols-2 lg:w-[200px] 2xl:w-[220px] gap-2">
            {[
              { l:"Win Rate", v:`${d.winRate}%`, c: d.winRate >= 60 ? "text-accent-emerald" : "text-accent-amber" },
              { l:"Trades", v:d.tradesClosed, c:"text-text-primary" },
              { l:"Risk", v:d.riskLevel, c:"text-accent-emerald" },
              { l:"System", v:d.systemStatus, c:"text-accent-emerald" },
            ].map(s => (
              <Card key={s.l} className="p-2.5 text-center">
                <div className={`text-sm sm:text-base font-bold ${s.c}`}>{s.v}</div>
                <div className="text-[8px] text-text-muted uppercase tracking-wider font-semibold">{s.l}</div>
              </Card>
            ))}
          </div>
        </div>

        {/* ═══ ROW 3: News + Risk + Opportunities ═══ */}
        <div className={`grid grid-cols-1 lg:grid-cols-[1fr_240px] 2xl:grid-cols-[1fr_300px] gap-3 transition-all duration-700 delay-200 ${loaded ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'}`}>
          <Card className="p-3">
            <div className="flex justify-between items-center mb-2">
              <div className="flex items-center gap-1.5"><span className="w-1.5 h-1.5 rounded-full bg-accent-emerald" /><span className="text-[10px] font-bold">News Feed</span></div>
              <div className="flex gap-1">{NEWS.map((_, i) => <button key={i} onClick={() => setNewsIdx(i)} className={`h-1 rounded-full transition-all ${i === newsIdx ? 'w-3 bg-accent-cyan' : 'w-1 bg-border-default'}`} />)}</div>
            </div>
            <div className="relative h-[52px] overflow-hidden">
              {NEWS.map((n, i) => (
                <div key={i} className={`absolute inset-0 transition-all duration-400 flex justify-between gap-3 ${i === newsIdx ? 'opacity-100 translate-x-0' : 'opacity-0 translate-x-6'}`}>
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-semibold text-text-primary truncate">{n.hl}</div>
                    <div className="text-[10px] text-text-muted mt-0.5 line-clamp-1">{n.sum}</div>
                    <div className="flex items-center gap-2 mt-0.5">
                      <span className="text-[9px] text-text-muted">{n.t}</span>
                      <span className={`text-[8px] font-bold px-1.5 py-px rounded-full ${n.dir === "Bullish" ? "bg-accent-emerald/10 text-accent-emerald" : n.dir === "Bearish" ? "bg-accent-crimson/10 text-accent-crimson" : "bg-bg-tertiary text-text-muted"}`}>{n.dir}</span>
                    </div>
                  </div>
                  <div className="text-right shrink-0">
                    <div className={`text-base font-bold tabular-nums ${n.impact >= 75 ? "text-accent-cyan" : "text-text-secondary"}`}>{n.impact}%</div>
                    <div className="text-[7px] text-text-muted uppercase">Impact</div>
                  </div>
                </div>
              ))}
            </div>
          </Card>
          <Card className="p-3">
            <div className="text-[10px] font-bold mb-2">Risk Status</div>
            {["Daily","Weekly","Total"].map((l, i) => { const v = [{c:0,m:3},{c:0,m:6},{c:0,m:15}][i]; return (
              <div key={l} className="mb-1.5">
                <div className="flex justify-between text-[10px] mb-0.5"><span className="text-text-muted">{l}</span><span className="text-text-secondary tabular-nums">{v.c.toFixed(1)}% / {v.m}.0%</span></div>
                <div className="h-1 bg-bg-tertiary rounded-full"><div className="h-full rounded-full bg-accent-emerald" style={{ width: `${(v.c/v.m)*100}%` }} /></div>
              </div>
            ); })}
            <div className="flex gap-3 mt-1.5">
              <div className="flex items-center gap-1"><span className="w-1 h-1 rounded-full bg-accent-emerald" /><span className="text-[8px] text-text-muted">DD: OK</span></div>
              <div className="flex items-center gap-1"><span className="w-1 h-1 rounded-full bg-accent-emerald" /><span className="text-[8px] text-text-muted">Pos: OK</span></div>
            </div>
          </Card>
        </div>

        {/* ═══ ROW 4: Opportunities — compact cards ═══ */}
        <div>
          <div className="text-[9px] text-text-muted uppercase tracking-widest font-semibold mb-2">Top Opportunities</div>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-6 gap-2">
            {OPPS.map((o, i) => (
              <Card key={i} className="p-2.5">
                <div className="flex justify-between items-center mb-1">
                  <span className="text-xs font-bold">{o.asset}</span>
                  <span className={`px-1.5 py-px text-[8px] font-bold rounded-full border ${o.status === "Ready" ? "bg-accent-emerald/10 text-accent-emerald border-accent-emerald/20" : o.status === "Close" ? "bg-accent-cyan/10 text-accent-cyan border-accent-cyan/20" : o.status === "Blocked" ? "bg-accent-crimson/10 text-accent-crimson/50 border-accent-crimson/15" : "bg-bg-tertiary text-text-muted border-border-default"}`}>{o.status}</span>
                </div>
                <div className="flex items-center gap-1.5 mb-1.5">
                  <span className={`text-[10px] font-bold ${o.dir === "Long" ? "text-accent-emerald" : o.dir === "Short" ? "text-accent-crimson" : "text-text-muted"}`}>{o.dir}</span>
                  <span className={`text-[9px] ${o.risk === "Low" ? "text-accent-emerald" : o.risk === "Medium" ? "text-accent-amber" : "text-accent-crimson"}`}>{o.risk}</span>
                </div>
                <div className="flex justify-between items-center mb-1"><span className="text-[8px] text-text-muted">Chance</span><span className="text-[10px] font-bold text-text-secondary tabular-nums">{o.chance}%</span></div>
                <div className="h-0.5 bg-bg-tertiary rounded-full"><div className={`h-full rounded-full ${o.chance >= 75 ? "bg-accent-emerald" : o.chance >= 50 ? "bg-accent-cyan" : "bg-border-default"}`} style={{ width: `${o.chance}%` }} /></div>
                <div className="text-[9px] text-text-muted mt-1 leading-tight line-clamp-1">{o.desc}</div>
              </Card>
            ))}
          </div>
        </div>

        {/* ═══ ROW 5: Open Trades + Activity side by side ═══ */}
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_340px] 2xl:grid-cols-[1fr_400px] gap-3">
          {TRADES.length > 0 && (
            <div>
              <div className="text-[9px] text-text-muted uppercase tracking-widest font-semibold mb-2">Open Trades</div>
              {TRADES.map((t, i) => (
                <Card key={i} className="p-3">
                  <div className="flex justify-between items-center mb-2">
                    <div className="flex items-center gap-2"><span className="text-sm font-bold">{t.asset}</span><span className="px-1.5 py-px text-[9px] font-bold rounded-full bg-accent-emerald/10 text-accent-emerald">{t.dir}</span></div>
                    <button className="px-2.5 py-1 rounded-md border border-border-default text-[10px] text-text-muted hover:bg-bg-tertiary">Close</button>
                  </div>
                  <div className="grid grid-cols-5 gap-2">
                    {[{ l:"Entry", v:fm(t.entry), c:"text-text-primary" },{ l:"P&L", v:`+${fm(t.pnl)}`, c:"text-accent-emerald" },{ l:"Alloc", v:fm(t.alloc), c:"text-text-secondary" },{ l:"SL / TP", v:`${fm(t.sl)} / ${fm(t.tp)}`, c:"text-text-muted" },{ l:"Time", v:t.time, c:"text-text-muted" }].map(c => (
                      <div key={c.l}><div className="text-[8px] text-text-muted uppercase">{c.l}</div><div className={`text-xs font-bold tabular-nums ${c.c}`}>{c.v}</div></div>
                    ))}
                  </div>
                </Card>
              ))}
            </div>
          )}
          <div>
            <div className="text-[9px] text-text-muted uppercase tracking-widest font-semibold mb-2">Recent Activity</div>
            <Card className="p-3">
              {activity.map((a: any, i: number) => (
                <div key={i} className={`flex items-center gap-2.5 py-2 ${i < activity.length-1 ? "border-b border-border-default/40" : ""}`}>
                  <div className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0 ${a.cls}`}>{a.icon}</div>
                  <div className="flex-1 text-xs text-text-secondary">{a.text}</div>
                  <span className="text-[9px] text-text-muted shrink-0">{a.t}</span>
                </div>
              ))}
            </Card>
          </div>
        </div>
      </div>
      {/* Toast */}
      {toast && (
        <div className="fixed bottom-6 right-6 z-50 px-5 py-3 rounded-xl bg-accent-violet text-white text-sm font-semibold shadow-2xl shadow-accent-violet/30 animate-slide-in">
          {toast}
        </div>
      )}
    </AppShell>
  );
}
