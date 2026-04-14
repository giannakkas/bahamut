"use client";

import React, { useState, useEffect } from "react";
import { apiBase } from "@/lib/utils";

/* ═══════════════════════════════════════════
   TYPES
   ═══════════════════════════════════════════ */
interface Snapshot {
  timestamp: string;
  summary: any;
  class_context: Record<string, any>;
  asset_context: Record<string, any>;
  headline_context: any[];
  event_context: any[];
  pipeline_directives: any;
  source_of_truth: string;
}

/* ═══════════════════════════════════════════
   HELPERS
   ═══════════════════════════════════════════ */
const MODE_COLORS: Record<string, string> = {
  NORMAL: "text-green-400",
  CAUTION: "text-yellow-400",
  RESTRICTED: "text-orange-400",
  FROZEN: "text-red-400",
  DEFENSIVE: "text-orange-400",
  SELECTIVE: "text-yellow-400",
  AGGRESSIVE: "text-green-400",
};

const MODE_BG: Record<string, string> = {
  NORMAL: "bg-green-500/10 border-green-500/30",
  CAUTION: "bg-yellow-500/10 border-yellow-500/30",
  RESTRICTED: "bg-orange-500/10 border-orange-500/30",
  FROZEN: "bg-red-500/10 border-red-500/30",
};

const POSTURE_BG: Record<string, string> = {
  DEFENSIVE: "bg-orange-500/10 border-orange-500/30",
  SELECTIVE: "bg-yellow-500/10 border-yellow-500/30",
  AGGRESSIVE: "bg-green-500/10 border-green-500/30",
  FROZEN: "bg-red-500/10 border-red-500/30",
};

function Badge({ mode }: { mode: string }) {
  const bg = MODE_BG[mode] || MODE_BG.NORMAL;
  const color = MODE_COLORS[mode] || "text-green-400";
  return (
    <span className={`inline-block px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider rounded border ${bg} ${color}`}>
      {mode}
    </span>
  );
}

function Pill({ label, value, color }: { label: string; value: string | number; color?: string }) {
  return (
    <div className="flex flex-col items-center px-3 py-2">
      <span className={`text-lg font-bold font-mono ${color || "text-cyan-400"}`}>{value}</span>
      <span className="text-[10px] uppercase tracking-wider text-gray-500 mt-0.5">{label}</span>
    </div>
  );
}

/* ═══════════════════════════════════════════
   PAGE
   ═══════════════════════════════════════════ */
