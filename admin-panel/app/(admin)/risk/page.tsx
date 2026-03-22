"use client";

import { useState } from "react";
import {
  useSummary,
  useMarginalRisk,
  useToggleKillSwitch,
  useToggleSafeMode,
} from "@/lib/hooks";
import { useUIStore } from "@/store/ui";
import { TopBar } from "@/components/layout/TopBar";
import { KillSwitchPanel } from "@/components/risk/KillSwitchPanel";
import { ScenarioChart } from "@/components/risk/ScenarioChart";
import { Card, Button, CardSkeleton, QueryError } from "@/components/ui";
import { RiskGauge, BarChart } from "@/components/charts";
import { pct, fmt } from "@/lib/utils";

export default function RiskPage() {
  const { data: summary, isLoading: loadingSum, isError: errSum, error: errSumData, refetch: retrySum } = useSummary();
  const { data: risk, isLoading: loadingRisk, isError: errRisk, error: errRiskData, refetch: retryRisk } = useMarginalRisk();
  const toggleKill = useToggleKillSwitch();
  const toggleSafe = useToggleSafeMode();
  const addToast = useUIStore((s) => s.addToast);
  const [simMode, setSimMode] = useState(false);

  if (errSum || errRisk) {
    return (
      <div>
        <TopBar title="Risk & Kill Switch Control" />
        <QueryError
          message={(errSumData ?? errRiskData)?.message}
          onRetry={() => { retrySum(); retryRisk(); }}
        />
      </div>
    );
  }

  if (loadingSum || loadingRisk || !summary || !risk) {
    return (
      <div>
        <TopBar title="Risk & Kill Switch Control" />
        <div className="space-y-3">
          <CardSkeleton />
          <CardSkeleton />
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            <CardSkeleton />
            <CardSkeleton />
            <CardSkeleton />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div>
      <TopBar title="Risk & Kill Switch Control">
        <Button
          color="#8b5cf6"
          onClick={() => setSimMode(!simMode)}
        >
          {simMode ? "⬤ Simulation ON" : "🧪 Simulation Mode"}
        </Button>
      </TopBar>

      {/* Kill Switch + Safe Mode */}
      <KillSwitchPanel
        killSwitch={summary.kill_switch}
        safeMode={summary.safe_mode}
        onToggleKill={async (active) => {
          try {
            await toggleKill.mutateAsync(active);
            addToast(
              "warning",
              active ? "Kill switch ACTIVATED" : "Trading RESUMED"
            );
          } catch {
            addToast("error", "Failed to toggle kill switch");
          }
        }}
        onToggleSafe={async () => {
          try {
            await toggleSafe.mutateAsync(!summary.safe_mode.active);
            addToast(
              "info",
              summary.safe_mode.active ? "Safe mode DISABLED" : "Safe mode ENABLED"
            );
          } catch {
            addToast("error", "Failed to toggle safe mode");
          }
        }}
        toggling={toggleKill.isPending || toggleSafe.isPending}
      />

      {/* Risk Metrics */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 mt-3">
        <Card glowColor="#ef4444">
          <div className="text-[10px] text-bah-muted uppercase tracking-widest mb-1">
            Total Marginal Risk
          </div>
          <div
            className="text-[22px] font-bold"
            style={{
              color: risk.total_risk > 0.15 ? "#ef4444" : "#f59e0b",
            }}
          >
            {pct(risk.total_risk)}
          </div>
          <RiskGauge value={risk.total_risk} />
        </Card>

        <Card glowColor="#10b981">
          <div className="text-[10px] text-bah-muted uppercase tracking-widest mb-1">
            Expected Return
          </div>
          <div className="text-[22px] font-bold text-bah-green">
            +{pct(risk.expected_return)}
          </div>
          <div className="text-[10px] text-bah-muted mt-2">
            Return/Risk:{" "}
            <span className="text-bah-cyan">
              {fmt(risk.expected_return / risk.total_risk)}x
            </span>
          </div>
        </Card>

        <Card glowColor="#06b6d4">
          <div className="text-[10px] text-bah-muted uppercase tracking-widest mb-1">
            Quality Ratio
          </div>
          <div className="text-[22px] font-bold text-bah-cyan">
            {fmt(risk.quality_ratio)}
          </div>
          <div className="h-1.5 bg-white/[0.04] rounded mt-3 overflow-hidden">
            <div
              className="h-full rounded bg-gradient-to-r from-bah-cyan to-bah-purple"
              style={{ width: pct(risk.quality_ratio) }}
            />
          </div>
        </Card>
      </div>

      {/* Scenario Impact */}
      <div className="mt-3">
        <Card glowColor="#8b5cf6">
          <div className="text-xs font-semibold text-bah-heading mb-4">
            Scenario Impact Analysis
          </div>
          <BarChart
            data={risk.scenarios}
            labelKey="name"
            valueKey="impact"
            colorKey="color"
            height={180}
          />
        </Card>
      </div>

      {/* Simulation Panel */}
      {simMode && (
        <Card
          glowColor="#8b5cf6"
          className="mt-3 border-bah-purple/30"
        >
          <div className="text-xs font-semibold text-bah-purple mb-3">
            🧪 Simulation Mode
          </div>
          <p className="text-[11px] text-bah-subtle mb-4">
            Run hypothetical scenarios without executing trades. Connect
            a simulation API endpoint to see projected outcomes here.
          </p>
          <div className="rounded-lg bg-bah-purple/[0.06] p-6 text-center">
            <div className="text-[10px] text-bah-muted">
              Simulation results will appear here when{" "}
              <code className="text-bah-purple">POST /admin/simulate</code>{" "}
              is implemented on the backend.
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}
