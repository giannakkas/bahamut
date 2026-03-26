"use client";

import { useState, useEffect, useRef } from "react";

// ═══════════════════════════════════════════════════
// BAHAMUT TRADER DASHBOARD — Consumer UI
// ═══════════════════════════════════════════════════

const API = process.env.NEXT_PUBLIC_API_URL || "https://api.bahamut.ai";

// ─── Formatting helpers ───
const fmtMoney = (n: number) => {
  if (n === undefined || n === null) return "$0.00";
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `$${(n / 1_000).toFixed(1)}K`;
  return `$${n.toFixed(2)}`;
};
const fmtPct = (n: number) => `${n >= 0 ? "+" : ""}${n.toFixed(1)}%`;
const fmtTime = (iso: string) => {
  if (!iso) return "";
  try { return new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }); } catch { return iso; }
};

// ─── Mock data (replace with real API) ───
const MOCK = {
  balance: 12450.00,
  available: 8200.00,
  todayPnl: 342.80,
  todayPnlPct: 2.75,
  tradingAmount: 5000,
  status: "active" as "active" | "paused" | "protected",
  winRate: 67,
  tradesClosed: 23,
  riskLevel: "Low" as "Low" | "Medium" | "High",
  systemStatus: "Online",
};

const MOCK_OPPORTUNITIES = [
  { asset: "BTC / USD", direction: "Long", status: "Ready", chance: 85, risk: "Medium", explanation: "Strong uptrend forming with high momentum" },
  { asset: "ETH / USD", direction: "Long", status: "Close", chance: 72, risk: "Medium", explanation: "Approaching key breakout level" },
  { asset: "EUR / USD", direction: "Short", status: "Watching", chance: 58, risk: "Low", explanation: "Dollar strength building gradually" },
  { asset: "Gold", direction: "Long", status: "Ready", chance: 81, risk: "Low", explanation: "Safe haven demand increasing" },
  { asset: "SPY", direction: "Watching", status: "Blocked", chance: 35, risk: "High", explanation: "Market closed — waiting for open" },
];

const MOCK_TRADES = [
  { asset: "BTC / USD", direction: "Long", entry: 67240, currentPrice: 68105, pnl: 412.50, pnlPct: 1.28, allocated: 2500, sl: 65800, tp: 70200, openedAt: "2026-03-26T08:15:00Z" },
];

const MOCK_NEWS = [
  { headline: "Fed Holds Rates Steady at March Meeting", summary: "Markets rally as the Federal Reserve maintains interest rates, signaling patience.", time: "2h ago", impact: 78, direction: "Bullish" },
  { headline: "Bitcoin Breaks $68K Resistance", summary: "BTC surges past key resistance with strong volume, targeting $72K next.", time: "3h ago", impact: 85, direction: "Bullish" },
  { headline: "EU Manufacturing Data Disappoints", summary: "Eurozone PMI falls below expectations, putting pressure on EUR.", time: "4h ago", impact: 62, direction: "Bearish" },
  { headline: "Oil Prices Rise on Supply Concerns", summary: "Brent crude climbs 2% as OPEC+ signals potential output cuts.", time: "5h ago", impact: 71, direction: "Bullish" },
  { headline: "Tech Earnings Season Begins Strong", summary: "Major tech companies beat estimates, boosting market sentiment.", time: "6h ago", impact: 74, direction: "Bullish" },
  { headline: "China GDP Growth Slows", summary: "Q1 growth misses target, raising concerns about global demand.", time: "8h ago", impact: 68, direction: "Bearish" },
  { headline: "Gold Hits New All-Time High", summary: "Safe haven demand pushes gold past $2,400 per ounce.", time: "10h ago", impact: 80, direction: "Bullish" },
  { headline: "Dollar Index Strengthens", summary: "DXY rises for third consecutive day on strong jobs data.", time: "12h ago", impact: 65, direction: "Neutral" },
  { headline: "Crypto Market Cap Surpasses $3T", summary: "Total crypto market capitalization reaches new milestone.", time: "14h ago", impact: 72, direction: "Bullish" },
  { headline: "Japanese Yen Hits Multi-Year Low", summary: "USD/JPY surges past 155 as BoJ maintains ultra-loose policy.", time: "16h ago", impact: 66, direction: "Bearish" },
];

