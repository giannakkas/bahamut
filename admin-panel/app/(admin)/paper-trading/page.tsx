"use client";
import { useState, useEffect } from "react";
import { apiBase } from "@/lib/utils";

export default function PaperTradingPage() {
  const [portfolio, setPortfolio] = useState<any>(null);
  const [positions, setPositions] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const token = typeof window !== "undefined" ? sessionStorage.getItem("bah_token") : null;
  const headers = { Authorization: `Bearer ${token}` };

  useEffect(() => {
    Promise.all([
      fetch(`${apiBase()}/paper-trading/portfolio`, { headers }).then(r => r.json()).catch(() => null),
      fetch(`${apiBase()}/paper-trading/positions`, { headers }).then(r => r.json()).catch(() => []),
    ]).then(([pf, pos]) => {
      setPortfolio(pf);
      setPositions(Array.isArray(pos) ? pos : []);
      setLoading(false);
    });
  }, []);

  if (loading) return <div className="p-6 text-bah-muted">Loading paper trading...</div>;

  return (
    <div className="p-6 max-w-5xl space-y-6">
      <h1 className="text-xl font-bold text-bah-heading">Paper Trading</h1>

      {portfolio && (
        <div className="grid grid-cols-4 gap-3">
          {[
            { label: "Balance", value: `$${(portfolio.current_balance || 100000).toLocaleString()}`, color: "text-bah-cyan" },
            { label: "Total P&L", value: `$${(portfolio.total_pnl || 0).toFixed(2)}`, color: (portfolio.total_pnl || 0) >= 0 ? "text-green-400" : "text-red-400" },
            { label: "Win Rate", value: `${((portfolio.win_rate || 0) * 100).toFixed(1)}%`, color: "text-bah-heading" },
            { label: "Total Trades", value: portfolio.total_trades || 0, color: "text-bah-heading" },
          ].map(m => (
            <div key={m.label} className="bg-bah-surface border border-bah-border rounded-xl p-4 text-center">
              <div className={`text-xl font-bold ${m.color}`}>{m.value}</div>
              <div className="text-[10px] text-bah-muted uppercase mt-1">{m.label}</div>
            </div>
          ))}
        </div>
      )}

      <div className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-bah-border">
          <h2 className="text-sm font-semibold text-bah-heading">Open Positions</h2>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-bah-border text-xs text-bah-muted uppercase">
              <th className="px-4 py-2 text-left">Asset</th>
              <th className="px-4 py-2 text-left">Direction</th>
              <th className="px-4 py-2 text-right">Entry</th>
              <th className="px-4 py-2 text-right">Size</th>
              <th className="px-4 py-2 text-right">P&L</th>
              <th className="px-4 py-2 text-left">Status</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((p: any, i: number) => (
              <tr key={i} className="border-b border-bah-border/30 hover:bg-white/[0.02]">
                <td className="px-4 py-2 font-medium text-bah-heading">{p.asset}</td>
                <td className="px-4 py-2">
                  <span className={p.direction === "LONG" ? "text-green-400" : "text-red-400"}>{p.direction}</span>
                </td>
                <td className="px-4 py-2 text-right font-mono text-bah-subtle">{p.entry_price}</td>
                <td className="px-4 py-2 text-right font-mono text-bah-subtle">${p.position_value?.toFixed(0)}</td>
                <td className={`px-4 py-2 text-right font-mono ${(p.unrealized_pnl || 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                  ${(p.unrealized_pnl || 0).toFixed(2)}
                </td>
                <td className="px-4 py-2 text-xs text-bah-muted">{p.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {positions.length === 0 && <div className="text-sm text-bah-muted text-center py-8">No open positions</div>}
      </div>
    </div>
  );
}
