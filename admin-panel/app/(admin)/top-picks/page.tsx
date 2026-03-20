"use client";
import { useEffect, useState, useCallback } from "react";
import { apiBase } from "@/lib/utils";

const CLASS_COLORS: Record<string, string> = {
  fx: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  crypto: "bg-purple-500/20 text-purple-400 border-purple-500/30",
  indices: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  commodities: "bg-amber-500/20 text-amber-400 border-amber-500/30",
};

function ScoreBar({ score }: { score: number }) {
  const color = score >= 70 ? "bg-[#10b981]" : score >= 45 ? "bg-[#f59e0b]" : "bg-gray-600";
  return (
    <div className="flex items-center gap-2">
      <div className="w-16 h-2 bg-[#1C1C35] rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${score}%` }} />
      </div>
      <span className={`font-mono text-sm font-bold ${score >= 70 ? "text-[#10b981]" : score >= 45 ? "text-[#f59e0b]" : "text-[#555570]"}`}>
        {score}
      </span>
    </div>
  );
}

export default function TopPicksPage() {
  const [data, setData] = useState<any>(null);
  const [filter, setFilter] = useState("all");
  const [scanning, setScanning] = useState(false);
  const [loading, setLoading] = useState(true);
  const [countdown, setCountdown] = useState("");
  const [modal, setModal] = useState<{ symbol: string; reasons: string[]; direction: string; score: number } | null>(null);
  const token = typeof window !== "undefined" ? sessionStorage.getItem("bah_token") : null;
  const headers = { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };

  const SCAN_INTERVAL = 30 * 60;

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase()}/scanner/top-picks`, { headers });
      setData(await res.json());
    } catch (e) { console.error(e); }
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 60000);
    return () => clearInterval(interval);
  }, [fetchData]);

  useEffect(() => {
    const tick = () => {
      if (!data?.scanned_at) { setCountdown("--:--"); return; }
      const scannedAt = new Date(data.scanned_at).getTime();
      const nextScan = scannedAt + SCAN_INTERVAL * 1000;
      let remaining = Math.floor((nextScan - Date.now()) / 1000);
      if (remaining <= 0) {
        const overdue = Math.abs(remaining);
        const cyclesPassed = Math.floor(overdue / SCAN_INTERVAL) + 1;
        remaining = (cyclesPassed * SCAN_INTERVAL) - overdue;
      }
      const min = Math.floor(remaining / 60);
      const sec = remaining % 60;
      setCountdown(`${min}:${sec.toString().padStart(2, "0")}`);
    };
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, [data?.scanned_at]);

  const triggerScan = async () => {
    setScanning(true);
    try {
      await fetch(`${apiBase()}/scanner/trigger`, { method: "POST", headers });
      for (let i = 0; i < 20; i++) {
        await new Promise(r => setTimeout(r, 10000));
        const res = await fetch(`${apiBase()}/scanner/top-picks`, { headers });
        const newData = await res.json();
        if (newData?.total_scanned > 0 && newData.scanned_at !== data?.scanned_at) {
          setData(newData);
          break;
        }
      }
    } catch (e) { console.error(e); }
    setScanning(false);
  };

  const allResults = data?.all_results || [];
  const filtered = filter === "all" ? allResults : allResults.filter((r: any) => r.asset_class === filter);
  const topPicks = data?.top_picks || [];
  const scanTime = data?.scanned_at ? new Date(data.scanned_at).toLocaleString("en-GB", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";

  const classStats = {
    fx: allResults.filter((r: any) => r.asset_class === "fx").length,
    crypto: allResults.filter((r: any) => r.asset_class === "crypto").length,
    indices: allResults.filter((r: any) => r.asset_class === "indices").length,
    commodities: allResults.filter((r: any) => r.asset_class === "commodities").length,
  };

  return (
    <div className="p-6 max-w-6xl space-y-5">
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-[#E8E8F0] flex items-center gap-3">
            Top Picks
            <span className="text-xs bg-[#6C63FF]/20 text-[#6C63FF] px-2 py-1 rounded-full font-medium">
              {data?.total_scanned || 0} assets scanned
            </span>
          </h1>
          <p className="text-sm text-[#8888AA] mt-1">
            AI scanner ranks all assets by opportunity strength · Last scan: {scanTime}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="text-right hidden sm:block">
            <div className="text-[10px] text-[#555570] uppercase tracking-wider">Next scan</div>
            <div className="text-sm font-mono font-bold text-[#6C63FF]">{countdown}</div>
          </div>
          <button onClick={triggerScan} disabled={scanning}
            className="bg-[#6C63FF] hover:bg-[#6C63FF]/90 text-white font-semibold px-4 py-1.5 rounded-md text-sm disabled:opacity-50 shrink-0">
            {scanning ? "Scanning ~2 min..." : "Scan Now"}
          </button>
        </div>
      </div>

      {/* Top 5 Cards */}
      {topPicks.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
          {topPicks.slice(0, 5).map((pick: any, i: number) => (
            <div key={pick.symbol} className={`bg-[#0F0F1E] border rounded-xl p-4 ${i === 0 ? "border-[#6C63FF]/50 ring-1 ring-[#6C63FF]/20" : "border-[#2A2A4A]"}`}>
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className={`text-xs font-bold ${i === 0 ? "text-[#6C63FF]" : "text-[#555570]"}`}>#{i + 1}</span>
                  <span className="font-bold text-lg text-[#E8E8F0]">{pick.symbol}</span>
                </div>
                <span className={`px-2 py-0.5 rounded text-xs font-bold border ${CLASS_COLORS[pick.asset_class] || "bg-gray-500/20 text-gray-400"}`}>
                  {pick.asset_class}
                </span>
              </div>
              <div className="flex items-center justify-between mb-2">
                <span className={`text-sm font-bold ${pick.direction === "LONG" ? "text-[#10b981]" : pick.direction === "SHORT" ? "text-[#E94560]" : "text-[#555570]"}`}>
                  {pick.direction === "LONG" ? "▲" : pick.direction === "SHORT" ? "▼" : "─"} {pick.direction}
                </span>
                <span className="font-mono text-sm text-[#8888AA]">${pick.price}</span>
              </div>
              <ScoreBar score={pick.score} />
              {pick.whale_score > 0 && (
                <div className="mt-2">
                  <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                    pick.whale_score >= 20 ? "bg-[#10b981]/20 text-[#10b981]" : "bg-[#f59e0b]/20 text-[#f59e0b]"
                  }`}>
                    🐋 {pick.whale_signal === "EXTREME_SPIKE" ? "EXTREME" : pick.whale_signal === "MAJOR_SPIKE" ? "MAJOR" : "ACTIVE"} · Vol {pick.volume_ratio}x
                  </span>
                </div>
              )}
              <div className="mt-1 text-[10px] text-[#555570] leading-tight">
                {pick.reasons?.slice(0, 2).join(" · ")}
              </div>
              {pick.agent_decision && (
                <div className={`mt-2 pt-2 border-t border-[#2A2A4A] text-xs font-semibold ${
                  pick.agent_decision === "SIGNAL" || pick.agent_decision === "STRONG_SIGNAL" ? "text-[#6C63FF]" : "text-[#555570]"
                }`}>
                  Agent: {pick.agent_decision} ({(pick.agent_score * 100).toFixed(0)}%)
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        {[
          { key: "all", label: `All (${allResults.length})` },
          { key: "indices", label: `Stocks (${classStats.indices})` },
          { key: "crypto", label: `Crypto (${classStats.crypto})` },
          { key: "fx", label: `FX (${classStats.fx})` },
          { key: "commodities", label: `Commodities (${classStats.commodities})` },
        ].map(f => (
          <button key={f.key} onClick={() => setFilter(f.key)}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              filter === f.key ? "bg-[#6C63FF]/20 text-[#6C63FF]" : "bg-[#0F0F1E] text-[#8888AA] hover:text-[#E8E8F0]"
            }`}>
            {f.label}
          </button>
        ))}
      </div>

      {/* Full Table */}
      <div className="bg-[#0F0F1E] border border-[#2A2A4A] rounded-lg overflow-x-auto">
        <table className="w-full min-w-[800px]">
          <thead>
            <tr className="border-b border-[#2A2A4A] text-xs text-[#555570] uppercase tracking-wider">
              <th className="text-left py-3 px-4">Rank</th>
              <th className="text-left py-3 px-4">Asset</th>
              <th className="text-left py-3 px-4">Class</th>
              <th className="text-right py-3 px-4">Price</th>
              <th className="text-right py-3 px-4">Change</th>
              <th className="text-center py-3 px-4">Direction</th>
              <th className="text-right py-3 px-4">Score</th>
              <th className="text-center py-3 px-4">Whales</th>
              <th className="text-right py-3 px-4">RSI</th>
              <th className="text-right py-3 px-4">ADX</th>
              <th className="text-left py-3 px-4">Reasons</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={11} className="py-12 text-center text-[#555570] text-sm">Loading scanner results...</td></tr>
            ) : filtered.length === 0 ? (
              <tr><td colSpan={11} className="py-12 text-center text-[#555570] text-sm">
                No scan results yet. Click &quot;Scan Now&quot; to analyze all assets.
              </td></tr>
            ) : (
              filtered.map((r: any) => {
                const rank = allResults.indexOf(r) + 1;
                return (
                  <tr key={r.symbol} className="border-b border-[#2A2A4A]/50 hover:bg-[#161628]/50 transition-colors">
                    <td className="py-2.5 px-4 text-sm font-mono text-[#555570]">{rank}</td>
                    <td className="py-2.5 px-4 font-semibold text-sm text-[#E8E8F0]">{r.symbol}</td>
                    <td className="py-2.5 px-4">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-medium border ${CLASS_COLORS[r.asset_class] || ""}`}>
                        {r.asset_class}
                      </span>
                    </td>
                    <td className="py-2.5 px-4 text-right font-mono text-sm text-[#8888AA]">{r.price}</td>
                    <td className={`py-2.5 px-4 text-right font-mono text-sm ${r.change_pct >= 0 ? "text-[#10b981]" : "text-[#E94560]"}`}>
                      {r.change_pct >= 0 ? "+" : ""}{r.change_pct}%
                    </td>
                    <td className="py-2.5 px-4 text-center">
                      <span className={`text-sm font-bold ${r.direction === "LONG" ? "text-[#10b981]" : r.direction === "SHORT" ? "text-[#E94560]" : "text-[#555570]"}`}>
                        {r.direction === "LONG" ? "▲" : r.direction === "SHORT" ? "▼" : "─"}
                      </span>
                    </td>
                    <td className="py-2.5 px-4 text-right"><ScoreBar score={r.score} /></td>
                    <td className="py-2.5 px-4 text-center">
                      {r.whale_score > 0 ? (
                        <span className={`text-xs font-bold px-1.5 py-0.5 rounded ${
                          r.whale_score >= 20 ? "bg-[#10b981]/20 text-[#10b981]" :
                          r.whale_score >= 10 ? "bg-[#f59e0b]/20 text-[#f59e0b]" :
                          "bg-[#1C1C35] text-[#555570]"
                        }`}>
                          🐋 {r.whale_score > 20 ? "+++" : r.whale_score > 10 ? "++" : "+"}
                        </span>
                      ) : r.whale_score < 0 ? (
                        <span className="text-xs font-bold px-1.5 py-0.5 rounded bg-[#E94560]/20 text-[#E94560]">🐋 −</span>
                      ) : (
                        <span className="text-xs text-[#555570]">—</span>
                      )}
                    </td>
                    <td className={`py-2.5 px-4 text-right font-mono text-sm ${r.rsi < 30 || r.rsi > 70 ? "text-[#f59e0b] font-bold" : "text-[#8888AA]"}`}>
                      {r.rsi}
                    </td>
                    <td className={`py-2.5 px-4 text-right font-mono text-sm ${r.adx > 25 ? "text-[#10b981]" : "text-[#555570]"}`}>
                      {r.adx}
                    </td>
                    <td className="py-2.5 px-4">
                      <button
                        onClick={() => setModal({ symbol: r.symbol, reasons: r.reasons || [], direction: r.direction, score: r.score })}
                        className="text-xs text-[#6C63FF] hover:text-[#6C63FF]/80 hover:underline text-left max-w-[200px] truncate cursor-pointer"
                      >
                        {r.reasons?.join(" · ") || "—"}
                      </button>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Info */}
      <div className="bg-[#0F0F1E]/50 border border-[#2A2A4A]/50 rounded-xl p-4 text-xs text-[#555570]">
        <strong className="text-[#8888AA]">How the scanner works:</strong> Every 30 minutes, Bahamut scans all assets.
        Each gets a technical score based on RSI, EMA alignment, MACD momentum, ADX trend strength, and Bollinger Band breakouts.
        <strong className="text-[#8888AA]"> Whale detection</strong> adds bonus points for unusual volume spikes (🐋).
        The top 10 get a full 6-agent deep analysis. Scores above 70 = strong opportunity.
      </div>

      {/* Reasons Modal */}
      {modal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4" onClick={() => setModal(null)}>
          <div className="absolute inset-0 bg-black/60" />
          <div className="relative bg-[#0F0F1E] border border-[#2A2A4A] rounded-2xl p-6 max-w-md w-full shadow-2xl" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-3">
                <span className={`text-2xl font-bold ${modal.direction === "LONG" ? "text-[#10b981]" : "text-[#E94560]"}`}>
                  {modal.direction === "LONG" ? "▲" : "▼"}
                </span>
                <div>
                  <div className="text-lg font-bold text-[#E8E8F0]">{modal.symbol}</div>
                  <div className={`text-sm font-semibold ${modal.direction === "LONG" ? "text-[#10b981]" : "text-[#E94560]"}`}>
                    {modal.direction} · Score {modal.score}/100
                  </div>
                </div>
              </div>
              <button onClick={() => setModal(null)} className="text-[#555570] hover:text-[#E8E8F0] text-xl leading-none p-1">✕</button>
            </div>
            <div className="mb-4">
              <div className="text-xs text-[#555570] uppercase tracking-wider mb-2">Why this asset scored high</div>
              <div className="space-y-2">
                {modal.reasons.length > 0 ? modal.reasons.map((reason: string, i: number) => (
                  <div key={i} className="flex items-start gap-3 p-3 bg-[#161628] rounded-lg border border-[#2A2A4A]">
                    <span className="text-[#6C63FF] font-bold text-sm mt-0.5">{i + 1}</span>
                    <span className="text-sm text-[#E8E8F0] leading-relaxed">{reason}</span>
                  </div>
                )) : (
                  <div className="text-sm text-[#555570] p-3">No specific reasons recorded.</div>
                )}
              </div>
            </div>
            <div className="flex gap-2">
              <a href="/agent-council" className="flex-1 text-center py-2 bg-[#6C63FF]/20 text-[#6C63FF] rounded-lg text-sm font-semibold hover:bg-[#6C63FF]/30 transition-colors">
                Deep Analysis in Agent Council
              </a>
              <button onClick={() => setModal(null)} className="px-4 py-2 bg-[#161628] text-[#8888AA] rounded-lg text-sm hover:bg-[#1C1C35] transition-colors">
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