const MOCK_ACTIVITY = [
  { type: "trade_closed", text: "BTC/USD trade closed — +$287.50 profit", time: "2h ago" },
  { type: "trade_opened", text: "ETH/USD trade opened — Long position", time: "4h ago" },
  { type: "amount_updated", text: "Trading amount updated to $5,000", time: "1d ago" },
  { type: "topup", text: "Balance topped up — +$2,000", time: "2d ago" },
  { type: "trade_closed", text: "Gold trade closed — +$142.00 profit", time: "3d ago" },
];

export default function TraderDashboard() {
  const [data, setData] = useState(MOCK);
  const [showTopUp, setShowTopUp] = useState(false);
  const [topUpAmount, setTopUpAmount] = useState("");
  const [tradingAmount, setTradingAmount] = useState(MOCK.tradingAmount);
  const [newsIdx, setNewsIdx] = useState(0);

  // Auto-rotate news
  useEffect(() => {
    const iv = setInterval(() => setNewsIdx(i => (i + 1) % MOCK_NEWS.length), 5000);
    return () => clearInterval(iv);
  }, []);

  const statusColors = { active: "text-emerald-400", paused: "text-amber-400", protected: "text-blue-400" };
  const statusLabels = { active: "Active", paused: "Paused", protected: "Protected" };
  const statusDots = { active: "bg-emerald-400", paused: "bg-amber-400", protected: "bg-blue-400" };

  return (
    <div className="min-h-screen bg-[#0a0e17] text-white font-[system-ui,-apple-system,sans-serif]">
      {/* ═══ NAV ═══ */}
      <nav className="sticky top-0 z-50 bg-[#0a0e17]/90 backdrop-blur-xl border-b border-white/[0.06]">
        <div className="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-400 to-blue-600 flex items-center justify-center text-sm font-black">B</div>
            <span className="text-sm font-bold tracking-tight">BAHAMUT</span>
          </div>
          <div className="flex gap-1">
            {["Dashboard", "Portfolio", "Trades", "News", "Settings"].map((item, i) => (
              <button key={item} className={`px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all ${i === 0 ? "bg-white/[0.08] text-white" : "text-white/40 hover:text-white/70 hover:bg-white/[0.03]"}`}>{item}</button>
            ))}
          </div>
        </div>
      </nav>

      <div className="max-w-6xl mx-auto px-4 py-6 space-y-6">

        {/* ═══ 1. HERO / ACCOUNT HEADER ═══ */}
        <div className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-[#0f1724] to-[#0d111d] border border-white/[0.06] p-6 sm:p-8">
          {/* Subtle glow */}
          <div className="absolute top-0 right-0 w-64 h-64 bg-cyan-500/[0.04] rounded-full blur-3xl -translate-y-1/2 translate-x-1/4" />

          <div className="relative grid grid-cols-1 sm:grid-cols-2 gap-6">
            <div>
              <div className="text-xs text-white/30 uppercase tracking-widest font-semibold mb-1">Total Balance</div>
              <div className="text-4xl sm:text-5xl font-black tracking-tight tabular-nums">{fmtMoney(data.balance)}</div>
              <div className="flex items-center gap-3 mt-2">
                <span className="text-sm text-white/40">Available: <span className="text-white/70 font-semibold">{fmtMoney(data.available)}</span></span>
              </div>
            </div>

            <div className="flex flex-col justify-center items-start sm:items-end gap-2">
              <div className="flex items-center gap-2">
                <span className={`w-2 h-2 rounded-full ${statusDots[data.status]} animate-pulse`} />
                <span className={`text-sm font-semibold ${statusColors[data.status]}`}>Trading {statusLabels[data.status]}</span>
              </div>
              <div className="flex items-baseline gap-1">
                <span className={`text-2xl font-bold tabular-nums ${data.todayPnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                  {data.todayPnl >= 0 ? "+" : ""}{fmtMoney(data.todayPnl)}
                </span>
                <span className={`text-sm ${data.todayPnl >= 0 ? "text-emerald-400/60" : "text-red-400/60"}`}>{fmtPct(data.todayPnlPct)}</span>
              </div>
              <span className="text-xs text-white/25">Today&apos;s profit</span>
            </div>
          </div>
        </div>

        {/* ═══ 2. TOP-UP + TRADING AMOUNT ═══ */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Top Up Card */}
          <div className="rounded-2xl bg-[#0f1420] border border-white/[0.06] p-6">
            <div className="text-xs text-white/30 uppercase tracking-widest font-semibold mb-4">Add Funds</div>
            {!showTopUp ? (
              <button onClick={() => setShowTopUp(true)} className="w-full py-3.5 rounded-xl bg-gradient-to-r from-cyan-500 to-blue-600 text-white font-bold text-sm hover:from-cyan-400 hover:to-blue-500 transition-all active:scale-[0.98] shadow-lg shadow-cyan-500/20">
                Top Up Balance
              </button>
            ) : (
              <div className="space-y-3 animate-in">
                <input type="number" value={topUpAmount} onChange={e => setTopUpAmount(e.target.value)} placeholder="Enter amount" className="w-full px-4 py-3 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-lg font-semibold placeholder:text-white/20 focus:outline-none focus:border-cyan-500/40 tabular-nums" />
                <div className="flex gap-2">
                  <button onClick={() => { setShowTopUp(false); setTopUpAmount(""); }} className="flex-1 py-2.5 rounded-xl border border-white/[0.08] text-white/50 text-sm font-medium hover:bg-white/[0.03]">Cancel</button>
                  <button className="flex-1 py-2.5 rounded-xl bg-gradient-to-r from-cyan-500 to-blue-600 text-white text-sm font-bold hover:from-cyan-400 hover:to-blue-500 active:scale-[0.98]">Confirm</button>
                </div>
              </div>
            )}
          </div>

          {/* Trading Amount Card */}
          <div className="rounded-2xl bg-[#0f1420] border border-white/[0.06] p-6">
            <div className="text-xs text-white/30 uppercase tracking-widest font-semibold mb-1">Trading Allocation</div>
            <div className="text-xs text-white/20 mb-4">How much should Bahamut trade for you?</div>

            <div className="relative mb-3">
              <span className="absolute left-4 top-1/2 -translate-y-1/2 text-white/30 text-lg font-bold">$</span>
              <input type="number" value={tradingAmount} onChange={e => setTradingAmount(Number(e.target.value))} className="w-full pl-9 pr-4 py-3 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-xl font-bold focus:outline-none focus:border-cyan-500/40 tabular-nums" />
            </div>

            <input type="range" min={0} max={data.balance} step={100} value={tradingAmount} onChange={e => setTradingAmount(Number(e.target.value))} className="w-full h-1.5 rounded-full appearance-none bg-white/[0.06] mb-3 accent-cyan-500 cursor-pointer" />

            <div className="flex gap-1.5 mb-4">
              {[100, 500, 1000, 5000].map(v => (
                <button key={v} onClick={() => setTradingAmount(v)} className={`flex-1 py-1.5 rounded-lg text-[11px] font-semibold border transition-all ${tradingAmount === v ? "bg-cyan-500/15 text-cyan-300 border-cyan-500/30" : "bg-white/[0.02] text-white/30 border-white/[0.06] hover:text-white/50"}`}>
                  {fmtMoney(v)}
                </button>
              ))}
              <button onClick={() => setTradingAmount(data.balance)} className={`flex-1 py-1.5 rounded-lg text-[11px] font-semibold border transition-all ${tradingAmount === data.balance ? "bg-cyan-500/15 text-cyan-300 border-cyan-500/30" : "bg-white/[0.02] text-white/30 border-white/[0.06] hover:text-white/50"}`}>
                Max
              </button>
            </div>

            <button className="w-full py-3 rounded-xl bg-white/[0.06] border border-white/[0.08] text-white font-semibold text-sm hover:bg-white/[0.10] transition-all active:scale-[0.98]">
              Update Trading Amount
            </button>
            <div className="text-[10px] text-white/20 text-center mt-2">Bahamut will only trade with this amount. You can change it anytime.</div>
          </div>
        </div>

        {/* ═══ 3. TRUST STRIP ═══ */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { label: "Win Rate", value: `${data.winRate}%`, color: data.winRate >= 60 ? "text-emerald-400" : data.winRate >= 45 ? "text-amber-400" : "text-red-400" },
            { label: "Trades Closed", value: data.tradesClosed, color: "text-white" },
            { label: "Risk Level", value: data.riskLevel, color: data.riskLevel === "Low" ? "text-emerald-400" : data.riskLevel === "Medium" ? "text-amber-400" : "text-red-400" },
            { label: "System", value: data.systemStatus, color: "text-emerald-400" },
          ].map(item => (
            <div key={item.label} className="rounded-xl bg-[#0f1420] border border-white/[0.06] p-4 text-center">
              <div className={`text-xl font-bold ${item.color}`}>{item.value}</div>
              <div className="text-[10px] text-white/25 uppercase tracking-wider font-semibold mt-0.5">{item.label}</div>
            </div>
          ))}
        </div>

        {/* ═══ 4. MARKET NEWS CAROUSEL ═══ */}
        <div className="rounded-2xl bg-[#0f1420] border border-white/[0.06] p-5">
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs text-white/30 uppercase tracking-widest font-semibold">Market News</span>
            <div className="flex gap-1">
              {MOCK_NEWS.slice(0, 10).map((_, i) => (
                <button key={i} onClick={() => setNewsIdx(i)} className={`w-1.5 h-1.5 rounded-full transition-all ${i === newsIdx ? "bg-cyan-400 w-4" : "bg-white/10 hover:bg-white/20"}`} />
              ))}
            </div>
          </div>
          <div className="relative overflow-hidden h-[72px]">
            {MOCK_NEWS.map((item, i) => (
              <div key={i} className={`absolute inset-0 transition-all duration-500 ${i === newsIdx ? "opacity-100 translate-x-0" : i < newsIdx ? "opacity-0 -translate-x-8" : "opacity-0 translate-x-8"}`}>
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold text-white truncate">{item.headline}</div>
                    <div className="text-xs text-white/35 mt-0.5 line-clamp-1">{item.summary}</div>
                    <div className="flex items-center gap-3 mt-1.5">
                      <span className="text-[10px] text-white/20">{item.time}</span>
                      <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${item.direction === "Bullish" ? "bg-emerald-500/10 text-emerald-400" : item.direction === "Bearish" ? "bg-red-500/10 text-red-400" : "bg-white/[0.05] text-white/40"}`}>
                        {item.direction}
                      </span>
                    </div>
                  </div>
                  <div className="text-right shrink-0">
                    <div className={`text-lg font-bold tabular-nums ${item.impact >= 75 ? "text-cyan-400" : item.impact >= 60 ? "text-white/70" : "text-white/40"}`}>{item.impact}%</div>
                    <div className="text-[9px] text-white/20 uppercase">Impact</div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* ═══ 5. TOP TRADE OPPORTUNITIES ═══ */}
        <div>
          <div className="text-xs text-white/30 uppercase tracking-widest font-semibold mb-3">Top Opportunities</div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {MOCK_OPPORTUNITIES.map((opp, i) => {
              const dirColor = opp.direction === "Long" ? "text-emerald-400" : opp.direction === "Short" ? "text-red-400" : "text-white/40";
              const statusColor = opp.status === "Ready" ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/25" : opp.status === "Close" ? "bg-cyan-500/15 text-cyan-300 border-cyan-500/25" : opp.status === "Blocked" ? "bg-red-500/10 text-red-300/50 border-red-500/15" : "bg-white/[0.04] text-white/30 border-white/[0.06]";
              const riskColor = opp.risk === "Low" ? "text-emerald-400" : opp.risk === "Medium" ? "text-amber-400" : "text-red-400";
              return (
                <div key={i} className="rounded-xl bg-[#0f1420] border border-white/[0.06] p-4 hover:border-white/[0.12] transition-all group">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-bold text-white">{opp.asset}</span>
                    <span className={`px-2 py-0.5 text-[9px] font-bold rounded-full border ${statusColor}`}>{opp.status}</span>
                  </div>
                  <div className="flex items-center gap-3 mb-3">
                    <span className={`text-xs font-bold ${dirColor}`}>{opp.direction}</span>
                    <span className="text-[10px] text-white/20">·</span>
                    <span className={`text-[10px] ${riskColor}`}>{opp.risk} risk</span>
                  </div>
                  {/* Chance bar */}
                  <div className="mb-2">
                    <div className="flex justify-between items-center mb-1">
                      <span className="text-[10px] text-white/25">Chance to trade</span>
                      <span className="text-xs font-bold text-white/60 tabular-nums">{opp.chance}%</span>
                    </div>
                    <div className="h-1.5 bg-white/[0.04] rounded-full overflow-hidden">
                      <div className={`h-full rounded-full transition-all ${opp.chance >= 75 ? "bg-emerald-400" : opp.chance >= 50 ? "bg-cyan-400" : "bg-white/15"}`} style={{ width: `${opp.chance}%` }} />
                    </div>
                  </div>
                  <div className="text-[11px] text-white/25 leading-relaxed">{opp.explanation}</div>
                </div>
              );
            })}
          </div>
        </div>

        {/* ═══ 6. OPEN TRADES ═══ */}
        {MOCK_TRADES.length > 0 && (
          <div>
            <div className="text-xs text-white/30 uppercase tracking-widest font-semibold mb-3">Open Trades</div>
            <div className="space-y-3">
              {MOCK_TRADES.map((trade, i) => (
                <div key={i} className="rounded-xl bg-[#0f1420] border border-white/[0.06] p-5">
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-3">
                      <span className="text-base font-bold text-white">{trade.asset}</span>
                      <span className={`px-2 py-0.5 text-[10px] font-bold rounded-full ${trade.direction === "Long" ? "bg-emerald-500/15 text-emerald-300" : "bg-red-500/15 text-red-300"}`}>{trade.direction}</span>
                    </div>
                    <button className="px-3 py-1.5 rounded-lg border border-white/[0.08] text-xs text-white/40 hover:text-white/70 hover:bg-white/[0.03] transition-all">Close Trade</button>
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-5 gap-4">
                    <div>
                      <div className="text-[10px] text-white/25 uppercase mb-0.5">Entry</div>
                      <div className="text-sm font-bold text-white tabular-nums">{fmtMoney(trade.entry)}</div>
                    </div>
                    <div>
                      <div className="text-[10px] text-white/25 uppercase mb-0.5">Live P&L</div>
                      <div className={`text-sm font-bold tabular-nums ${trade.pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                        {trade.pnl >= 0 ? "+" : ""}{fmtMoney(trade.pnl)} <span className="text-xs opacity-60">({fmtPct(trade.pnlPct)})</span>
                      </div>
                    </div>
                    <div>
                      <div className="text-[10px] text-white/25 uppercase mb-0.5">Allocated</div>
                      <div className="text-sm font-semibold text-white/70 tabular-nums">{fmtMoney(trade.allocated)}</div>
                    </div>
                    <div>
                      <div className="text-[10px] text-white/25 uppercase mb-0.5">Stop / Target</div>
                      <div className="text-sm text-white/50 tabular-nums">
                        <span className="text-red-400/60">{fmtMoney(trade.sl)}</span> / <span className="text-emerald-400/60">{fmtMoney(trade.tp)}</span>
                      </div>
                    </div>
                    <div>
                      <div className="text-[10px] text-white/25 uppercase mb-0.5">Open Since</div>
                      <div className="text-sm text-white/50">{fmtTime(trade.openedAt)}</div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ═══ 7. RECENT ACTIVITY ═══ */}
        <div className="rounded-2xl bg-[#0f1420] border border-white/[0.06] p-5">
          <div className="text-xs text-white/30 uppercase tracking-widest font-semibold mb-3">Recent Activity</div>
          <div className="space-y-0">
            {MOCK_ACTIVITY.map((item, i) => {
              const icons: Record<string, string> = { trade_closed: "✓", trade_opened: "→", topup: "+", amount_updated: "↕" };
              const colors: Record<string, string> = { trade_closed: "bg-emerald-500/15 text-emerald-400", trade_opened: "bg-cyan-500/15 text-cyan-400", topup: "bg-blue-500/15 text-blue-400", amount_updated: "bg-white/[0.06] text-white/40" };
              return (
                <div key={i} className="flex items-center gap-3 py-2.5 border-b border-white/[0.03] last:border-0">
                  <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold ${colors[item.type]}`}>{icons[item.type]}</div>
                  <div className="flex-1 text-sm text-white/60">{item.text}</div>
                  <span className="text-[10px] text-white/20 shrink-0">{item.time}</span>
                </div>
              );
            })}
          </div>
        </div>

        {/* Footer */}
        <div className="text-center py-6 text-[10px] text-white/15">
          Bahamut.AI — Trade · Analyse · Conquer
        </div>
      </div>
    </div>
  );
}
