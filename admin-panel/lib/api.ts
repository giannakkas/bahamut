import { apiBase, isMockMode } from "./utils";
import {
  MOCK_SUMMARY,
  MOCK_CONFIG,
  MOCK_RISK,
  MOCK_AUDIT,
  MOCK_OVERRIDES,
  MOCK_LEARNING,
  MOCK_ALERTS,
} from "./mock-data";
import type {
  ConfigMap,
  ConfigOverride,
  ConfigUpdatePayload,
  SystemSummary,
  MarginalRiskData,
  LearningPattern,
  Alert,
  AuditLogEntry,
  AISuggestion,
} from "@/types";

// ─── Auth Token Management ───────────────────────────────────────
// Uses sessionStorage — token cleared on tab close, not vulnerable to
// persistent XSS extraction like localStorage.

const TOKEN_KEY = "bah_token";
const REFRESH_KEY = "bah_refresh";

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return sessionStorage.getItem(TOKEN_KEY);
}

function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return sessionStorage.getItem(REFRESH_KEY);
}

function setToken(token: string): void {
  sessionStorage.setItem(TOKEN_KEY, token);
}

function setRefreshToken(token: string): void {
  sessionStorage.setItem(REFRESH_KEY, token);
}

function clearToken(): void {
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(REFRESH_KEY);
}

/** Parse JWT payload without verification (client-side expiry check). */
function parseJwtPayload(token: string): { exp?: number; sub?: string } | null {
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return null;
    return JSON.parse(atob(parts[1]));
  } catch {
    return null;
  }
}

/** Check if a JWT token is expired (with 30s grace buffer). */
function isTokenExpired(token: string): boolean {
  const payload = parseJwtPayload(token);
  if (!payload?.exp) return true;
  return payload.exp < Math.floor(Date.now() / 1000) + 30;
}

// ─── Fetch Wrapper ───────────────────────────────────────────────

