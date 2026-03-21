"use client";
import { useState, useEffect, useCallback } from "react";
import { apiBase } from "@/lib/utils";

export default function NotificationSettings() {
  const [settings, setSettings] = useState<any>(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const [message, setMessage] = useState<{ type: string; text: string } | null>(null);
  const [loading, setLoading] = useState(true);

  // Form state
  const [form, setForm] = useState({
    telegram_enabled: false,
    telegram_bot_token: "",
    telegram_chat_id: "",
    email_enabled: false,
    email_smtp_host: "smtp-relay.brevo.com",
    email_smtp_port: 587,
    email_smtp_user: "",
    email_smtp_pass: "",
    email_from: "",
    email_to: "",
    level_critical: true,
    level_warning: true,
    level_info: false,
  });

  const token = typeof window !== "undefined" ? sessionStorage.getItem("bah_token") : null;

  const api = useCallback(async (path: string, opts?: any) => {
    try {
      const r = await fetch(`${apiBase()}/monitoring${path}`, {
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        ...opts,
      });
      if (r.ok) return await r.json();
      const err = await r.json().catch(() => ({}));
      return { error: err.detail || r.statusText };
    } catch (e: any) {
      return { error: e.message };
    }
  }, [token]);

  const load = useCallback(async () => {
    const data = await api("/settings");
    if (data && !data.error) {
      setSettings(data);
      setForm((prev) => ({
        ...prev,
        telegram_enabled: data.telegram_enabled ?? false,
        telegram_bot_token: data.telegram_bot_token?.startsWith("●") ? "" : (data.telegram_bot_token || ""),
        telegram_chat_id: data.telegram_chat_id || "",
        email_enabled: data.email_enabled ?? false,
        email_smtp_host: data.email_smtp_host || "smtp-relay.brevo.com",
        email_smtp_port: data.email_smtp_port || 587,
        email_smtp_user: data.email_smtp_user || "",
        email_smtp_pass: data.email_smtp_pass?.startsWith("●") ? "" : (data.email_smtp_pass || ""),
        email_from: data.email_from || "",
        email_to: data.email_to || "",
        level_critical: data.level_critical ?? true,
        level_warning: data.level_warning ?? true,
        level_info: data.level_info ?? false,
      }));
    }
    setLoading(false);
  }, [api]);

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setSaving(true);
    setMessage(null);
    // Only send non-empty values (don't overwrite masked passwords with empty)
    const payload: any = { ...form };
    if (!payload.telegram_bot_token) delete payload.telegram_bot_token;
    if (!payload.email_smtp_pass) delete payload.email_smtp_pass;

    const res = await api("/settings", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    setSaving(false);
    if (res?.ok) {
      setMessage({ type: "success", text: "Settings saved" });
      load();
    } else {
      setMessage({ type: "error", text: res?.error || "Failed to save" });
    }
  };

  const test = async (channel: "telegram" | "email") => {
    setTesting(channel);
    setMessage(null);

    // Send current form values so test works without saving first
    const body = channel === "email" ? {
      api_key: form.email_smtp_pass || undefined,
      from_email: form.email_from,
      to_email: form.email_to,
    } : undefined;

    const res = await api(`/settings/test/${channel}`, {
      method: "POST",
      body: body ? JSON.stringify(body) : undefined,
    });
    setTesting(null);
    if (res?.ok) {
      setMessage({ type: "success", text: res.message || `Test ${channel} sent! Check your ${channel === "telegram" ? "Telegram" : "inbox"}.` });
    } else {
      setMessage({ type: "error", text: res?.error || `Test ${channel} failed` });
    }
  };

  const set = (key: string, value: any) => setForm((p) => ({ ...p, [key]: value }));

  if (loading) return <div className="p-8 text-bah-muted">Loading settings...</div>;

  return (
    <div className="p-6 max-w-3xl space-y-6">
      <div>
        <h1 className="text-xl font-bold text-bah-heading">Notification Settings</h1>
        <p className="text-xs text-bah-muted mt-1">Configure Telegram and Email alerts for trading events</p>
      </div>

      {message && (
        <div className={`px-4 py-3 rounded-lg text-sm ${
          message.type === "success"
            ? "bg-green-500/10 text-green-400 border border-green-500/30"
            : "bg-red-500/10 text-red-400 border border-red-500/30"
        }`}>{message.text}</div>
      )}

      {/* ═══ TELEGRAM ═══ */}
      <div className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
        <div className="px-5 py-4 border-b border-bah-border flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-lg">📲</span>
            <div>
              <h2 className="text-sm font-semibold text-bah-heading">Telegram</h2>
              <p className="text-[11px] text-bah-muted">Instant alerts via Telegram bot</p>
            </div>
          </div>
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={form.telegram_enabled}
              onChange={(e) => set("telegram_enabled", e.target.checked)}
              className="w-4 h-4 rounded border-bah-border accent-green-500" />
            <span className="text-xs text-bah-muted">Enabled</span>
          </label>
        </div>
        <div className="px-5 py-4 space-y-4">
          <div>
            <label className="block text-xs text-bah-muted mb-1 font-medium">Bot Token</label>
            <input type="password" value={form.telegram_bot_token}
              onChange={(e) => set("telegram_bot_token", e.target.value)}
              placeholder={settings?.telegram_bot_token?.startsWith("●") ? settings.telegram_bot_token : "Paste token from @BotFather"}
              className="w-full px-3 py-2 bg-bah-bg border border-bah-border rounded-lg text-sm text-bah-heading font-mono focus:outline-none focus:border-bah-cyan" />
            <p className="text-[10px] text-bah-muted mt-1">Message @BotFather on Telegram → /newbot → copy the token</p>
          </div>
          <div>
            <label className="block text-xs text-bah-muted mb-1 font-medium">Chat ID</label>
            <input type="text" value={form.telegram_chat_id}
              onChange={(e) => set("telegram_chat_id", e.target.value)}
              placeholder="e.g. 123456789"
              className="w-full px-3 py-2 bg-bah-bg border border-bah-border rounded-lg text-sm text-bah-heading font-mono focus:outline-none focus:border-bah-cyan" />
            <p className="text-[10px] text-bah-muted mt-1">Message your bot, then visit https://api.telegram.org/bot&lt;TOKEN&gt;/getUpdates</p>
          </div>
          <button onClick={() => test("telegram")} disabled={testing === "telegram"}
            className="px-4 py-2 bg-bah-cyan/10 border border-bah-cyan/30 rounded-lg text-xs text-bah-cyan hover:bg-bah-cyan/20 disabled:opacity-50">
            {testing === "telegram" ? "Sending..." : "Send Test Message"}
          </button>
        </div>
      </div>

      {/* ═══ EMAIL (BREVO API) ═══ */}
      <div className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
        <div className="px-5 py-4 border-b border-bah-border flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-lg">📧</span>
            <div>
              <h2 className="text-sm font-semibold text-bah-heading">Email (Brevo)</h2>
              <p className="text-[11px] text-bah-muted">Email alerts via Brevo API</p>
            </div>
          </div>
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={form.email_enabled}
              onChange={(e) => set("email_enabled", e.target.checked)}
              className="w-4 h-4 rounded border-bah-border accent-green-500" />
            <span className="text-xs text-bah-muted">Enabled</span>
          </label>
        </div>
        <div className="px-5 py-4 space-y-4">
          <div>
            <label className="block text-xs text-bah-muted mb-1 font-medium">Brevo API Key</label>
            <input type="password" value={form.email_smtp_pass}
              onChange={(e) => set("email_smtp_pass", e.target.value)}
              placeholder={settings?.email_smtp_pass?.startsWith("●") ? settings.email_smtp_pass : "xkeysib-..."}
              className="w-full px-3 py-2 bg-bah-bg border border-bah-border rounded-lg text-sm text-bah-heading font-mono focus:outline-none focus:border-bah-cyan" />
            <p className="text-[10px] text-bah-muted mt-1">Brevo → SMTP & API → API Keys → Generate</p>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-bah-muted mb-1 font-medium">From Email</label>
              <input type="email" value={form.email_from}
                onChange={(e) => set("email_from", e.target.value)}
                placeholder="info@bahamut.ai"
                className="w-full px-3 py-2 bg-bah-bg border border-bah-border rounded-lg text-sm text-bah-heading font-mono focus:outline-none focus:border-bah-cyan" />
              <p className="text-[10px] text-bah-muted mt-1">Must be verified in Brevo → Senders</p>
            </div>
            <div>
              <label className="block text-xs text-bah-muted mb-1 font-medium">Send Alerts To</label>
              <input type="email" value={form.email_to}
                onChange={(e) => set("email_to", e.target.value)}
                placeholder="you@email.com"
                className="w-full px-3 py-2 bg-bah-bg border border-bah-border rounded-lg text-sm text-bah-heading font-mono focus:outline-none focus:border-bah-cyan" />
            </div>
          </div>
          <button onClick={() => test("email")} disabled={testing === "email"}
            className="px-4 py-2 bg-bah-cyan/10 border border-bah-cyan/30 rounded-lg text-xs text-bah-cyan hover:bg-bah-cyan/20 disabled:opacity-50">
            {testing === "email" ? "Sending..." : "Send Test Email"}
          </button>
        </div>
      </div>

      {/* ═══ ALERT LEVELS ═══ */}
      <div className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
        <div className="px-5 py-4 border-b border-bah-border">
          <h2 className="text-sm font-semibold text-bah-heading">Alert Levels</h2>
          <p className="text-[11px] text-bah-muted">Choose which alert types get sent externally</p>
        </div>
        <div className="px-5 py-4 space-y-3">
          {[
            { key: "level_critical", label: "Critical", desc: "Drawdown >8%, risk >5%, kill switch, execution errors", color: "text-red-400" },
            { key: "level_warning", label: "Warning", desc: "Drawdown >5%, low win rate, approaching risk limit", color: "text-amber-400" },
            { key: "level_info", label: "Info", desc: "Trade opened/closed, regime changes", color: "text-bah-muted" },
          ].map((level) => (
            <label key={level.key} className="flex items-start gap-3 cursor-pointer">
              <input type="checkbox" checked={(form as any)[level.key]}
                onChange={(e) => set(level.key, e.target.checked)}
                className="w-4 h-4 mt-0.5 rounded border-bah-border accent-green-500" />
              <div>
                <span className={`text-sm font-semibold ${level.color}`}>{level.label}</span>
                <p className="text-[11px] text-bah-muted">{level.desc}</p>
              </div>
            </label>
          ))}
        </div>
      </div>

      {/* ═══ SAVE ═══ */}
      <div className="flex items-center justify-between">
        <div className="text-[11px] text-bah-muted">
          {settings?.telegram_connected && <span className="text-green-400 mr-4">✓ Telegram connected</span>}
          {settings?.email_connected && <span className="text-green-400">✓ Email connected</span>}
          {!settings?.telegram_connected && !settings?.email_connected && <span>No channels configured yet</span>}
        </div>
        <button onClick={save} disabled={saving}
          className="px-6 py-2.5 bg-bah-cyan text-white rounded-lg text-sm font-semibold hover:bg-bah-cyan/90 disabled:opacity-50">
          {saving ? "Saving..." : "Save Settings"}
        </button>
      </div>
    </div>
  );
}
