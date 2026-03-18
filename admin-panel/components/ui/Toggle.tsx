"use client";

import { cn } from "@/lib/utils";

interface ToggleProps {
  value: boolean;
  onChange: (val: boolean) => void;
  disabled?: boolean;
}

export function Toggle({ value, onChange, disabled }: ToggleProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={value}
      disabled={disabled}
      onClick={() => onChange(!value)}
      className={cn(
        "relative inline-flex h-5 w-[38px] shrink-0 rounded-full border transition-colors duration-200",
        value
          ? "bg-bah-cyan/30 border-bah-cyan/40"
          : "bg-white/[0.06] border-white/10",
        disabled && "opacity-50 cursor-not-allowed"
      )}
    >
      <span
        className={cn(
          "pointer-events-none inline-block h-3.5 w-3.5 rounded-full transition-all duration-200 mt-[2px]",
          value
            ? "translate-x-[19px] bg-bah-cyan shadow-[0_0_8px_rgba(6,182,212,0.4)]"
            : "translate-x-[2px] bg-bah-muted"
        )}
      />
    </button>
  );
}
