"use client";

import { useUIStore } from "@/store/ui";
import { cn } from "@/lib/utils";

const typeStyles: Record<string, string> = {
  success:
    "bg-bah-green/10 border-bah-green/25 text-bah-green",
  error:
    "bg-bah-red/10 border-bah-red/25 text-bah-red",
  warning:
    "bg-bah-amber/10 border-bah-amber/25 text-bah-amber",
  info: "bg-bah-cyan/10 border-bah-cyan/25 text-bah-cyan",
};

export function ToastProvider() {
  const toasts = useUIStore((s) => s.toasts);

  if (toasts.length === 0) return null;

  return (
    <div className="fixed top-4 right-4 z-[2000] flex flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={cn(
            "rounded-lg border px-4 py-2.5 text-xs font-mono backdrop-blur-xl max-w-xs animate-fade-in",
            typeStyles[t.type] ?? typeStyles.info
          )}
        >
          {t.message}
        </div>
      ))}
    </div>
  );
}
