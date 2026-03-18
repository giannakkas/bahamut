"use client";

import { Card } from "@/components/ui";
import { DonutChart } from "@/components/charts";
import { pct } from "@/lib/utils";
import type { ScenarioResult } from "@/types";

interface ScenarioChartProps {
  scenarios: ScenarioResult[];
}

export function ScenarioChart({ scenarios }: ScenarioChartProps) {
  return (
    <Card glowColor="#8b5cf6">
      <div className="text-xs font-semibold text-bah-heading mb-4">
        Scenario Analysis
      </div>
      <div className="flex gap-4 items-center">
        <DonutChart
          data={scenarios.map((s) => ({
            value: s.probability * 100,
            color: s.color,
          }))}
          size={120}
        />
        <div className="flex-1 flex flex-col gap-1.5">
          {scenarios.map((s) => (
            <div key={s.name} className="flex items-center gap-2">
              <div
                className="w-2 h-2 rounded-sm shrink-0"
                style={{ background: s.color }}
              />
              <span className="flex-1 text-[11px] text-bah-subtle">
                {s.name}
              </span>
              <span className="text-[10px] text-bah-muted w-10 text-right">
                {pct(s.probability)}
              </span>
              <span
                className={`text-[11px] font-semibold w-12 text-right ${
                  s.impact >= 0 ? "text-bah-green" : "text-bah-red"
                }`}
              >
                {s.impact >= 0 ? "+" : ""}
                {pct(s.impact)}
              </span>
            </div>
          ))}
        </div>
      </div>
    </Card>
  );
}
