"use client";

import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

interface CardProps {
  children: ReactNode;
  glowColor?: string;
  className?: string;
  style?: React.CSSProperties;
  onClick?: () => void;
}

export function Card({ children, glowColor, className, style, onClick }: CardProps) {
  return (
    <div
      onClick={onClick}
      style={style}
      className={cn(
        "relative overflow-hidden rounded-xl border border-bah-border bg-bah-surface/80 p-4 backdrop-blur-xl",
        onClick && "cursor-pointer",
        className
      )}
    >
      {glowColor && (
        <div
          className="absolute top-0 left-0 right-0 h-0.5 opacity-60"
          style={{
            background: `linear-gradient(90deg, transparent, ${glowColor}, transparent)`,
          }}
        />
      )}
      {children}
    </div>
  );
}
