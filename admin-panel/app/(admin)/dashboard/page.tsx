"use client";

import { useState, useEffect } from "react";
import { useSummary, useMarginalRisk } from "@/lib/hooks";
import { fmtTime, fmtMoney, pct, fmt, apiBase } from "@/lib/utils";
import { TopBar } from "@/components/layout/TopBar";
import { StatusCard } from "@/components/dashboard/StatusCard";
import { Card, Badge, Pulse, CardSkeleton, QueryError } from "@/components/ui";
import { Sparkline, RiskGauge, DonutChart } from "@/components/charts";
import { ScenarioChart } from "@/components/risk/ScenarioChart";

export default function DashboardPage() {
  const { data: summary, isLoading: loadingSum, isError: errSum, error: errSumData, refetch: retrySum } = useSummary();
  const { data: risk, isLoading: loadingRisk, isError: errRisk, error: errRiskData, refetch: retryRisk } = useMarginalRisk();

  // Extra data fetched directly
  const [learning, setLearning] = useState<any>(null);
  const [killRecovery, setKillRecovery] = useState<any>(null);
  const [recentPositions, setRecentPositions] = useState<any[]>([]);
  const token = typeof window !== "undefined" ? sessionStorage.getItem("bah_token") : null;

  useEffect(() => {
    if (!token) return;
    const headers = { Authorization: `Bearer ${token}` };
    Promise.all([
      fetch(`${apiBase()}/trust/learning-progress`, { headers }).then(r => r.json()).catch(() => null),
      fetch(`${apiBase()}/trust/kill-switch-status`, { headers }).then(r => r.json()).catch(() => null),
      fetch(`${apiBase()}/paper-trading/positions?limit=5`, { headers }).then(r => r.json()).catch(() => ({ positions: [] })),
    ]).then(([lp, ks, pos]) => {
      setLearning(lp);
      setKillRecovery(ks);
      setRecentPositions(pos?.positions?.slice(0, 5) || []);
    });
  }, [token]);

  if (errSum || errRisk) {
    return (
      <div>
        <TopBar title="System Overview" />
        <QueryError message={(errSumData ?? errRiskData)?.message} onRetry={() => { retrySum(); retryRisk(); }} />
      </div>
    );
  }

  if (loadingSum || loadingRisk || !summary || !risk) {
    return (
      <div>
        <TopBar title="System Overview" />
        <div className="grid grid-cols-5 gap-3">
          <CardSkeleton /><CardSkeleton /><CardSkeleton /><CardSkeleton /><CardSkeleton />
        </div>
      </div>
    );
  }

  const riskColor = summary.risk_level === "LOW" ? "#10b981" : summary.risk_level === "MEDIUM" ? "#f59e0b" : "#ef4444";
  const readinessColor = summary.readiness.score >= 0.8 ? "#10b981" : summary.readiness.score >= 0.6 ? "#f59e0b" : "#ef4444";
  const warmupMode = summary.warmup?.mode || learning?.status || "unknown";
  const warmupProgress = summary.warmup?.progress ?? learning?.progress ?? 0;

  return (
    <div>
      <TopBar title="System Overview" subtitle={`Last cycle: ${fmtTime(summary.last_cycle)}`}>
        <Badge color={summary.kill_switch.active ? "#ef4444" : "#10b981"}>
          ⬤ {summary.kill_switch.active ? "KILL ACTIVE" : "TRADING"}
        </Badge>
        <Badge color={summary.safe_mode.active ? "#f59e0b" : "#10b981"}>
          {summary.safe_mode.active ? "SAFE MODE" : "NORMAL"}
        </Badge>
      </TopBar>

      {/* KPI Row */}
      <div className="grid grid-cols-6 gap-3">
        <StatusCard label="Portfolio Value" value={fmtMoney(summary.portfolio_value)} color="#06b6d4" />
        <StatusCard label="Daily P&L" value={`${summary.daily_pnl >= 0 ? "+" : ""}${fmtMoney(summary.daily_pnl)}`} color={summary.daily_pnl >= 0 ? "#10b981" : "#ef4444"} subtitle={`${summary.daily_pnl_pct >= 0 ? "+" : ""}${summary.daily_pnl_pct}%`} />
        <StatusCard label="Open Positions" value={summary.open_positions} color="#8b5cf6" />
        <StatusCard label="Agents Active" value={`${summary.agents_active}/6`} color="#3b82f6" />
        <StatusCard label="Active Constraints" value={summary.active_constraints} color="#f59e0b" />
        <StatusCard label="System Mode" value={warmupMode === "active" ? "ACTIVE" : "WARMUP"} color={warmupMode === "active" ? "#10b981" : "#f59e0b"} />
      </div>

      {/* Main Grid */}
      <div className="grid grid-cols-4 gap-3 mt-3">
        {/* Kill Switch — detailed */}
        <Card glowColor={summary.kill_switch.active ? "#ef4444" : "#10b981"}>
          <div className="text-[10px] text-bah-muted uppercase tracking-widest mb-1">Kill Switch</div>
          <div className="flex items-center gap-2 mt-1">
            <Pulse color={summary.kill_switch.active ? "#ef4444" : "#10b981"} />
            <span className="text-base font-bold" style={{ color: summary.kill_switch.active ? "#ef4444" : "#10b981" }}>
              {summary.kill_switch.active ? "ACTIVE" : "INACTIVE"}
            </span>
          </div>
          {summary.kill_switch.reason && (
            <div className="text-[11px] text-bah-red mt-2">Reason: {summary.kill_switch.reason}</div>
          )}
          {killRecovery && killRecovery.status !== "normal" && (
            <div className="mt-2 text-[10px]">
              <span className={killRecovery.status === "recovering" ? "text-amber-400" : killRecovery.status === "cooldown" ? "text-red-400" : "text-bah-muted"}>
                Recovery: {killRecovery.status}
              </span>
              {killRecovery.size_multiplier < 1 && (
                <span className="text-bah-muted ml-1">Size ×{killRecovery.size_multiplier}</span>
              )}
            </div>
          )}
          <div className="text-[10px] text-bah-muted mt-2">
            Last triggered: {fmtTime(summary.kill_switch.last_triggered)}
          </div>
          {killRecovery?.trigger_count_today > 0 && (
            <div className="text-[10px] text-amber-400 mt-0.5">
              Triggers today: {killRecovery.trigger_count_today}
            </div>
          )}
        </Card>

        {/* Risk Level */}
        <Card glowColor={riskColor}>
          <div className="text-[10px] text-bah-muted uppercase tracking-widest mb-1">Risk Level</div>
          <div className="text-[22px] font-bold" style={{ color: riskColor }}>{summary.risk_level}</div>
          <div className="mt-2"><RiskGauge value={risk.total_risk} /></div>
        </Card>

        {/* Readiness */}
        <Card glowColor={readinessColor}>
          <div className="text-[10px] text-bah-muted uppercase tracking-widest mb-1">Readiness Score</div>
          <div className="text-[22px] font-bold" style={{ color: readinessColor }}>{pct(summary.readiness.score)}</div>
          <div className="text-sm font-bold mt-0.5" style={{ color: readinessColor }}>Grade: {summary.readiness.grade}</div>
          <div className="mt-3 flex flex-col gap-1.5">
            {Object.entries(summary.readiness.components).map(([k, v]: [string, any]) => (
              <div key={k} className="flex items-center gap-2">
                <span className="text-[10px] text-bah-subtle w-12 capitalize">{k}</span>
                <div className="flex-1 h-1 bg-white/[0.04] rounded overflow-hidden">
                  <div className="h-full rounded transition-all duration-500" style={{ width: pct(v), background: v >= 0.8 ? "#10b981" : "#f59e0b" }} />
                </div>
                <span className="text-[10px] text-bah-subtle w-9 text-right">{pct(v)}</span>
              </div>
            ))}
          </div>
        </Card>

        {/* Confidence */}
        <Card glowColor="#14b8a6">
          <div className="text-[10px] text-bah-muted uppercase tracking-widest mb-1">Confidence Score</div>
          <div className="text-[22px] font-bold text-bah-teal">{pct(summary.confidence.score)}</div>
          <div className="flex items-center gap-1.5 mt-1">
            <Badge color={summary.confidence.trend === "rising" ? "#10b981" : summary.confidence.trend === "falling" ? "#ef4444" : "#64748b"}>
              {summary.confidence.trend === "rising" ? "↑" : summary.confidence.trend === "falling" ? "↓" : "→"} {summary.confidence.trend}
            </Badge>
          </div>
          <div className="mt-3"><Sparkline data={summary.confidence.history} color="#14b8a6" width={160} height={32} /></div>
        </Card>
      </div>

      {/* Learning Progress + Recent Trades */}
      <div className="grid grid-cols-2 gap-3 mt-3">
        {/* Learning / Warmup Progress */}
        <Card glowColor="#8b5cf6">
          <div className="flex justify-between items-center mb-3">
            <div className="text-xs font-semibold text-bah-heading">Learning Progress</div>
            <Badge color={warmupMode === "active" ? "#10b981" : warmupMode === "learning" ? "#06b6d4" : "#f59e0b"}>
              {warmupMode === "active" ? "READY" : warmupMode === "learning" ? "LEARNING" : "WARMUP"}
            </Badge>
          </div>
          <div className="h-2 bg-white/[0.04] rounded-full overflow-hidden mb-3">
            <div className="h-full bg-purple-500 rounded-full transition-all duration-700" style={{ width: `${warmupProgress * 100}%` }} />
          </div>
          <div className="grid grid-cols-3 gap-2 text-center">
            <div className="bg-white/[0.02] rounded-lg p-2">
              <div className="text-lg font-bold text-bah-heading">{learning?.samples_collected || 0}</div>
              <div className="text-[9px] text-bah-muted">Samples</div>
            </div>
            <div className="bg-white/[0.02] rounded-lg p-2">
              <div className="text-lg font-bold text-bah-heading">{learning?.patterns_detected || 0}</div>
              <div className="text-[9px] text-bah-muted">Patterns</div>
            </div>
            <div className="bg-white/[0.02] rounded-lg p-2">
              <div className="text-lg font-bold text-bah-heading">{learning?.closed_trades || 0}</div>
              <div className="text-[9px] text-bah-muted">Closed Trades</div>
            </div>
          </div>
          {learning?.next_milestone && (
            <div className="text-[10px] text-bah-muted mt-2">Next: {learning.next_milestone}</div>
          )}
        </Card>

        {/* Recent Positions */}
        <Card glowColor="#06b6d4">
          <div className="text-xs font-semibold text-bah-heading mb-3">Recent Positions</div>
          {recentPositions.length > 0 ? (
            <div className="space-y-1">
              {recentPositions.map((p: any, i: number) => (
                <div key={i} className="flex items-center justify-between py-1.5 border-b border-white/[0.03] last:border-0">
                  <div className="flex items-center gap-2">
                    <span className={`text-xs font-bold ${p.direction === "LONG" ? "text-green-400" : "text-red-400"}`}>
                      {p.direction === "LONG" ? "▲" : "▼"}
                    </span>
                    <span className="text-[11px] font-semibold text-bah-heading">{p.asset}</span>
                    <span className="text-[10px] text-bah-muted">{p.status}</span>
                  </div>
                  <div className="text-right">
                    <span className={`text-[11px] font-mono font-semibold ${(p.unrealized_pnl || p.realized_pnl || 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                      {(p.unrealized_pnl || p.realized_pnl || 0) >= 0 ? "+" : ""}${(p.unrealized_pnl || p.realized_pnl || 0).toFixed(2)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-[11px] text-bah-muted text-center py-4">No positions yet</div>
          )}
        </Card>
      </div>

      {/* Portfolio Intelligence Row */}
      <div className="grid grid-cols-2 gap-3 mt-3">
        <Card glowColor="#06b6d4">
          <div className="flex justify-between items-center mb-3">
            <div className="text-xs font-semibold text-bah-heading">Top Risk Contributors</div>
            <div className="text-[10px] text-bah-muted">Quality: <span className="text-bah-cyan">{fmt(risk.quality_ratio)}</span></div>
          </div>
          {risk.contributors && risk.contributors.length > 0 ? risk.contributors.map((c: any) => (
            <div key={c.asset} className="flex items-center gap-2 py-1">
              <span className="w-9 text-[11px] font-semibold text-bah-heading">{c.asset}</span>
              <div className="flex-1 h-1.5 bg-white/[0.04] rounded overflow-hidden">
                <div className="h-full rounded bg-gradient-to-r from-bah-cyan/50 to-bah-cyan/20" style={{ width: `${c.contribution_pct}%` }} />
              </div>
              <span className="text-[10px] text-bah-subtle w-10 text-right">{c.contribution_pct}%</span>
            </div>
          )) : (
            <div className="text-[11px] text-bah-muted text-center py-4">No risk contributors yet</div>
          )}
        </Card>
        <ScenarioChart scenarios={risk.scenarios || []} />
      </div>
    </div>
  );
}
