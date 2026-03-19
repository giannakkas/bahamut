"use client";
import { useState, useEffect } from "react";
import { apiBase } from "@/lib/utils";

export default function TradeJournalPage() {
  const [trades, setTrades] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const token = typeof window !== "undefined" ? sessionStorage.getItem("bah_token") : null;

  useEffect(() => {
    fetch(`${apiBase()}/paper-trading/positions?status=CLOSED&limit=50`, { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.json()).then(d => setTrades(Array.isArray(d) ? d : []))
      .catch(() => setTrades([])).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="p-6 text-bah-muted">Loading trade journal...</div>;

  const totalPnl = trades.reduce((s, t) => s + (t.realized_pnl || 0), 0);
  const wins = trades.filter(t => (t.realized_pnl || 0) > 0).length;
  const winRate = trades.length > 0 ? (wins / trades.length * 100).toFixed(1) : "0.0";

  return (
    <div className="p-6 max-w-5xl space-y-6">
      <h1 className="text-xl font-bold text-bah-heading">Trade Journal</h1>

      <div className="grid grid-cols-4 gap-3">
        <div className="bg-bah-surface border border-bah-border rounded-xl p-4 text-center">
          <div className="text-xl font-bold text-bah-heading">{trades.length}</div>
          <div className="text-[10px] text-bah-muted uppercase">Total Trades</div>
        </div>
        <div className="bg-bah-surface border border-bah-border rounded-xl p-4 text-center">
          <div className={`text-xl font-bold ${totalPnl >= 0 ? "text-green-400" : "text-red-400"}`}>${totalPnl.toFixed(2)}</div>
          <div className="text-[10px] text-bah-muted uppercase">Total P&L</div>
        </div>
        <div className="bg-bah-surface border border-bah-border rounded-xl p-4 text-center">
          <div className="text-xl font-bold text-bah-cyan">{winRate}%</div>
          <div className="text-[10px] text-bah-muted uppercase">Win Rate</div>
        </div>
        <div className="bg-bah-surface border border-bah-border rounded-xl p-4 text-center">
          <div className="text-xl font-bold text-green-400">{wins}</div>
          <div className="text-[10px] text-bah-muted uppercase">Wins</div>
        </div>
      </div>

      <div className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-bah-border text-xs text-bah-muted uppercase">
              <th className="px-4 py-2 text-left">Asset</th>
              <th className="px-4 py-2 text-left">Direction</th>
              <th className="px-4 py-2 text-right">Entry</th>
              <th className="px-4 py-2 text-right">Exit</th>
              <th className="px-4 py-2 text-right">P&L</th>
              <th className="px-4 py-2 text-left">Closed</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((t: any, i: number) => (
              <tr key={i} className="border-b border-bah-border/30 hover:bg-white/[0.02]">
                <td className="px-4 py-2 font-medium text-bah-heading">{t.asset}</td>
                <td className="px-4 py-2"><span className={t.direction === "LONG" ? "text-green-400" : "text-red-400"}>{t.direction}</span></td>
                <td className="px-4 py-2 text-right font-mono text-bah-subtle">{t.entry_price}</td>
                <td className="px-4 py-2 text-right font-mono text-bah-subtle">{t.exit_price || "—"}</td>
                <td className={`px-4 py-2 text-right font-mono font-semibold ${(t.realized_pnl || 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                  ${(t.realized_pnl || 0).toFixed(2)}
                </td>
                <td className="px-4 py-2 text-xs text-bah-muted">{t.closed_at ? new Date(t.closed_at).toLocaleDateString() : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {trades.length === 0 && <div className="text-sm text-bah-muted text-center py-8">No closed trades yet</div>}
      </div>
    </div>
  );
}
