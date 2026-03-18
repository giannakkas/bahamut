"use client";

import type { ReactNode } from "react";

interface TopBarProps {
  title: string;
  subtitle?: string;
  children?: ReactNode;
}

export function TopBar({ title, subtitle, children }: TopBarProps) {
  return (
    <div className="flex items-center justify-between flex-wrap gap-3 mb-5">
      <div>
        <h1 className="text-xl font-bold text-bah-heading tracking-tight">
          {title}
        </h1>
        {subtitle && (
          <p className="text-[10px] text-bah-muted mt-0.5">{subtitle}</p>
        )}
      </div>
      {children && <div className="flex items-center gap-2">{children}</div>}
    </div>
  );
}
