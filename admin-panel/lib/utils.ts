import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Merge Tailwind classes safely */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Format number to fixed decimals */
export function fmt(n: number | string | boolean | null | undefined, d = 2): string {
  if (n == null) return "0";
  if (typeof n === "number") return isNaN(n) ? "0" : n.toFixed(d);
  return String(n);
}

/** Format as percentage string */
export function pct(n: number): string {
  if (n == null || isNaN(n)) return "0.0%";
  return `${(n * 100).toFixed(1)}%`;
}

/** Format ISO timestamp to short display */
export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("en-GB", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Format money with $ and commas */
export function fmtMoney(n: number): string {
  if (n == null || isNaN(n)) return "$0.00";
  return `$${n.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

/** Risk level to color class mapping */
export function riskColor(level: string): string {
  switch (level) {
    case "LOW":
      return "text-bah-green";
    case "MEDIUM":
      return "text-bah-amber";
    case "HIGH":
    case "CRITICAL":
      return "text-bah-red";
    default:
      return "text-bah-subtle";
  }
}

/** Risk level to hex color */
export function riskHex(level: string): string {
  switch (level) {
    case "LOW":
      return "#10b981";
    case "MEDIUM":
      return "#f59e0b";
    case "HIGH":
    case "CRITICAL":
      return "#ef4444";
    default:
      return "#64748b";
  }
}

/** Returns true if the env is in mock mode */
export function isMockMode(): boolean {
  return process.env.NEXT_PUBLIC_MOCK_MODE === "true";
}

/** API base URL — MUST be set via NEXT_PUBLIC_API_URL */
export function apiBase(): string {
  const url = process.env.NEXT_PUBLIC_API_URL;
  if (!url) {
    console.error("NEXT_PUBLIC_API_URL is not set. API calls will fail.");
    return "http://localhost:8000";
  }
  return url.replace(/\/+$/, ""); // strip trailing slashes
}

/** Refresh interval from env */
export function refreshInterval(): number {
  const val = process.env.NEXT_PUBLIC_REFRESH_INTERVAL;
  return val ? parseInt(val, 10) : 5000;
}