export default function MarketIntelligencePage() {
  const [data, setData] = useState<Snapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [assetFilter, setAssetFilter] = useState("");
  const [classFilter, setClassFilter] = useState("all");

  const fetchData = async () => {
    try {
      const t = localStorage.getItem("bahamut_admin_token");
      const h: Record<string, string> = t ? { Authorization: `Bearer ${t}` } : {};
      const r = await fetch(`${apiBase()}/training/market-intelligence`, { headers: h });
      if (!r.ok) {
        const errBody = await r.json().catch(() => ({}));
        throw new Error(errBody.error || errBody.trace || `HTTP ${r.status}`);
      }
      const j = await r.json();
      setData(j);
      setError("");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    const iv = setInterval(fetchData, 30000);
    return () => clearInterval(iv);
  }, []);

  if (loading) return (
    <div className="flex items-center justify-center h-64 text-gray-500 font-mono text-sm">
      Loading market intelligence...
    </div>
  );

  if (error) return (
    <div className="p-6 text-red-400 font-mono text-sm">Error: {error}</div>
  );

  if (!data) return null;
  const { summary, class_context, asset_context, headline_context, event_context, pipeline_directives } = data;

  // Filter assets
  const assetEntries = Object.entries(asset_context || {}).filter(([a, ctx]: [string, any]) => {
    if (classFilter !== "all" && ctx.asset_class !== classFilter) return false;
    if (assetFilter && !a.toLowerCase().includes(assetFilter.toLowerCase())) return false;
    return true;
  });

  return (
    <div className="space-y-6 pb-12">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-100 tracking-tight font-mono">
            AI Market Intelligence
          </h1>
          <p className="text-xs text-gray-500 mt-0.5 font-mono">
            Source of truth: <span className="text-cyan-400">{data.source_of_truth}</span>
            {" · "}
            <span className="text-gray-400">{data.timestamp}</span>
          </p>
        </div>
        <button onClick={fetchData}
          className="px-3 py-1.5 text-xs font-mono border border-gray-700 rounded hover:bg-white/5 text-gray-400 hover:text-cyan-400 transition-colors">
          ↻ Refresh
        </button>
      </div>

      {/* ═══ SUMMARY CARD ═══ */}
      <div className={`rounded-lg border p-5 ${POSTURE_BG[summary?.pipeline_posture] || POSTURE_BG.SELECTIVE}`}>
        <div className="flex items-center gap-3 mb-3">
          <span className="text-2xl">🧠</span>
          <div>
            <h2 className="text-sm font-bold text-gray-200 font-mono uppercase tracking-wider">Pipeline Posture</h2>
            <span className={`text-xl font-bold font-mono ${MODE_COLORS[summary?.pipeline_posture] || "text-gray-400"}`}>
              {summary?.pipeline_posture || "UNKNOWN"}
            </span>
          </div>
        </div>

        <div className="flex flex-wrap gap-1 mb-4">
          <div className="flex items-center gap-6 flex-wrap">
            <Pill label="Crypto F&G" value={summary?.crypto_fear_greed ?? "?"} color={summary?.crypto_fear_greed <= 25 ? "text-red-400" : summary?.crypto_fear_greed <= 40 ? "text-yellow-400" : "text-green-400"} />
            <Pill label="Stocks F&G" value={summary?.stocks_fear_greed ?? "?"} color={summary?.stocks_fear_greed <= 35 ? "text-yellow-400" : "text-green-400"} />
            <Pill label="Crypto Mode" value={summary?.crypto_market_mode || "?"} color={MODE_COLORS[summary?.crypto_market_mode]} />
            <Pill label="Stocks Mode" value={summary?.stocks_market_mode || "?"} color={MODE_COLORS[summary?.stocks_market_mode]} />
            <Pill label="Macro Risk" value={summary?.macro_risk_mode || "?"} color={MODE_COLORS[summary?.macro_risk_mode]} />
            <Pill label="Headlines" value={summary?.active_headlines ?? 0} />
            <Pill label="High Events" value={summary?.upcoming_high_events ?? 0} color={summary?.upcoming_high_events > 0 ? "text-orange-400" : "text-gray-500"} />
          </div>
        </div>

        <div className="bg-black/30 rounded-md p-3 text-xs text-gray-300 font-mono leading-relaxed">
          {summary?.ai_narrative || "No narrative available."}
        </div>
      </div>

      {/* ═══ PIPELINE DIRECTIVES ═══ */}
      <div className="rounded-lg border border-gray-800 bg-[#0d1220] p-4">
        <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-3 font-mono">Pipeline Directives</h3>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { label: "Crypto LONGs", val: pipeline_directives?.crypto_longs_allowed, truthy: "ALLOWED", falsy: "BLOCKED" },
            { label: "Crypto SHORTs", val: pipeline_directives?.crypto_shorts_allowed, truthy: "ALLOWED", falsy: "BLOCKED" },
            { label: "Stock LONGs", val: pipeline_directives?.stock_longs_allowed, truthy: "ALLOWED", falsy: "BLOCKED" },
            { label: "Stock SHORTs", val: pipeline_directives?.stock_shorts_allowed, truthy: "ALLOWED", falsy: "BLOCKED" },
          ].map((d, i) => (
            <div key={i} className="text-center p-2 rounded border border-gray-800 bg-black/20">
              <div className={`text-sm font-bold font-mono ${d.val ? "text-green-400" : "text-red-400"}`}>
                {d.val ? d.truthy : d.falsy}
              </div>
              <div className="text-[10px] text-gray-500 uppercase mt-0.5">{d.label}</div>
            </div>
          ))}
        </div>
        <div className="mt-3 flex items-center gap-4 text-xs text-gray-500 font-mono">
          <span>Global Size Mult: <span className="text-gray-300">{pipeline_directives?.global_size_multiplier ?? 1}</span></span>
          <span>High Events 24h: <span className="text-gray-300">{pipeline_directives?.high_impact_events_next_24h ?? 0}</span></span>
        </div>
      </div>

      {/* ═══ CLASS CONTEXT CARDS ═══ */}
      <div>
        <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-3 font-mono">Asset Class Context</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-3">
          {Object.entries(class_context || {}).map(([cls, ctx]: [string, any]) => (
            <div key={cls} className={`rounded-lg border p-3 ${MODE_BG[ctx.mode] || MODE_BG.NORMAL}`}>
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-bold text-gray-200 uppercase font-mono">{cls}</span>
                <Badge mode={ctx.mode} />
              </div>
              {ctx.sentiment_value !== undefined && (
                <div className="text-xs text-gray-500 mb-1 font-mono">
                  F&G: <span className="text-gray-300">{ctx.sentiment_value}</span>
                  <span className="text-gray-600 ml-1">({ctx.sentiment_label})</span>
                </div>
              )}
              <div className="text-xs text-gray-500 font-mono space-y-0.5">
                <div>Bias: <span className="text-gray-300">{ctx.bias}</span></div>
                <div>Dirs: <span className="text-gray-300">{(ctx.preferred_directions || []).join(", ")}</span></div>
                <div>Size: <span className="text-gray-300">{ctx.size_multiplier ?? 1}×</span></div>
                <div>Penalty: <span className="text-gray-300">{ctx.threshold_penalty ?? 0}</span></div>
                <div>Policy: <span className="text-gray-300">{ctx.trade_policy}</span></div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ═══ PER-ASSET TABLE ═══ */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider font-mono">Per-Asset AI Context</h3>
          <div className="flex gap-2">
            <input
              type="text" placeholder="Filter asset..."
              value={assetFilter} onChange={(e) => setAssetFilter(e.target.value)}
              className="px-2 py-1 text-xs font-mono bg-black/30 border border-gray-700 rounded text-gray-300 placeholder-gray-600 w-32"
            />
            <select value={classFilter} onChange={(e) => setClassFilter(e.target.value)}
              className="px-2 py-1 text-xs font-mono bg-black/30 border border-gray-700 rounded text-gray-300">
              <option value="all">All Classes</option>
              <option value="crypto">Crypto</option>
              <option value="stock">Stock</option>
              <option value="forex">Forex</option>
              <option value="commodity">Commodity</option>
              <option value="index">Index</option>
            </select>
          </div>
        </div>
        <div className="overflow-x-auto rounded-lg border border-gray-800">
          <table className="w-full text-xs font-mono">
            <thead>
              <tr className="text-gray-500 uppercase tracking-wider border-b border-gray-800 bg-black/30">
                <th className="px-3 py-2 text-left">Asset</th>
                <th className="px-3 py-2 text-left">Class</th>
                <th className="px-3 py-2 text-center">News</th>
                <th className="px-3 py-2 text-center">Sentiment</th>
                <th className="px-3 py-2 text-center">Combined</th>
                <th className="px-3 py-2 text-center">Bias</th>
                <th className="px-3 py-2 text-center">Conf</th>
                <th className="px-3 py-2 text-center">Size ×</th>
                <th className="px-3 py-2 text-center">Penalty</th>
                <th className="px-3 py-2 text-left">Directions</th>
              </tr>
            </thead>
            <tbody>
              {assetEntries.map(([asset, ctx]: [string, any]) => (
                <tr key={asset} className="border-b border-gray-800/50 hover:bg-white/[0.02]">
                  <td className="px-3 py-1.5 text-gray-200 font-semibold">{asset}</td>
                  <td className="px-3 py-1.5 text-gray-500">{ctx.asset_class}</td>
                  <td className="px-3 py-1.5 text-center"><Badge mode={ctx.news_mode} /></td>
                  <td className="px-3 py-1.5 text-center"><Badge mode={ctx.sentiment_mode} /></td>
                  <td className="px-3 py-1.5 text-center"><Badge mode={ctx.combined_mode} /></td>
                  <td className="px-3 py-1.5 text-center text-gray-300">{ctx.ai_bias}</td>
                  <td className="px-3 py-1.5 text-center text-gray-400">{(ctx.ai_confidence * 100).toFixed(0)}%</td>
                  <td className={`px-3 py-1.5 text-center ${ctx.size_multiplier < 1 ? "text-orange-400" : "text-gray-400"}`}>{ctx.size_multiplier}×</td>
                  <td className={`px-3 py-1.5 text-center ${ctx.threshold_penalty > 0 ? "text-yellow-400" : "text-gray-600"}`}>{ctx.threshold_penalty}</td>
                  <td className="px-3 py-1.5 text-gray-400">{(ctx.allowed_directions || []).join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* ═══ HEADLINES ═══ */}
      {headline_context && headline_context.length > 0 && (
        <div>
          <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-3 font-mono">
            AI News Interpretation ({headline_context.length})
          </h3>
          <div className="space-y-2">
            {headline_context.map((h: any, i: number) => (
              <div key={i} className="rounded border border-gray-800 bg-black/20 p-3 flex items-start gap-3">
                <div className={`shrink-0 w-2 h-2 rounded-full mt-1.5 ${h.freshness === "fresh" ? "bg-green-400" : h.freshness === "active" ? "bg-yellow-400" : "bg-gray-600"}`} />
                <div className="flex-1 min-w-0">
                  <div className="text-xs text-gray-200 font-mono">{h.title}</div>
                  <div className="flex gap-3 mt-1 text-[10px] text-gray-500 font-mono">
                    <span>{h.source}</span>
                    <span className={h.freshness === "fresh" ? "text-green-400" : h.freshness === "active" ? "text-yellow-400" : "text-gray-600"}>{h.freshness}</span>
                    <span>Impact: {h.impact_score}</span>
                    <span>Bias: <span className="text-gray-400">{h.bias}</span></span>
                    <span>Scope: {h.scope}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ═══ ECONOMIC CALENDAR ═══ */}
      <div>
        <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-3 font-mono">
          Economic Calendar ({(event_context || []).length} events)
        </h3>
        {(!event_context || event_context.length === 0) ? (
          <div className="rounded border border-gray-800 bg-black/20 p-4 text-xs text-gray-500 font-mono">
            No calendar events cached. Events are fetched from ForexFactory / Finnhub and cached in Redis for 2 hours.
          </div>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-gray-800">
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="text-gray-500 uppercase tracking-wider border-b border-gray-800 bg-black/30">
                  <th className="px-3 py-2 text-left">Impact</th>
                  <th className="px-3 py-2 text-left">Event</th>
                  <th className="px-3 py-2 text-left">Country</th>
                  <th className="px-3 py-2 text-left">Date</th>
                  <th className="px-3 py-2 text-center">Actual</th>
                  <th className="px-3 py-2 text-center">Forecast</th>
                  <th className="px-3 py-2 text-center">Previous</th>
                  <th className="px-3 py-2 text-center">Risk</th>
                  <th className="px-3 py-2 text-left">Policy</th>
                  <th className="px-3 py-2 text-left">Affected</th>
                </tr>
              </thead>
              <tbody>
                {event_context.map((ev: any, i: number) => (
                  <tr key={i} className={`border-b border-gray-800/50 hover:bg-white/[0.02] ${ev.impact === "HIGH" ? "bg-red-500/[0.03]" : ""}`}>
                    <td className="px-3 py-1.5">
                      <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold uppercase ${ev.impact === "HIGH" ? "bg-red-500/20 text-red-400" : ev.impact === "MEDIUM" ? "bg-yellow-500/20 text-yellow-400" : "bg-gray-500/20 text-gray-400"}`}>
                        {ev.impact}
                      </span>
                    </td>
                    <td className="px-3 py-1.5 text-gray-200 max-w-[250px] truncate">{ev.event}</td>
                    <td className="px-3 py-1.5 text-gray-500">{ev.country}</td>
                    <td className="px-3 py-1.5 text-gray-500">{ev.date}</td>
                    <td className="px-3 py-1.5 text-center text-gray-300">{ev.actual ?? "–"}</td>
                    <td className="px-3 py-1.5 text-center text-gray-400">{ev.forecast ?? "–"}</td>
                    <td className="px-3 py-1.5 text-center text-gray-500">{ev.previous ?? "–"}</td>
                    <td className="px-3 py-1.5 text-center"><Badge mode={ev.risk_level === "HIGH" ? "RESTRICTED" : ev.risk_level === "MEDIUM" ? "CAUTION" : "NORMAL"} /></td>
                    <td className="px-3 py-1.5">
                      <span className={`text-[10px] ${ev.trade_policy === "reduce_size" ? "text-orange-400" : ev.trade_policy === "caution" ? "text-yellow-400" : "text-gray-500"}`}>
                        {ev.trade_policy}{ev.size_reduction_pct > 0 ? ` (-${ev.size_reduction_pct}%)` : ""}
                      </span>
                    </td>
                    <td className="px-3 py-1.5 text-gray-600 text-[10px]">{(ev.affected_classes || []).join(", ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ═══ DEBUG PANEL ═══ */}
      <details className="rounded-lg border border-gray-800 bg-[#0d1220]">
        <summary className="px-4 py-3 text-xs font-bold text-gray-500 uppercase tracking-wider font-mono cursor-pointer hover:text-gray-400">
          Debug / Raw Data
        </summary>
        <div className="p-4 border-t border-gray-800">
          <pre className="text-[10px] font-mono text-gray-500 overflow-auto max-h-96 whitespace-pre-wrap">
            {JSON.stringify(data, null, 2)}
          </pre>
        </div>
      </details>
    </div>
  );
}
