"use client";

import { cn } from "@/lib/utils";
import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "outline" | "danger" | "ghost";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  color?: string;
  children: ReactNode;
}

const base =
  "inline-flex items-center justify-center gap-1.5 rounded-lg px-3.5 py-1.5 text-[12px] font-semibold font-mono tracking-wide transition-all duration-150 disabled:opacity-40 disabled:cursor-not-allowed";

const variants: Record<Variant, string> = {
  primary: "border-0",
  outline: "bg-transparent",
  danger:
    "bg-bah-red/10 border border-bah-red/30 text-bah-red hover:bg-bah-red/20",
  ghost:
    "bg-transparent border border-transparent text-bah-subtle hover:text-bah-text hover:bg-white/[0.03]",
};

export function Button({
  variant = "primary",
  color = "#06b6d4",
  children,
  className,
  ...props
}: ButtonProps) {
  const style =
    variant === "primary"
      ? { background: `${color}20`, color }
      : variant === "outline"
        ? { border: `1px solid ${color}50`, color }
        : undefined;

  return (
    <button
      className={cn(base, variants[variant], className)}
      style={style}
      {...props}
    >
      {children}
    </button>
  );
}
