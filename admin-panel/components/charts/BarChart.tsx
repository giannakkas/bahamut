"use client";

import { pct } from "@/lib/utils";

interface BarChartProps {
  data: readonly object[];
  labelKey: string;
  valueKey: string;
  colorKey?: string;
  height?: number;
  formatValue?: (v: number) => string;
}

function getField(obj: object, key: string): unknown {
  return (obj as Record<string, unknown>)[key];
}

export function BarChart({
  data,
  labelKey,
  valueKey,
  colorKey,
  height = 200,
  formatValue,
}: BarChartProps) {
  const maxVal = Math.max(...data.map((d) => Math.abs(Number(getField(d, valueKey)))));

  const fmtVal = formatValue ?? ((v: number) => (v > 0 ? "+" : "") + pct(v));

  return (
    <div
      className="flex items-end gap-1.5 px-1"
      style={{ height }}
    >
      {data.map((d, i) => {
        const val = Number(getField(d, valueKey));
        const h = (Math.abs(val) / maxVal) * (height - 40);
        const color = colorKey ? String(getField(d, colorKey)) : "#06b6d4";

        return (
          <div
            key={i}
            className="flex-1 flex flex-col items-center gap-1"
          >
            <span className="text-[9px] text-bah-subtle">
              {fmtVal(val)}
            </span>
            <div
              className="w-full rounded-t"
              style={{
                height: Math.max(h, 4),
                background: `linear-gradient(180deg, ${color}60, ${color}20)`,
                border: `1px solid ${color}40`,
              }}
            />
            <span className="text-[9px] text-bah-text font-semibold truncate max-w-full">
              {String(getField(d, labelKey))}
            </span>
          </div>
        );
      })}
    </div>
  );
}