interface FetchOptions extends RequestInit {
  skipAuth?: boolean;
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const FETCH_TIMEOUT_MS = 15_000;

// Logout callback — set by auth store init to avoid circular import
let _onAuthExpired: (() => void) | null = null;
let _refreshInFlight: Promise<string> | null = null;

export function setAuthExpiredCallback(cb: () => void): void {
  _onAuthExpired = cb;
}

/**
 * Attempt to refresh the access token using the refresh token.
 * Deduplicates concurrent refresh attempts via a shared promise.
 */
async function tryRefreshToken(): Promise<string | null> {
  const refresh = getRefreshToken();
  if (!refresh || isTokenExpired(refresh)) return null;

  // Deduplicate: if a refresh is already in flight, wait for it
  if (_refreshInFlight) {
    try {
      return await _refreshInFlight;
    } catch {
      return null;
    }
  }

  _refreshInFlight = (async (): Promise<string | null> => {
    try {
      const res = await fetch(`${apiBase()}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refresh }),
        signal: AbortSignal.timeout(5000),
      });
      if (!res.ok) {
        clearToken();
        return null;
      }
      const data = await res.json();
      const newToken = data.access_token as string;
      if (!newToken) return null;
      setToken(newToken);
      return newToken;
    } catch {
      return null;
    } finally {
      _refreshInFlight = null;
    }
  })();

  return _refreshInFlight;
}

async function apiFetch<T>(path: string, options: FetchOptions = {}, _isRetry = false): Promise<T> {
  const { skipAuth, ...fetchOptions } = options;
  const url = `${apiBase()}${path}`;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(fetchOptions.headers as Record<string, string>),
  };

  if (!skipAuth) {
    let token = getToken();
    if (token && isTokenExpired(token)) {
      // Try auto-refresh before giving up
      const refreshed = await tryRefreshToken();
      if (refreshed) {
        token = refreshed;
      } else {
        clearToken();
        _onAuthExpired?.();
        throw new ApiError("Session expired", 401);
      }
    }
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);

  let res: Response;
  try {
    res = await fetch(url, { ...fetchOptions, headers, signal: controller.signal });
  } catch (err) {
    clearTimeout(timeoutId);
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new ApiError(`Request timed out after ${FETCH_TIMEOUT_MS / 1000}s`, 0);
    }
    throw new ApiError(err instanceof Error ? err.message : "Network error", 0);
  } finally {
    clearTimeout(timeoutId);
  }

  if (!res.ok) {
    const body = await res.text().catch(() => "Unknown error");
    if (res.status === 401 && !_isRetry && !skipAuth) {
      // Try refresh once before giving up
      const refreshed = await tryRefreshToken();
      if (refreshed) {
        return apiFetch<T>(path, options, true);
      }
      clearToken();
      _onAuthExpired?.();
      throw new ApiError("Session expired — please log in again", 401);
    }
    if (res.status === 401) {
      clearToken();
      _onAuthExpired?.();
      throw new ApiError("Session expired — please log in again", 401);
    }
    if (res.status === 403) {
      throw new ApiError("Insufficient permissions", 403);
    }
    throw new ApiError(body, res.status);
  }

  const text = await res.text();
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new ApiError(`Invalid JSON response from ${path}`, res.status);
  }
}

// ─── Auth ────────────────────────────────────────────────────────

export async function login(
  username: string,
  password: string
): Promise<{ token: string; user: string }> {
  if (isMockMode()) {
    await new Promise((r) => setTimeout(r, 500));
    const exp = Math.floor(Date.now() / 1000) + 28800;
    const refreshExp = Math.floor(Date.now() / 1000) + 604800; // 7 days
    const header = btoa(JSON.stringify({ alg: "HS256", typ: "JWT" }));
    const accessPayload = btoa(JSON.stringify({ sub: username, exp, type: "access" }));
    const refreshPayload = btoa(JSON.stringify({ sub: username, exp: refreshExp, type: "refresh" }));
    const token = `${header}.${accessPayload}.mock_sig`;
    setToken(token);
    setRefreshToken(`${header}.${refreshPayload}.mock_sig`);
    return { token, user: username };
  }

  const data = await apiFetch<{ access_token: string; refresh_token: string; user: string }>(
    "/auth/login",
    { method: "POST", body: JSON.stringify({ email: username, password }), skipAuth: true }
  );
  setToken(data.access_token);
  setRefreshToken(data.refresh_token);
  return { token: data.access_token, user: data.user };
}

export function logout(): void {
  // Fire-and-forget: revoke token on server
  try {
    const token = getToken();
    if (token) {
      fetch(`${apiBase()}/auth/logout`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        signal: AbortSignal.timeout(3000),
      }).catch(() => {}); // best-effort, don't block logout
    }
  } catch {
    // ignore
  }
  clearToken();
}

export function isAuthenticated(): boolean {
  const token = getToken();
  if (!token) return false;
  if (isTokenExpired(token)) {
    clearToken();
    return false;
  }
  return true;
}

export async function checkHealth(): Promise<boolean> {
  if (isMockMode()) return true;
  try {
    const res = await fetch(`${apiBase()}/health`, { signal: AbortSignal.timeout(3000) });
    return res.ok;
  } catch {
    return false;
  }
}

// ─── System Summary ──────────────────────────────────────────────

export async function getSummary(): Promise<SystemSummary> {
  if (isMockMode()) return MOCK_SUMMARY;
  return apiFetch<SystemSummary>("/admin/summary");
}

// ─── Config ──────────────────────────────────────────────────────

export async function getConfig(): Promise<ConfigMap> {
  if (isMockMode()) return MOCK_CONFIG;
  return apiFetch<ConfigMap>("/admin/config");
}

export async function updateConfig(payload: ConfigUpdatePayload): Promise<void> {
  if (isMockMode()) { await new Promise((r) => setTimeout(r, 300)); return; }
  await apiFetch("/admin/config", { method: "POST", body: JSON.stringify(payload) });
}

export async function resetConfig(key: string): Promise<void> {
  if (isMockMode()) { await new Promise((r) => setTimeout(r, 200)); return; }
  await apiFetch(`/admin/config/reset/${key}`, { method: "POST" });
}

// ─── Overrides ───────────────────────────────────────────────────

export async function getOverrides(): Promise<ConfigOverride[]> {
  if (isMockMode()) return MOCK_OVERRIDES;
  return apiFetch<ConfigOverride[]>("/admin/config/overrides");
}

export async function createOverride(data: {
  key: string; value: number | string | boolean; ttl: number; reason: string;
}): Promise<void> {
  if (isMockMode()) { await new Promise((r) => setTimeout(r, 300)); return; }
  await apiFetch("/admin/config/overrides", { method: "POST", body: JSON.stringify(data) });
}

export async function removeOverride(key: string): Promise<void> {
  if (isMockMode()) { await new Promise((r) => setTimeout(r, 200)); return; }
  await apiFetch(`/admin/config/overrides/${key}`, { method: "DELETE" });
}

// ─── Risk ────────────────────────────────────────────────────────

export async function getMarginalRisk(): Promise<MarginalRiskData> {
  if (isMockMode()) return MOCK_RISK;
  return apiFetch<MarginalRiskData>("/portfolio/marginal-risk");
}

export async function toggleKillSwitch(active: boolean): Promise<void> {
  if (isMockMode()) { await new Promise((r) => setTimeout(r, 500)); return; }
  await apiFetch("/portfolio/kill-switch", { method: "POST", body: JSON.stringify({ active }) });
}

export async function toggleSafeMode(active: boolean): Promise<void> {
  if (isMockMode()) { await new Promise((r) => setTimeout(r, 300)); return; }
  await apiFetch("/admin/config", { method: "POST", body: JSON.stringify({ key: "safe_mode.enabled", value: active }) });
}

// ─── Audit ───────────────────────────────────────────────────────

export async function getAuditLog(): Promise<AuditLogEntry[]> {
  if (isMockMode()) return MOCK_AUDIT;
  return apiFetch<AuditLogEntry[]>("/admin/audit-log");
}

// ─── Learning ────────────────────────────────────────────────────

export async function getLearningPatterns(): Promise<LearningPattern[]> {
  if (isMockMode()) return MOCK_LEARNING;
  return apiFetch<LearningPattern[]>("/admin/learning/patterns");
}

// ─── Alerts ──────────────────────────────────────────────────────

export async function getAlerts(): Promise<Alert[]> {
  if (isMockMode()) return MOCK_ALERTS;
  return apiFetch<Alert[]>("/admin/alerts");
}

export async function dismissAlert(id: number): Promise<void> {
  if (isMockMode()) return;
  await apiFetch(`/admin/alerts/${id}/dismiss`, { method: "POST" });
}

// ─── AI Optimization ─────────────────────────────────────────────

export async function getAISuggestions(): Promise<AISuggestion[]> {
  if (isMockMode()) {
    await new Promise((r) => setTimeout(r, 2000));
    return [
      { key: "confidence.min_trade", current: 0.65, suggested: 0.7, reason: "Recent win rate suggests higher threshold improves quality" },
      { key: "exposure.max_single", current: 0.15, suggested: 0.12, reason: "Correlation increase warrants lower single-asset exposure" },
      { key: "marginal_risk.threshold", current: 0.15, suggested: 0.13, reason: "Volatility regime shift detected — tighter risk controls recommended" },
      { key: "deleverage.speed", current: 0.3, suggested: 0.4, reason: "Faster deleverage improves drawdown recovery in current regime" },
      { key: "scenario.weight_bear", current: 0.25, suggested: 0.3, reason: "Macro indicators suggest elevated downside probability" },
    ];
  }
  return apiFetch<AISuggestion[]>("/admin/ai/optimize");
}
