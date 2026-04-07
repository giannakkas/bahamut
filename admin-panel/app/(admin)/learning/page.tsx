"use client";

import { useLearningPatterns } from "@/lib/hooks";
import { TopBar } from "@/components/layout/TopBar";
import { Card, Badge, CardSkeleton, EmptyState, QueryError } from "@/components/ui";
import { BarChart } from "@/components/charts";
import { pct, fmtTime } from "@/lib/utils";

export default function LearningPage() {
  const { data: patterns, isLoading, isError, error, refetch } = useLearningPatterns();

  if (isError) {
    return (
      <div>
        <TopBar title="Learning Insights" />
        <QueryError message={error?.message} onRetry={refetch} />
      </div>
    );
  }

  if (isLoading || !patterns) {
    return (
      <div>
        <TopBar title="Learning Insights" />
        <div className="grid grid-cols-2 gap-3">
          <CardSkeleton />
          <CardSkeleton />
        </div>
      </div>
    );
  }

  if (patterns.length === 0) {
    return (
      <div>
        <TopBar title="Learning Insights">
          <Badge color="#f59e0b">Warming Up</Badge>
        </TopBar>
        <Card glowColor="#8b5cf6">
          <div className="text-center py-8">
            <div className="text-4xl mb-3">🧬</div>
            <div className="text-lg font-semibold text-bah-heading mb-2">
              System is Learning
            </div>
            <div className="text-sm text-bah-muted max-w-md mx-auto mb-6">
              Bahamut is analyzing market data and building trading patterns.
              This process requires real trading history to calibrate properly.
            </div>
            <div className="max-w-sm mx-auto space-y-3">
              <WarmupBar label="Closed Trades" current={0} required={20} />
              <WarmupBar label="Learning Samples" current={0} required={50} />
              <WarmupBar label="Calibration Age" current={0} required={3} unit="days" />
            </div>
            <div className="text-xs text-bah-muted mt-6">
              Patterns will appear here automatically as the system gathers enough data.
              <br />No action needed — the engine is working in the background.
            </div>
          </div>
        </Card>
      </div>
    );
  }

  const avgConf = patterns.reduce((s, p) => s + p.confidence, 0) / patterns.length;
  const avgWin = patterns.reduce((s, p) => s + p.win_rate, 0) / patterns.length;
  const totalFreq = patterns.reduce((s, p) => s + p.frequency, 0);

  return (
    <div>
      <TopBar title="Learning Insights">
        <Badge color="#8b5cf6">{patterns.length} patterns detected</Badge>
      </TopBar>

      <div className="grid grid-cols-2 gap-3">
        {/* Stats */}
        <Card glowColor="#8b5cf6">
          <div className="text-xs font-semibold text-bah-heading mb-4">
            Learning Performance
          </div>
          <div className="grid grid-cols-2 gap-3">
            {[
              { label: "Avg Confidence", value: pct(avgConf), color: "#8b5cf6" },
              { label: "Avg Win Rate", value: pct(avgWin), color: "#10b981" },
              { label: "Total Triggers", value: String(totalFreq), color: "#06b6d4" },
              { label: "Active Patterns", value: String(patterns.length), color: "#f59e0b" },
            ].map((m) => (
              <div
                key={m.label}
                className="rounded-lg p-3 text-center"
                style={{ background: `${m.color}08` }}
              >
                <div className="text-[11px] text-bah-muted">{m.label}</div>
                <div className="text-xl font-bold mt-1" style={{ color: m.color }}>
                  {m.value}
                </div>
              </div>
            ))}
          </div>
        </Card>

        {/* Confidence Chart */}
        <Card glowColor="#14b8a6">
          <div className="text-xs font-semibold text-bah-heading mb-4">
            Pattern Confidence
          </div>
          <BarChart
            data={patterns.map((p) => ({
              name: p.pattern.split(" ").slice(0, 2).join(" "),
              value: p.confidence,
              color:
                p.confidence >= 0.8
                  ? "#10b981"
                  : p.confidence >= 0.7
                    ? "#06b6d4"
                    : "#f59e0b",
            }))}
            labelKey="name"
            valueKey="value"
            colorKey="color"
            height={150}
            formatValue={(v) => pct(v)}
          />
        </Card>
      </div>

      {/* Pattern Table */}
      <Card className="mt-3">
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-[12px]">
            <thead>
              <tr>
                {["Pattern", "Freq", "Confidence", "Win Rate", "Last Seen"].map(
                  (h) => (
                    <th
                      key={h}
                      className="px-2.5 py-2 text-left text-[11px] text-bah-muted uppercase tracking-widest border-b border-bah-border/60 font-medium"
                    >
                      {h}
                    </th>
                  )
                )}
              </tr>
            </thead>
            <tbody>
              {[...patterns]
                .sort((a, b) => b.confidence - a.confidence)
                .map((p, i) => (
                  <tr key={i} className="hover:bg-bah-cyan/[0.02] transition-colors">
                    <td className="px-2.5 py-2 text-bah-heading font-medium border-b border-white/[0.02]">
                      {p.pattern}
                    </td>
                    <td className="px-2.5 py-2 text-bah-subtle border-b border-white/[0.02]">
                      {p.frequency}
                    </td>
                    <td className="px-2.5 py-2 border-b border-white/[0.02]">
                      <div className="flex items-center gap-1.5">
                        <div className="w-12 h-1 bg-white/[0.04] rounded overflow-hidden">
                          <div
                            className="h-full rounded"
                            style={{
                              width: pct(p.confidence),
                              background:
                                p.confidence >= 0.8
                                  ? "#10b981"
                                  : p.confidence >= 0.7
                                    ? "#06b6d4"
                                    : "#f59e0b",
                            }}
                          />
                        </div>
                        <span
                          className="text-[12px]"
                          style={{
                            color:
                              p.confidence >= 0.8
                                ? "#10b981"
                                : p.confidence >= 0.7
                                  ? "#06b6d4"
                                  : "#f59e0b",
                          }}
                        >
                          {pct(p.confidence)}
                        </span>
                      </div>
                    </td>
                    <td
                      className="px-2.5 py-2 border-b border-white/[0.02]"
                      style={{
                        color: p.win_rate >= 0.7 ? "#10b981" : "#f59e0b",
                      }}
                    >
                      {pct(p.win_rate)}
                    </td>
                    <td className="px-2.5 py-2 text-bah-muted text-[11px] border-b border-white/[0.02]">
                      {fmtTime(p.last_seen)}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

function WarmupBar({ label, current, required, unit = "" }: { 
  label: string; current: number; required: number; unit?: string 
}) {
  const pctVal = Math.min(100, Math.round((current / required) * 100));
  const met = current >= required;
  return (
    <div>
      <div className="flex justify-between text-xs mb-1">
        <span className="text-bah-muted">{label}</span>
        <span className={met ? "text-green-400" : "text-bah-subtle"}>
          {current}{unit ? ` ${unit}` : ""} / {required}{unit ? ` ${unit}` : ""}
          {met && " ✓"}
        </span>
      </div>
      <div className="h-1.5 bg-white/[0.04] rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-700 ${met ? "bg-green-400" : "bg-bah-purple"}`}
          style={{ width: `${pctVal}%` }}
        />
      </div>
    </div>
  );
}
