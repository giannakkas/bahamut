"use client";

interface DonutDatum {
  value: number;
  color: string;
}

interface DonutChartProps {
  data: DonutDatum[];
  size?: number;
}

export function DonutChart({ data, size = 140 }: DonutChartProps) {
  const total = data.reduce((s, d) => s + d.value, 0);
  const r = size / 2 - 10;
  const cx = size / 2;
  const cy = size / 2;

  let cumAngle = -90;

  return (
    <svg width={size} height={size}>
      {data.map((d, i) => {
        const angle = (d.value / total) * 360;
        const startRad = (cumAngle * Math.PI) / 180;
        const endRad = ((cumAngle + angle) * Math.PI) / 180;
        const x1 = cx + r * Math.cos(startRad);
        const y1 = cy + r * Math.sin(startRad);
        const x2 = cx + r * Math.cos(endRad);
        const y2 = cy + r * Math.sin(endRad);
        const large = angle > 180 ? 1 : 0;
        const path = `M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2} Z`;
        cumAngle += angle;

        return (
          <path
            key={i}
            d={path}
            fill={d.color}
            opacity={0.8}
            stroke="#0a0e17"
            strokeWidth={2}
          />
        );
      })}
      <circle cx={cx} cy={cy} r={r * 0.55} fill="#0a0e17" />
    </svg>
  );
}
