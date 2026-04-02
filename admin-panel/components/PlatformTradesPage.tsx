"use client";
import React, { useState, useEffect, useCallback } from "react";
import { apiBase } from "@/lib/utils";

const STRAT_NAMES: Record<string, string> = {
  v5_base: "S1 · EMA Trend", v5_tuned: "S2 · EMA Tuned",
  v9_breakout: "S3 · Breakout", v10_mean_reversion: "S4 · Mean Reversion",
};
const sn = (s: string) => STRAT_NAMES[s] || s;
const fm = (n: number) => `$${Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const fmS = (n: number) => `${n >= 0 ? "+" : "-"}${fm(n)}`;
const fp = (n: number) => `${n >= 0 ? "+" : ""}${(n * 100).toFixed(1)}%`;
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

export default function PlatformTradesPage({ platform, icon, label, color }: {
  platform: string; icon: string; label: string; color: string;
}) {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const t = localStorage.getItem("bahamut_admin_token");
      const h: Record<string, string> = t ? { Authorization: `Bearer ${t}` } : {};
      const r = await fetch(`${apiBase()}/training/platform-trades/${platform}`, { headers: h });
      if (r.ok) setData(await r.json());
    } catch {}
    setLoading(false);
  }, [platform]);

  useEffect(() => { load(); const iv = setInterval(load, 30000); return () => clearInterval(iv); }, [load]);

  if (loading) return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="text-center">
        <div className="inline-block w-8 h-8 border-2 border-bah-cyan/30 border-t-bah-cyan rounded-full animate-spin mb-4" />
        <div className="text-bah-muted text-xs">Loading {label} trades...</div>
      </div>
    </div>
  );

  if (!data || data.error) return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="text-bah-muted text-sm">No data available. {data?.error || ""}</div>
    </div>
  );

  const s = data.summary;
  const trades = data.trades || [];
  const byAsset = data.by_asset || {};
  const byStrat = data.by_strategy || {};

  return (
    <div className="p-2 sm:p-4 max-w-[1440px] mx-auto space-y-4 pt-12 lg:pt-4">
      {/* Header */}
      <div className="flex items-center gap-3">
        <span className="text-2xl">{icon}</span>
        <div>
          <h1 className="text-lg font-bold text-bah-heading">{label} Trades</h1>
          <p className="text-[10px] text-bah-muted">{s.total_trades} trades · {data.asset_class} assets · Last updated: {new Date().toLocaleTimeString()}</p>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-2">
        {[
          { l: "Total PnL", v: fmS(s.total_pnl), c: pnlC(s.total_pnl) },
          { l: "Win Rate", v: `${(s.win_rate * 100).toFixed(1)}%`, c: s.win_rate >= 0.5 ? "text-green-400" : "text-amber-400" },
          { l: "Profit Factor", v: s.profit_factor.toFixed(2), c: s.profit_factor >= 1 ? "text-green-400" : "text-red-400" },
          { l: "Trades", v: String(s.total_trades), c: "text-bah-heading" },
          { l: "Wins", v: String(s.wins), c: "text-green-400" },
          { l: "Losses", v: String(s.losses), c: "text-red-400" },
          { l: "Avg Win", v: fm(s.avg_win), c: "text-green-400" },
          { l: "Avg Loss", v: fm(s.avg_loss), c: "text-red-400" },
        ].map((card, i) => (
          <div key={i} className="bg-bah-card border border-bah-border rounded-lg p-3 text-center">
            <div className={`text-sm sm:text-base font-bold ${card.c}`}>{card.v}</div>
            <div className="text-[8px] text-bah-muted uppercase tracking-wider mt-0.5">{card.l}</div>
          </div>
        ))}
      </div>

      {/* Best / Worst Trade */}
      {(s.best_trade || s.worst_trade) && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {s.best_trade && (
            <div className="bg-green-500/10 border border-green-500/20 rounded-xl p-3 flex justify-between items-center">
              <div>
                <div className="text-[9px] text-green-400/60 uppercase font-bold">Best Trade</div>
                <div className="text-sm text-bah-heading font-bold">{s.best_trade.asset} <span className="text-[10px] text-bah-muted">{sn(s.best_trade.strategy)}</span></div>
              </div>
              <div className="text-lg font-bold text-green-400">{fmS(s.best_trade.pnl)}</div>
            </div>
          )}
          {s.worst_trade && (
            <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-3 flex justify-between items-center">
              <div>
                <div className="text-[9px] text-red-400/60 uppercase font-bold">Worst Trade</div>
                <div className="text-sm text-bah-heading font-bold">{s.worst_trade.asset} <span className="text-[10px] text-bah-muted">{sn(s.worst_trade.strategy)}</span></div>
              </div>
              <div className="text-lg font-bold text-red-400">{fmS(s.worst_trade.pnl)}</div>
            </div>
          )}
        </div>
      )}

      {/* Asset + Strategy Breakdown Side by Side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Section title="By Asset">
          <div className="space-y-1">
            {Object.entries(byAsset).map(([asset, st]: [string, any]) => {
              const wr = st.wins + st.losses > 0 ? st.wins / (st.wins + st.losses) : 0;
              return (
                <div key={asset} className="flex items-center justify-between py-1.5 border-b border-bah-border/30 last:border-0 text-xs">
                  <div className="flex items-center gap-2">
                    <span className="text-bah-heading font-bold w-[70px]">{asset}</span>
                    <span className="text-bah-muted">{st.trades}t</span>
                    <span className="text-bah-muted">{(wr * 100).toFixed(0)}% WR</span>
                  </div>
                  <span className={`font-bold ${pnlC(st.pnl)}`}>{fmS(st.pnl)}</span>
                </div>
              );
            })}
          </div>
        </Section>

        <Section title="By Strategy">
          <div className="space-y-1">
            {Object.entries(byStrat).map(([strat, st]: [string, any]) => {
              const wr = st.wins + st.losses > 0 ? st.wins / (st.wins + st.losses) : 0;
              return (
                <div key={strat} className="flex items-center justify-between py-1.5 border-b border-bah-border/30 last:border-0 text-xs">
                  <div className="flex items-center gap-2">
                    <span className="text-bah-heading font-bold">{sn(strat)}</span>
                    <span className="text-bah-muted">{st.trades}t</span>
                    <span className="text-bah-muted">{(wr * 100).toFixed(0)}% WR</span>
                  </div>
                  <span className={`font-bold ${pnlC(st.pnl)}`}>{fmS(st.pnl)}</span>
                </div>
              );
            })}
          </div>
        </Section>
      </div>

      {/* Full Trade List */}
      <Section title={`All Trades (${trades.length})`}>
        <div className="overflow-x-auto">
          <table className="w-full text-[10px] sm:text-xs min-w-[900px]">
            <thead>
              <tr className="border-b border-bah-border text-[8px] text-bah-muted uppercase tracking-wider text-left">
                <th className="py-2 pr-2">Time</th>
                <th className="py-2 pr-2">Asset</th>
                <th className="py-2 pr-2">Strategy</th>
                <th className="py-2 pr-2">Dir</th>
                <th className="py-2 pr-2">Entry</th>
                <th className="py-2 pr-2">Exit</th>
                <th className="py-2 pr-2">Bars</th>
                <th className="py-2 pr-2">Reason</th>
                <th className="py-2 pr-2">PnL</th>
                <th className="py-2">Result</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t: any, i: number) => {
                const isWin = t.pnl > 0.01;
                const isLoss = t.pnl < -0.01;
                const isFlat = !isWin && !isLoss;
                return (
                  <tr key={i} className="border-b border-bah-border/30 hover:bg-bah-surface/50">
                    <td className="py-2 pr-2 text-bah-muted">{t.exit_time ? new Date(t.exit_time).toLocaleDateString("en-GB", { day: "numeric", month: "short" }) + " " + new Date(t.exit_time).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }) : ""}</td>
                    <td className="py-2 pr-2 text-bah-heading font-bold">{t.asset}</td>
                    <td className="py-2 pr-2 text-bah-muted">{sn(t.strategy)}</td>
                    <td className={`py-2 pr-2 font-bold ${t.direction === "LONG" ? "text-green-400" : "text-red-400"}`}>{t.direction}</td>
                    <td className="py-2 pr-2 text-bah-text">{fm(t.entry_price)}</td>
                    <td className="py-2 pr-2 text-bah-text">{fm(t.exit_price)}</td>
                    <td className="py-2 pr-2 text-bah-muted">{t.bars_held}</td>
                    <td className="py-2 pr-2">
                      <span className={`px-1.5 py-0.5 rounded text-[8px] font-bold ${
                        t.exit_reason === "TP" ? "bg-green-500/15 text-green-400" :
                        t.exit_reason === "SL" ? "bg-red-500/15 text-red-400" :
                        "bg-bah-surface text-bah-muted"
                      }`}>{t.exit_reason}</span>
                    </td>
                    <td className={`py-2 pr-2 font-bold ${pnlC(t.pnl)}`}>{fmS(t.pnl)}</td>
                    <td className="py-2">
                      <span className={`px-1.5 py-0.5 rounded text-[8px] font-bold ${
                        isWin ? "bg-green-500/15 text-green-400" :
                        isLoss ? "bg-red-500/15 text-red-400" :
                        "bg-bah-surface text-bah-muted"
                      }`}>{isWin ? "WIN" : isLoss ? "LOSS" : "FLAT"}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Section>
    </div>
  );
}
