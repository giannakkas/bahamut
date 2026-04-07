"use client";
import React, { useState, useEffect, useCallback, useRef } from "react";
import { apiBase } from "@/lib/utils";
import { useAdminSocket } from "@/providers/AdminSocketProvider";

const STRAT_NAMES: Record<string, string> = {
  v5_base: "S1 · EMA Trend", v5_tuned: "S2 · EMA Tuned",
  v9_breakout: "S3 · Breakout", v10_mean_reversion: "S4 · Mean Reversion",
};
const sn = (s: string) => STRAT_NAMES[s] || s;
const fm = (n: number) => `$${Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const fmS = (n: number) => `${n >= 0 ? "+" : "-"}${fm(n)}`;
const pnlC = (v: number) => v > 0.01 ? "text-green-400" : v < -0.01 ? "text-red-400" : "text-bah-muted";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-bah-card border border-bah-border rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-bah-border">
        <h2 className="text-xs font-bold text-bah-heading uppercase tracking-wider">{title}</h2>
      </div>
      <div className="p-4">{children}</div>
    </div>
  );
}

function fmtTime(iso: string) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" }) + " " +
           d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  } catch { return iso; }
}

export default function PlatformTradesPage({ platform, icon, label, color }: {
  platform: string; icon: string; label: string; color: string;
}) {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<"trades" | "orders" | "fills">("trades");
  const [sentiment, setSentiment] = useState<any>(null);
  const [leaderboard, setLeaderboard] = useState<any>(null);

  const load = useCallback(async () => {
    try {
      const t = localStorage.getItem("bahamut_admin_token");
      const h: Record<string, string> = t ? { Authorization: `Bearer ${t}` } : {};
      // Pull DIRECTLY from exchange API
      const r = await fetch(`${apiBase()}/execution/${platform}/live`, { headers: h });
      if (r.ok) setData(await r.json());
      // Fetch sentiment for both pages
      const sr = await fetch(`${apiBase()}/training/sentiment`, { headers: h });
      if (sr.ok) setSentiment(await sr.json());
      // Fetch asset leaderboard
      const lr = await fetch(`${apiBase()}/training/asset-leaderboard`, { headers: h });
      if (lr.ok) setLeaderboard(await lr.json());
    } catch {}
    setLoading(false);
  }, [platform]);

  const { lastEvent, status: wsStatus } = useAdminSocket();
  const lastEventRef = useRef(lastEvent);

  useEffect(() => { load(); const iv = setInterval(load, 60000); return () => clearInterval(iv); }, [load]);

  // Auto-refresh when a trade event comes through WebSocket
  useEffect(() => {
    if (lastEvent && lastEvent !== lastEventRef.current) {
      lastEventRef.current = lastEvent;
      const evt = (lastEvent as any)?.type || "";
      if (evt === "position_opened" || evt === "position_closed" || evt === "cycle_complete") {
        // Delay slightly to let cache invalidate
        setTimeout(load, 2000);
      }
    }
  }, [lastEvent, load]);

  if (loading) return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="text-center">
        <div className="inline-block w-8 h-8 border-2 border-bah-cyan/30 border-t-bah-cyan rounded-full animate-spin mb-4" />
        <div className="text-bah-muted text-xs">Connecting to {label}...</div>
      </div>
    </div>
  );

  if (!data || data.error) return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="text-center">
        <div className="text-bah-muted text-sm mb-2">{data?.error || `Cannot connect to ${label}`}</div>
        <div className="text-bah-muted text-[10px]">Check API keys in Railway environment variables</div>
      </div>
    </div>
  );

  const s = data.summary || {};
  const trades = data.trades || [];
  const byAsset = data.by_asset || {};
  const rawOrders = data.raw_orders || [];
  const rawFills = data.raw_fills || [];
  const account = data.account || {};
  const positions = data.positions || [];

  return (
    <div className="p-2 sm:p-4 max-w-[1440px] mx-auto space-y-4 pt-12 lg:pt-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {icon.startsWith("/") ? (
            <img src={icon} alt={label} className="w-7 h-7 rounded-md" />
          ) : (
            <span className="text-2xl">{icon}</span>
          )}
          <div>
            <h1 className="text-lg font-bold text-bah-heading">{label} Trades</h1>
            <p className="text-[10px] text-bah-muted">
              Live from {label} API · {s.total_trades || 0} round-trip trades · Last refresh: {new Date().toLocaleTimeString()}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${wsStatus === "connected" ? "bg-green-400 animate-pulse" : "bg-red-400"}`} />
          <span className={`text-[10px] font-bold ${wsStatus === "connected" ? "text-green-400" : "text-red-400"}`}>
            {wsStatus === "connected" ? "LIVE" : "OFFLINE"}
          </span>
        </div>
      </div>

      {/* Account Info */}
      {platform === "alpaca" && account && (
        <div className="bg-bah-card border border-bah-border rounded-xl p-3 flex flex-wrap gap-4 text-xs">
          <div><span className="text-bah-muted">Cash:</span> <span className="text-bah-heading font-bold">{fm(account.cash || 0)}</span></div>
          <div><span className="text-bah-muted">Equity:</span> <span className="text-bah-heading font-bold">{fm(account.equity || 0)}</span></div>
          <div><span className="text-bah-muted">Buying Power:</span> <span className="text-bah-heading font-bold">{fm(account.buying_power || 0)}</span></div>
        </div>
      )}
      {platform === "binance" && account && (
        <div className="bg-bah-card border border-bah-border rounded-xl p-3 flex flex-wrap gap-4 text-xs">
          <div><span className="text-bah-muted">Balance:</span> <span className="text-bah-heading font-bold">{fm(account.balance || 0)}</span></div>
          <div><span className="text-bah-muted">Equity:</span> <span className="text-bah-heading font-bold">{fm(account.equity || 0)}</span></div>
          <div><span className="text-bah-muted">Unrealized:</span> <span className={`font-bold ${pnlC(account.unrealized_pnl || 0)}`}>{fmS(account.unrealized_pnl || 0)}</span></div>
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-2">
        {[
          { l: "Realized PnL", v: fmS(s.total_pnl || 0), c: pnlC(s.total_pnl || 0) },
          { l: "Unrealized", v: fmS(s.unrealized_pnl || 0), c: pnlC(s.unrealized_pnl || 0) },
          { l: "Profit Factor", v: (s.profit_factor || 0).toFixed(2), c: (s.profit_factor || 0) >= 1 ? "text-green-400" : "text-red-400" },
          { l: platform === "binance" ? "Fills" : "Round Trips", v: String(s.total_fills || s.total_trades || 0), c: "text-bah-heading" },
          { l: "Open", v: String(positions.length + (data.training_positions || []).length), c: "text-bah-cyan" },
          { l: "Wins", v: String(s.wins || 0), c: "text-green-400" },
          { l: "Losses", v: String(s.losses || 0), c: "text-red-400" },
          { l: "Volume", v: fm(s.total_volume || 0), c: "text-bah-heading" },
        ].map((card, i) => (
          <div key={i} className="bg-bah-card border border-bah-border rounded-lg p-3 text-center">
            <div className={`text-sm sm:text-base font-bold ${card.c}`}>{card.v}</div>
            <div className="text-[8px] text-bah-muted uppercase tracking-wider mt-0.5">{card.l}</div>
          </div>
        ))}
      </div>

      {/* Best / Worst */}
      {(s.best_trade || s.worst_trade) && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {s.best_trade && (
            <div className="bg-green-500/10 border border-green-500/20 rounded-xl p-3 flex justify-between items-center">
              <div>
                <div className="text-[9px] text-green-400/60 uppercase font-bold">Best Trade</div>
                <div className="text-sm text-bah-heading font-bold">{s.best_trade.asset}</div>
              </div>
              <div className="text-lg font-bold text-green-400">{fmS(s.best_trade.pnl)}</div>
            </div>
          )}
          {s.worst_trade && (
            <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-3 flex justify-between items-center">
              <div>
                <div className="text-[9px] text-red-400/60 uppercase font-bold">Worst Trade</div>
                <div className="text-sm text-bah-heading font-bold">{s.worst_trade.asset}</div>
              </div>
              <div className="text-lg font-bold text-red-400">{fmS(s.worst_trade.pnl)}</div>
            </div>
          )}
        </div>
      )}

      {/* Open Positions (Exchange) */}
      {positions.length > 0 && (
        <Section title={`Open Positions — Exchange (${positions.length})`}>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead><tr className="border-b border-bah-border text-[8px] text-bah-muted uppercase tracking-wider text-left">
                <th className="py-2 pr-2">Asset</th><th className="py-2 pr-2">{platform === "binance" ? "Side" : "Qty"}</th>
                <th className="py-2 pr-2">Entry</th><th className="py-2 pr-2">{platform === "binance" ? "Mark" : "Current"}</th>
                <th className="py-2 pr-2">{platform === "binance" ? "Qty" : "Market Value"}</th><th className="py-2">Unrealized P&L</th>
              </tr></thead>
              <tbody>{positions.map((p: any, i: number) => {
                const unreal = p.unrealized_pnl ?? p.unrealized_pl ?? 0;
                return (
                  <tr key={i} className="border-b border-bah-border/30">
                    <td className="py-2 pr-2 text-bah-heading font-bold">{p.asset || p.symbol}</td>
                    <td className="py-2 pr-2"><span className={`font-bold ${(p.side || "LONG") === "LONG" ? "text-green-400" : "text-red-400"}`}>{p.side || (p.qty > 0 ? "LONG" : "SHORT")}</span></td>
                    <td className="py-2 pr-2 text-bah-text font-mono">{fm(p.entry_price || p.avg_entry_price || 0)}</td>
                    <td className="py-2 pr-2 text-bah-text font-mono">{fm(p.mark_price || p.current_price || 0)}</td>
                    <td className="py-2 pr-2 text-bah-muted">{p.qty || p.market_value || 0}</td>
                    <td className={`py-2 font-bold ${pnlC(unreal)}`}>{fmS(unreal)}</td>
                  </tr>
                );
              })}</tbody>
            </table>
          </div>
        </Section>
      )}

      {/* Open Crypto Positions (Training Engine) — Binance only */}
      {platform === "binance" && (data.training_positions || []).length > 0 && (
        <Section title={`Open Crypto Positions — Training Engine (${data.training_positions.length})`}>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead><tr className="border-b border-bah-border text-[8px] text-bah-muted uppercase tracking-wider text-left">
                <th className="py-2 pr-2">Asset</th><th className="py-2 pr-2">Strategy</th><th className="py-2 pr-2">Dir</th>
                <th className="py-2 pr-2">Entry</th><th className="py-2 pr-2">Current</th>
                <th className="py-2 pr-2">SL</th><th className="py-2 pr-2">TP</th>
                <th className="py-2 pr-2">Risk</th><th className="py-2 pr-2">Bars</th>
                <th className="py-2 pr-2">Platform</th><th className="py-2">P&L</th>
              </tr></thead>
              <tbody>{(data.training_positions || []).map((p: any, i: number) => (
                <tr key={i} className="border-b border-bah-border/30">
                  <td className="py-2 pr-2 text-bah-heading font-bold">{p.asset}</td>
                  <td className="py-2 pr-2 text-bah-muted">{sn(p.strategy)}</td>
                  <td className="py-2 pr-2"><span className={`font-bold ${p.direction === "LONG" ? "text-green-400" : "text-red-400"}`}>{p.direction}</span></td>
                  <td className="py-2 pr-2 text-bah-text font-mono">{fm(p.entry_price)}</td>
                  <td className="py-2 pr-2 text-bah-text font-mono">{fm(p.current_price)}</td>
                  <td className="py-2 pr-2 text-red-400/60 font-mono">{fm(p.stop_price)}</td>
                  <td className="py-2 pr-2 text-green-400/60 font-mono">{fm(p.tp_price)}</td>
                  <td className="py-2 pr-2 text-amber-400/70 font-mono">{fm(p.risk_amount)}</td>
                  <td className="py-2 pr-2 text-bah-muted">{p.bars_held}/{p.max_hold_bars}</td>
                  <td className="py-2 pr-2"><span className={`px-1.5 py-0.5 rounded text-[8px] font-bold ${
                    p.execution_platform === "binance_futures" ? "bg-yellow-500/15 text-yellow-400 border border-yellow-500/25" :
                    "bg-bah-border/50 text-bah-muted border border-bah-border"
                  }`}>{p.execution_platform === "binance_futures" ? "FUTURES" : "INTERNAL"}</span></td>
                  <td className={`py-2 font-bold ${pnlC(p.unrealized_pnl)}`}>{fmS(p.unrealized_pnl)}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </Section>
      )}

      {/* Asset Breakdown + Volume */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Section title="By Asset">
          <div className="space-y-1">
            {Object.entries(byAsset).map(([asset, st]: [string, any]) => {
              const pnl = st.realized_pnl ?? st.pnl ?? 0;
              return (
                <div key={asset} className="flex items-center justify-between py-1.5 border-b border-bah-border/30 last:border-0 text-xs">
                  <div className="flex items-center gap-2">
                    <span className="text-bah-heading font-bold w-[70px]">{asset}</span>
                    <span className="text-bah-muted">{st.trades}t</span>
                    {st.volume > 0 && <span className="text-bah-muted">{fm(st.volume)} vol</span>}
                  </div>
                  <span className={`font-bold ${pnlC(pnl)}`}>{fmS(pnl)}</span>
                </div>
              );
            })}
            {Object.keys(byAsset).length === 0 && <div className="text-bah-muted text-xs text-center py-4">No trades yet on {label}</div>}
          </div>
        </Section>

        {/* Raw data tabs */}
        <Section title="Exchange Data">
          <div className="flex gap-1 mb-3">
            {(["trades", "orders", "fills"] as const).map(t => (
              <button key={t} onClick={() => setTab(t)}
                className={`px-3 py-1 text-[10px] font-bold rounded-md capitalize ${tab === t ? "bg-bah-cyan/20 text-bah-cyan" : "text-bah-muted hover:text-bah-text"}`}>
                {t} ({t === "trades" ? trades.length : t === "orders" ? rawOrders.length : rawFills.length})
              </button>
            ))}
          </div>
          <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
            {tab === "trades" && (
              <table className="w-full text-[10px]">
                <thead><tr className="border-b border-bah-border text-[8px] text-bah-muted uppercase sticky top-0 bg-bah-card">
                  <th className="py-1.5 pr-2 text-left">Time</th><th className="py-1.5 pr-2 text-left">Asset</th>
                  <th className="py-1.5 pr-2 text-left">Side</th><th className="py-1.5 pr-2 text-left">Price</th>
                  <th className="py-1.5 pr-2 text-left">Qty</th><th className="py-1.5 pr-2 text-left">Value</th>
                  <th className="py-1.5 text-left">Realized PnL</th>
                </tr></thead>
                <tbody>{trades.map((t: any, i: number) => {
                  const ts = t.time ? new Date(t.time).toLocaleString("en-GB", { hour12: false, month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : fmtTime(t.exit_time);
                  const rpnl = t.realized_pnl ?? t.pnl ?? 0;
                  return (
                    <tr key={i} className="border-b border-bah-border/20">
                      <td className="py-1.5 pr-2 text-bah-muted">{ts}</td>
                      <td className="py-1.5 pr-2 text-bah-heading font-bold">{t.asset || t.symbol}</td>
                      <td className="py-1.5 pr-2"><span className={`font-bold ${t.side === "BUY" ? "text-green-400" : "text-red-400"}`}>{t.side || t.direction}</span></td>
                      <td className="py-1.5 pr-2 text-bah-text font-mono">{fm(t.price || t.entry_price || 0)}</td>
                      <td className="py-1.5 pr-2 text-bah-muted">{t.qty}</td>
                      <td className="py-1.5 pr-2 text-bah-muted">{fm(t.quote_qty || 0)}</td>
                      <td className={`py-1.5 font-bold ${pnlC(rpnl)}`}>{fmS(rpnl)}</td>
                    </tr>
                  );
                })}</tbody>
              </table>
            )}
            {tab === "orders" && (
              <table className="w-full text-[10px]">
                <thead><tr className="border-b border-bah-border text-[8px] text-bah-muted uppercase sticky top-0 bg-bah-card">
                  <th className="py-1.5 pr-2 text-left">Asset</th><th className="py-1.5 pr-2 text-left">Side</th>
                  <th className="py-1.5 pr-2 text-left">Qty</th><th className="py-1.5 pr-2 text-left">Price</th>
                  <th className="py-1.5 text-left">Status</th>
                </tr></thead>
                <tbody>{rawOrders.map((o: any, i: number) => (
                  <tr key={i} className="border-b border-bah-border/20">
                    <td className="py-1.5 pr-2 text-bah-heading font-bold">{o.asset || o.symbol}</td>
                    <td className={`py-1.5 pr-2 font-bold ${o.side === "BUY" || o.side === "buy" ? "text-green-400" : "text-red-400"}`}>{(o.side || "").toUpperCase()}</td>
                    <td className="py-1.5 pr-2 text-bah-text">{o.filled_qty || o.executed_qty || o.qty || o.orig_qty}</td>
                    <td className="py-1.5 pr-2 text-bah-text">{fm(o.filled_avg_price || o.price || 0)}</td>
                    <td className="py-1.5"><span className={`px-1.5 py-0.5 rounded text-[8px] font-bold ${o.status === "filled" || o.status === "FILLED" ? "bg-green-500/15 text-green-400" : "bg-bah-surface text-bah-muted"}`}>{(o.status || "").toUpperCase()}</span></td>
                  </tr>
                ))}</tbody>
              </table>
            )}
            {tab === "fills" && (
              <table className="w-full text-[10px]">
                <thead><tr className="border-b border-bah-border text-[8px] text-bah-muted uppercase sticky top-0 bg-bah-card">
                  <th className="py-1.5 pr-2 text-left">Time</th><th className="py-1.5 pr-2 text-left">Asset</th>
                  <th className="py-1.5 pr-2 text-left">Side</th><th className="py-1.5 pr-2 text-left">Price</th>
                  <th className="py-1.5 text-left">Qty</th>
                </tr></thead>
                <tbody>{rawFills.map((f: any, i: number) => (
                  <tr key={i} className="border-b border-bah-border/20">
                    <td className="py-1.5 pr-2 text-bah-muted">{fmtTime(f.transaction_time || (f.time ? new Date(f.time).toISOString() : ""))}</td>
                    <td className="py-1.5 pr-2 text-bah-heading font-bold">{f.asset || f.symbol}</td>
                    <td className={`py-1.5 pr-2 font-bold ${f.side === "BUY" || f.side === "buy" ? "text-green-400" : "text-red-400"}`}>{(f.side || "").toUpperCase()}</td>
                    <td className="py-1.5 pr-2 text-bah-text">{fm(f.price || 0)}</td>
                    <td className="py-1.5 text-bah-text">{f.qty}</td>
                  </tr>
                ))}</tbody>
              </table>
            )}
          </div>
        </Section>
      </div>

      {/* Sentiment — only on Binance page */}
      {platform === "binance" && sentiment && (
        <div className="space-y-4">
          {/* Fear & Greed Index */}
          {sentiment.fear_greed && (
            <Section title="Fear & Greed Index">
              <div className="flex items-center gap-6">
                {/* Score circle */}
                <div className="relative w-24 h-24 shrink-0">
                  <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90">
                    <circle cx="50" cy="50" r="42" fill="none" stroke="currentColor" strokeWidth="8" className="text-bah-border" />
                    <circle cx="50" cy="50" r="42" fill="none" strokeWidth="8"
                      strokeDasharray={`${(sentiment.fear_greed.value / 100) * 264} 264`}
                      strokeLinecap="round"
                      className={
                        sentiment.fear_greed.value <= 24 ? "text-red-500" :
                        sentiment.fear_greed.value <= 39 ? "text-orange-500" :
                        sentiment.fear_greed.value <= 60 ? "text-yellow-500" :
                        sentiment.fear_greed.value <= 74 ? "text-green-400" :
                        "text-green-500"
                      } />
                  </svg>
                  <div className="absolute inset-0 flex items-center justify-center">
                    <span className={`text-2xl font-black ${
                      sentiment.fear_greed.value <= 24 ? "text-red-500" :
                      sentiment.fear_greed.value <= 39 ? "text-orange-500" :
                      sentiment.fear_greed.value <= 60 ? "text-yellow-500" :
                      "text-green-400"
                    }`}>{sentiment.fear_greed.value}</span>
                  </div>
                </div>
                <div className="flex-1">
                  <div className={`text-lg font-bold ${
                    sentiment.fear_greed.value <= 24 ? "text-red-500" :
                    sentiment.fear_greed.value <= 39 ? "text-orange-500" :
                    sentiment.fear_greed.value <= 60 ? "text-yellow-500" :
                    "text-green-400"
                  }`}>{sentiment.fear_greed.classification}</div>
                  <div className="text-[10px] text-bah-muted mt-1">
                    Source: alternative.me · Free · No API key
                  </div>
                  <div className="mt-2">
                    {sentiment.fear_greed.should_block_longs ? (
                      <span className="px-3 py-1 rounded-lg text-[10px] font-bold bg-red-500/20 text-red-400 border border-red-500/30">
                        🛑 ALL CRYPTO LONGS BLOCKED
                      </span>
                    ) : (
                      <span className="px-3 py-1 rounded-lg text-[10px] font-bold bg-green-500/20 text-green-400 border border-green-500/30">
                        ✅ CRYPTO LONGS ALLOWED
                      </span>
                    )}
                  </div>
                  <div className="text-[9px] text-bah-muted mt-2">
                    0-24: Extreme Fear (block) · 25-39: Fear (block) · 40-60: Neutral · 61-74: Greed · 75-100: Extreme Greed
                  </div>
                </div>
              </div>
            </Section>
          )}

          {/* CryptoPanic per-asset sentiment */}
          {sentiment.cryptopanic && sentiment.cryptopanic.assets && Object.keys(sentiment.cryptopanic.assets).length > 0 && (
            <Section title="CryptoPanic — Per-Asset Sentiment">
              <div className="flex items-center gap-3 mb-3">
                <span className={`text-sm font-bold ${
                  sentiment.cryptopanic.overall === "extreme_fear" ? "text-red-500" :
                  sentiment.cryptopanic.overall === "bearish" ? "text-orange-400" :
                  sentiment.cryptopanic.overall === "bullish" ? "text-green-400" :
                  sentiment.cryptopanic.overall === "extreme_greed" ? "text-green-500" :
                  "text-yellow-400"
                }`}>
                  Market: {sentiment.cryptopanic.overall?.toUpperCase()} (score: {sentiment.cryptopanic.score?.toFixed(2)})
                </span>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
                {Object.entries(sentiment.cryptopanic.assets).map(([code, s]: [string, any]) => (
                  <div key={code} className={`border rounded-lg p-2.5 text-center ${
                    s.mood === "bearish" ? "bg-red-500/10 border-red-500/20" :
                    s.mood === "bullish" ? "bg-green-500/10 border-green-500/20" :
                    "bg-bah-surface border-bah-border"
                  }`}>
                    <div className="text-xs font-bold text-bah-heading">{code}</div>
                    <div className={`text-lg font-black mt-0.5 ${
                      s.score > 0.15 ? "text-green-400" :
                      s.score < -0.15 ? "text-red-400" :
                      "text-yellow-400"
                    }`}>{s.score > 0 ? "+" : ""}{(s.score * 100).toFixed(0)}%</div>
                    <div className="text-[8px] text-bah-muted mt-0.5">
                      {s.bullish}↑ {s.bearish}↓ · {s.posts}p
                    </div>
                    <div className={`text-[8px] font-bold mt-0.5 ${
                      s.mood === "bearish" ? "text-red-400" :
                      s.mood === "bullish" ? "text-green-400" :
                      "text-yellow-400"
                    }`}>{s.mood.toUpperCase()}</div>
                  </div>
                ))}
              </div>
              <div className="text-[9px] text-bah-muted mt-2">
                Source: CryptoPanic API · Cached 30 min · Per-asset bearish score {"<"} -0.4 blocks that asset
              </div>
            </Section>
          )}

          {/* Combined action */}
          {(() => {
            const action = platform === "binance" ? sentiment.combined_crypto_action : sentiment.combined_stock_action;
            return action && (
              <div className={`rounded-xl p-3 border text-center text-xs font-bold ${
                action === "block_all_longs" ? "bg-red-500/15 border-red-500/30 text-red-400" :
                action === "block_longs" ? "bg-orange-500/15 border-orange-500/30 text-orange-400" :
                "bg-green-500/15 border-green-500/30 text-green-400"
              }`}>
                SENTIMENT GATE: {action.replace(/_/g, " ").toUpperCase()} {sentiment.combined_reason ? `— ${sentiment.combined_reason}` : ""}
              </div>
            );
          })()}
        </div>
      )}

      {/* Alpaca — CNN Fear & Greed for Stocks */}
      {platform === "alpaca" && sentiment && sentiment.cnn_fear_greed && (
        <Section title="CNN Fear & Greed Index — US Stock Market">
          <div className="flex items-center gap-6">
            <div className="relative w-24 h-24 shrink-0">
              <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90">
                <circle cx="50" cy="50" r="42" fill="none" stroke="currentColor" strokeWidth="8" className="text-bah-border" />
                <circle cx="50" cy="50" r="42" fill="none" strokeWidth="8"
                  strokeDasharray={`${(sentiment.cnn_fear_greed.value / 100) * 264} 264`}
                  strokeLinecap="round"
                  className={
                    sentiment.cnn_fear_greed.value <= 24 ? "text-red-500" :
                    sentiment.cnn_fear_greed.value <= 39 ? "text-orange-500" :
                    sentiment.cnn_fear_greed.value <= 60 ? "text-yellow-500" :
                    sentiment.cnn_fear_greed.value <= 74 ? "text-green-400" :
                    "text-green-500"
                  } />
              </svg>
              <div className="absolute inset-0 flex items-center justify-center">
                <span className={`text-2xl font-black ${
                  sentiment.cnn_fear_greed.value <= 24 ? "text-red-500" :
                  sentiment.cnn_fear_greed.value <= 39 ? "text-orange-500" :
                  sentiment.cnn_fear_greed.value <= 60 ? "text-yellow-500" :
                  "text-green-400"
                }`}>{sentiment.cnn_fear_greed.value}</span>
              </div>
            </div>
            <div className="flex-1">
              <div className={`text-lg font-bold ${
                sentiment.cnn_fear_greed.value <= 24 ? "text-red-500" :
                sentiment.cnn_fear_greed.value <= 39 ? "text-orange-500" :
                sentiment.cnn_fear_greed.value <= 60 ? "text-yellow-500" :
                "text-green-400"
              }`}>{sentiment.cnn_fear_greed.classification}</div>
              <div className="text-[10px] text-bah-muted mt-1">Source: CNN · Free · No API key</div>
              <div className="mt-2">
                {sentiment.cnn_fear_greed.should_block_longs ? (
                  <span className="px-3 py-1 rounded-lg text-[10px] font-bold bg-red-500/20 text-red-400 border border-red-500/30">
                    🛑 STOCK LONGS BLOCKED (Extreme Fear)
                  </span>
                ) : (
                  <span className="px-3 py-1 rounded-lg text-[10px] font-bold bg-green-500/20 text-green-400 border border-green-500/30">
                    ✅ STOCK LONGS ALLOWED
                  </span>
                )}
              </div>
              {/* Sub-indicators */}
              {sentiment.cnn_fear_greed.indicators && Object.keys(sentiment.cnn_fear_greed.indicators).length > 0 && (
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5 mt-3">
                  {Object.entries(sentiment.cnn_fear_greed.indicators).map(([key, ind]: [string, any]) => (
                    <div key={key} className={`rounded-md px-2 py-1 text-[9px] border ${
                      ind.rating === "extreme fear" ? "bg-red-500/10 border-red-500/20 text-red-400" :
                      ind.rating === "fear" ? "bg-orange-500/10 border-orange-500/20 text-orange-400" :
                      ind.rating === "greed" ? "bg-green-500/10 border-green-500/20 text-green-400" :
                      ind.rating === "extreme greed" ? "bg-green-500/15 border-green-500/25 text-green-500" :
                      "bg-yellow-500/10 border-yellow-500/20 text-yellow-400"
                    }`}>
                      <div className="font-bold">{ind.score}</div>
                      <div className="text-[7px] opacity-70">{key.replace(/_/g, " ")}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </Section>
      )}

      {/* Asset Leaderboard */}
      {leaderboard && (() => {
        const assets = platform === "binance" ? (leaderboard.crypto || []) : (leaderboard.stock || []);
        if (!assets.length) return null;
        const title = platform === "binance" ? "Crypto Asset Leaderboard" : "Stock Asset Leaderboard";
        return (
          <Section title={title}>
            <table className="w-full text-xs">
              <thead>
                <tr className="text-bah-muted text-[9px] uppercase border-b border-bah-border">
                  <th className="text-left py-1.5">#</th>
                  <th className="text-left py-1.5">Asset</th>
                  <th className="text-right py-1.5">Trades</th>
                  <th className="text-right py-1.5">W/L</th>
                  <th className="text-right py-1.5">WR</th>
                  <th className="text-right py-1.5">Total PnL</th>
                  <th className="text-right py-1.5">Avg PnL</th>
                  <th className="text-right py-1.5">Avg %</th>
                  <th className="text-right py-1.5">Best</th>
                  <th className="text-right py-1.5">Worst</th>
                </tr>
              </thead>
              <tbody>
                {assets.map((a: any, i: number) => (
                  <tr key={a.asset} className={`border-b border-bah-border/20 ${
                    i === 0 && a.pnl > 0 ? "bg-green-500/5" : 
                    a.pnl < 0 ? "bg-red-500/5" : 
                    a.trades === 0 ? "opacity-40" : ""
                  }`}>
                    <td className="py-1.5 text-bah-muted">{i + 1}</td>
                    <td className="py-1.5 font-bold text-bah-heading">{a.asset}</td>
                    <td className="text-right text-bah-muted">{a.trades}</td>
                    <td className="text-right">
                      <span className="text-green-400">{a.wins}</span>
                      <span className="text-bah-muted">/</span>
                      <span className="text-red-400">{a.losses}</span>
                    </td>
                    <td className={`text-right font-bold ${a.wr >= 55 ? "text-green-400" : a.wr >= 45 ? "text-yellow-400" : "text-red-400"}`}>{a.wr}%</td>
                    <td className={`text-right font-bold ${a.pnl > 0 ? "text-green-400" : a.pnl < 0 ? "text-red-400" : "text-bah-muted"}`}>
                      {a.pnl >= 0 ? "+" : ""}{fm(a.pnl)}
                    </td>
                    <td className={`text-right ${a.avg_pnl > 0 ? "text-green-400" : a.avg_pnl < 0 ? "text-red-400" : "text-bah-muted"}`}>
                      {a.avg_pnl >= 0 ? "+" : ""}{fm(a.avg_pnl)}
                    </td>
                    <td className={`text-right ${a.avg_pnl_pct > 0 ? "text-green-400" : a.avg_pnl_pct < 0 ? "text-red-400" : "text-bah-muted"}`}>
                      {a.avg_pnl_pct >= 0 ? "+" : ""}{a.avg_pnl_pct}%
                    </td>
                    <td className="text-right text-green-400/70">{fm(a.best)}</td>
                    <td className="text-right text-red-400/70">{fm(a.worst)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="flex justify-between mt-3 pt-2 border-t border-bah-border text-[10px]">
              <span className="text-bah-muted">{assets.filter((a: any) => a.trades > 0).length} active / {assets.length} total · Sorted by PnL</span>
              <span className={`font-bold ${assets.reduce((s: number, a: any) => s + a.pnl, 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                Total: {assets.reduce((s: number, a: any) => s + a.pnl, 0) >= 0 ? "+" : ""}
                {fm(assets.reduce((s: number, a: any) => s + a.pnl, 0))}
              </span>
            </div>
          </Section>
        );
      })()}
    </div>
  );
}
