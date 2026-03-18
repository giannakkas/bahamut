export type ConfigValueType = "float" | "int" | "bool" | "string";

export interface ConfigMeta {
  value: number | string | boolean;
  type: ConfigValueType;
  category: string;
  description: string;
  default: number | string | boolean;
  min?: number;
  max?: number;
  options?: string[];
}

export type ConfigMap = Record<string, ConfigMeta>;

export interface ConfigGroup {
  category: string;
  label: string;
  icon: string;
  color: string;
  items: ConfigEntry[];
}

export interface ConfigEntry extends ConfigMeta {
  key: string;
}

export interface ConfigUpdatePayload {
  key: string;
  value: number | string | boolean;
}

export interface ConfigOverride {
  key: string;
  value: number | string | boolean;
  ttl: number;
  created: string;
  expires: string;
  reason: string;
}

export const CATEGORY_META: Record<
  string,
  { label: string; icon: string; color: string }
> = {
  scenario: { label: "Scenarios", icon: "🎯", color: "#8b5cf6" },
  marginal_risk: { label: "Marginal Risk", icon: "📉", color: "#ef4444" },
  quality_ratio: { label: "Quality Ratio", icon: "💎", color: "#06b6d4" },
  exposure: { label: "Exposure", icon: "📊", color: "#f59e0b" },
  kill_switch: { label: "Kill Switch", icon: "🚨", color: "#dc2626" },
  safe_mode: { label: "Safe Mode", icon: "🛡️", color: "#10b981" },
  deleverage: { label: "Deleverage", icon: "⚖️", color: "#a855f7" },
  allocator: { label: "Allocator", icon: "🧮", color: "#3b82f6" },
  confidence: { label: "Confidence", icon: "🧠", color: "#14b8a6" },
  profile: { label: "Profile", icon: "👤", color: "#ec4899" },
  readiness: { label: "Readiness", icon: "✅", color: "#22c55e" },
};
