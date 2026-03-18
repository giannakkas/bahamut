"use client";

import { pct } from "@/lib/utils";

interface RiskGaugeProps {
  value: number;
  max?: number;
  size?: number;
}

function describeArc(
  cx: number,
  cy: number,
  r: number,
  startAngle: number,
  endAngle: number
): string {
  const sr = (startAngle * Math.PI) / 180;
  const er = (endAngle * Math.PI) / 180;
  const x1 = cx + r * Math.cos(sr);
  const y1 = cy + r * Math.sin(sr);
  const x2 = cx + r * Math.cos(er);
  const y2 = cy + r * Math.sin(er);
  const large = endAngle - startAngle > 180 ? 1 : 0;
  return `M ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2}`;
}

export function RiskGauge({ value, max = 0.3, size = 120 }: RiskGaugeProps) {
  const pctVal = Math.min(value / max, 1);
  const color =
    pctVal < 0.4 ? "#10b981" : pctVal < 0.7 ? "#f59e0b" : "#ef4444";
  const angle = -135 + pctVal * 270;
  const r = size / 2 - 12;
  const cx = size / 2;
  const cy = size / 2;

  return (
    <svg
      width={size}
      height={size * 0.7}
      viewBox={`0 0 ${size} ${size * 0.75}`}
    >
      <path
        d={describeArc(cx, cy, r, -135, 135)}
        fill="none"
        stroke="rgba(255,255,255,0.06)"
        strokeWidth={8}
        strokeLinecap="round"
      />
      <path
        d={describeArc(cx, cy, r, -135, angle)}
        fill="none"
        stroke={color}
        strokeWidth={8}
        strokeLinecap="round"
      />
      <text
        x={cx}
        y={cy + 4}
        textAnchor="middle"
        fill={color}
        fontSize={18}
        fontWeight="bold"
        fontFamily="inherit"
      >
        {pct(value)}
      </text>
      <text
        x={cx}
        y={cy + 18}
        textAnchor="middle"
        fill="#4a5568"
        fontSize={8}
        fontFamily="inherit"
      >
        RISK
      </text>
    </svg>
  );
}
