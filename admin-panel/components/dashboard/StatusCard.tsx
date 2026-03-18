"use client";

import { Card } from "@/components/ui";

interface StatusCardProps {
  label: string;
  value: string | number;
  color: string;
  subtitle?: string;
  children?: React.ReactNode;
}

export function StatusCard({
  label,
  value,
  color,
  subtitle,
  children,
}: StatusCardProps) {
  return (
    <Card glowColor={color}>
      <div className="text-[10px] text-bah-muted uppercase tracking-widest mb-1">
        {label}
      </div>
      <div
        className="text-lg font-bold tracking-tight"
        style={{ color }}
      >
        {value}
      </div>
      {subtitle && (
        <div className="text-[10px] text-bah-muted mt-1">{subtitle}</div>
      )}
      {children}
    </Card>
  );
}
