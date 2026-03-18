"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as api from "./api";
import { refreshInterval } from "./utils";
import type { ConfigUpdatePayload } from "@/types";

// ─── Query Keys ──────────────────────────────────────────────────

export const queryKeys = {
  summary: ["summary"] as const,
  config: ["config"] as const,
  overrides: ["overrides"] as const,
  risk: ["marginal-risk"] as const,
  audit: ["audit-log"] as const,
  learning: ["learning"] as const,
  alerts: ["alerts"] as const,
};

// ─── Summary ─────────────────────────────────────────────────────

export function useSummary() {
  return useQuery({
    queryKey: queryKeys.summary,
    queryFn: api.getSummary,
    refetchInterval: refreshInterval(),
    staleTime: 3000,
  });
}

// ─── Config ──────────────────────────────────────────────────────

export function useConfig() {
  return useQuery({
    queryKey: queryKeys.config,
    queryFn: api.getConfig,
    staleTime: 10000,
  });
}

export function useUpdateConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: ConfigUpdatePayload) => api.updateConfig(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.config });
      qc.invalidateQueries({ queryKey: queryKeys.audit });
    },
  });
}

export function useResetConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (key: string) => api.resetConfig(key),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.config });
      qc.invalidateQueries({ queryKey: queryKeys.audit });
    },
  });
}

// ─── Overrides ───────────────────────────────────────────────────

export function useOverrides() {
  return useQuery({
    queryKey: queryKeys.overrides,
    queryFn: api.getOverrides,
    refetchInterval: refreshInterval(),
  });
}

export function useCreateOverride() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.createOverride,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.overrides });
      qc.invalidateQueries({ queryKey: queryKeys.audit });
    },
  });
}

export function useRemoveOverride() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.removeOverride,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.overrides });
    },
  });
}

// ─── Risk ────────────────────────────────────────────────────────

export function useMarginalRisk() {
  return useQuery({
    queryKey: queryKeys.risk,
    queryFn: api.getMarginalRisk,
    refetchInterval: refreshInterval(),
    staleTime: 3000,
  });
}

export function useToggleKillSwitch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (active: boolean) => api.toggleKillSwitch(active),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.summary });
      qc.invalidateQueries({ queryKey: queryKeys.audit });
    },
  });
}

export function useToggleSafeMode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (active: boolean) => api.toggleSafeMode(active),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.summary });
      qc.invalidateQueries({ queryKey: queryKeys.config });
      qc.invalidateQueries({ queryKey: queryKeys.audit });
    },
  });
}

// ─── Audit ───────────────────────────────────────────────────────

export function useAuditLog() {
  return useQuery({
    queryKey: queryKeys.audit,
    queryFn: api.getAuditLog,
    staleTime: 5000,
  });
}

// ─── Learning ────────────────────────────────────────────────────

export function useLearningPatterns() {
  return useQuery({
    queryKey: queryKeys.learning,
    queryFn: api.getLearningPatterns,
    staleTime: 30000,
  });
}

// ─── Alerts ──────────────────────────────────────────────────────

export function useAlerts() {
  return useQuery({
    queryKey: queryKeys.alerts,
    queryFn: api.getAlerts,
    refetchInterval: refreshInterval(),
  });
}

export function useDismissAlert() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.dismissAlert(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.alerts });
    },
  });
}

// ─── AI Optimization ─────────────────────────────────────────────

export function useAISuggestions() {
  return useMutation({
    mutationFn: api.getAISuggestions,
  });
}
