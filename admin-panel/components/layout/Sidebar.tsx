"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, useEffect } from "react";
import { cn } from "@/lib/utils";
import { EnvIndicator } from "@/components/ui";
import { useAuthStore } from "@/store/auth";
import { useAlerts } from "@/lib/hooks";
import { useOverrides } from "@/lib/hooks";
import { useAdminSocket } from "@/providers/AdminSocketProvider";

const OPERATIONAL_NAV = [
  { href: "/training-operations", label: "Training Operations", icon: "🧪" },
  { href: "/binance-trades", label: "Binance Trades", icon: "🟡" },
  { href: "/alpaca-trades", label: "Alpaca Trades", icon: "🦙" },
  { href: "/settings-notifications", label: "Notifications", icon: "🔔" },
  { href: "/audit", label: "Audit Log", icon: "📜" },
  { href: "/users", label: "Users", icon: "👥" },
  { href: "/config", label: "Configuration", icon: "⚙", minRole: "super_admin" },
  { href: "/overrides", label: "Overrides", icon: "🎛", minRole: "super_admin" },
];

const LEGACY_NAV = [
  { href: "/dashboard", label: "Dashboard", icon: "◉" },
  { href: "/top-picks", label: "Top Picks", icon: "🔥" },
  { href: "/risk", label: "Risk & Kill Switch", icon: "⚡" },
  { href: "/alerts", label: "Alerts", icon: "🔔" },
  { href: "/paper-trading", label: "Paper Trading", icon: "💰" },
  { href: "/agent-council", label: "Agent Council", icon: "◎" },
  { href: "/learning", label: "Learning", icon: "🧬" },
  { href: "/learning-lab", label: "Learning Lab", icon: "◐" },
  { href: "/ai-opt", label: "AI Optimizer", icon: "🤖" },
  { href: "/execution", label: "Execution Monitor", icon: "⚡" },
  { href: "/trade-journal", label: "Trade Journal", icon: "☰" },
  { href: "/trust", label: "Trust & Intelligence", icon: "🧠", minRole: "super_admin" },
  { href: "/adaptive-risk", label: "Adaptive Risk", icon: "📊", minRole: "super_admin" },
  { href: "/agent-ranking", label: "Agent Ranking", icon: "🏆", minRole: "super_admin" },
];

const ROLE_LEVELS: Record<string, number> = {
  user: 0, viewer: 0, trader: 1, admin: 2, super_admin: 3,
};

export function Sidebar() {
  const pathname = usePathname();
  const logout = useAuthStore((s) => s.logout);
  const { data: alerts } = useAlerts();
  const { data: overrides } = useOverrides();
  const { status: wsStatus } = useAdminSocket();
  const [showLegacy, setShowLegacy] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  const activeAlerts = alerts?.filter((a) => !a.dismissed).length ?? 0;
  const activeOverrides = overrides?.length ?? 0;

  const userRole = typeof window !== "undefined" ? sessionStorage.getItem("bah_user_role") || "admin" : "admin";
  const isSuperAdmin = userRole === "super_admin";
  const userLevel = ROLE_LEVELS[userRole] ?? 0;

  // Close mobile menu on navigation
  useEffect(() => { setMobileOpen(false); }, [pathname]);

  // Lock body scroll when mobile menu is open
  useEffect(() => {
    if (mobileOpen) document.body.style.overflow = "hidden";
    else document.body.style.overflow = "";
    return () => { document.body.style.overflow = ""; };
  }, [mobileOpen]);

  const canSee = (item: { minRole?: string }) =>
    userLevel >= (ROLE_LEVELS[item.minRole || "admin"] ?? 0);

  const renderItem = (item: any) => {
    if (!canSee(item)) return null;
    const active = pathname === item.href;
    return (
      <Link key={item.href} href={item.href}
        onClick={() => setMobileOpen(false)}
        className={cn(
          "flex items-center gap-2.5 px-4 py-2.5 text-xs border-l-2 transition-all duration-200",
          active
            ? "border-bah-cyan bg-bah-cyan/[0.08] text-bah-cyan font-semibold"
            : "border-transparent text-bah-subtle hover:bg-white/[0.02] hover:text-bah-text"
        )}>
        <span className="text-sm w-5 text-center">{item.icon}</span>
        <span>{item.label}</span>
        {item.href === "/alerts" && activeAlerts > 0 && (
          <span className="ml-auto bg-bah-red text-white text-[9px] font-bold px-1.5 py-px rounded-full">{activeAlerts}</span>
        )}
        {item.href === "/overrides" && activeOverrides > 0 && (
          <span className="ml-auto bg-bah-amber text-black text-[9px] font-bold px-1.5 py-px rounded-full">{activeOverrides}</span>
        )}
      </Link>
    );
  };

  const sidebarContent = (
    <>
      {/* Logo */}
      <div className="px-4 pt-5 pb-4 border-b border-bah-border/60">
        <img src="/logo.png" alt="Bahamut.AI" className="h-12 w-auto object-contain" />
        <div className="text-[9px] tracking-[0.15em] uppercase mt-1 flex items-center gap-2">
          <span className="text-green-400 font-semibold">● OPERATIONS</span>
          <span className="text-bah-muted">BTC + ETH</span>
        </div>
      </div>

      {/* Operational Nav */}
      <div className="py-2 flex-1">
        <div className="px-4 py-1.5 text-[9px] text-bah-muted font-semibold uppercase tracking-widest">
          Trading Operations
        </div>
        {OPERATIONAL_NAV.map(renderItem)}

        {/* Legacy Section */}
        <div className="mt-3 border-t border-bah-border/40">
          <button
            onClick={() => setShowLegacy(!showLegacy)}
            className="w-full px-4 py-2 text-[9px] text-bah-muted font-semibold uppercase tracking-widest flex items-center justify-between hover:text-bah-heading transition-colors"
          >
            <span>Legacy / Research</span>
            <span className="text-[10px]">{showLegacy ? "▾" : "▸"}</span>
          </button>
          {showLegacy && (
            <div className="opacity-60">
              {LEGACY_NAV.map(renderItem)}
            </div>
          )}
        </div>
      </div>

      {/* Footer */}
      <div className="px-4 py-3 border-t border-bah-border/60 text-[10px] text-bah-muted">
        <EnvIndicator />
        <div className="flex items-center gap-1.5 mt-1 text-[10px]">
          <span className={`w-1.5 h-1.5 rounded-full ${wsStatus === "connected" ? "bg-green-400" : wsStatus === "connecting" ? "bg-amber-400 animate-pulse" : "bg-red-400"}`} />
          <span className={wsStatus === "connected" ? "text-green-400" : wsStatus === "connecting" ? "text-amber-400" : "text-red-400"}>
            {wsStatus === "connected" ? "Realtime ON" : wsStatus === "connecting" ? "Connecting..." : "Realtime OFF"}
          </span>
        </div>

        {isSuperAdmin && (
          <a href="#" onClick={(e) => {
            e.preventDefault();
            const token = typeof window !== "undefined" ? sessionStorage.getItem("bah_token") || "" : "";
            window.location.href = `https://bahamut.ai?token=${encodeURIComponent(token)}`;
          }}
            className="w-full mt-2 flex items-center justify-between px-2.5 py-1.5 rounded-md border border-bah-border bg-white/[0.02] text-bah-muted hover:bg-white/[0.04] hover:text-bah-heading transition-all duration-200">
            <span className="text-[10px] font-semibold tracking-wide uppercase">👤 Switch to Frontend</span>
            <span className="text-[9px] opacity-60">→</span>
          </a>
        )}

        {isSuperAdmin && (
          <div className="text-[9px] text-purple-400 font-semibold tracking-wider uppercase mt-2">⚡ Super Admin</div>
        )}

        <div className="flex justify-between mt-2">
          <span>v2.0.0</span>
          <button onClick={logout} className="text-bah-cyan hover:text-bah-cyan/80 transition-colors">Logout</button>
        </div>
      </div>
    </>
  );

  return (
    <>
      {/* Mobile hamburger — fixed top-left */}
      <button
        onClick={() => setMobileOpen(!mobileOpen)}
        className="lg:hidden fixed top-3 left-3 z-50 p-2 rounded-lg bg-bah-surface border border-bah-border text-bah-heading shadow-lg"
        aria-label="Toggle menu"
      >
        {mobileOpen ? (
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
        ) : (
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 12h18M3 6h18M3 18h18"/></svg>
        )}
      </button>

      {/* Mobile overlay */}
      {mobileOpen && (
        <div className="lg:hidden fixed inset-0 bg-black/60 z-30 backdrop-blur-sm" onClick={() => setMobileOpen(false)} />
      )}

      {/* Sidebar */}
      <nav className={cn(
        "flex flex-col w-[220px] shrink-0 h-screen overflow-y-auto border-r border-bah-border bg-gradient-to-b from-bah-surface to-bah-bg z-40 transition-transform duration-300",
        "lg:sticky lg:top-0 lg:translate-x-0",
        "fixed top-0 left-0",
        mobileOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"
      )}>
        {sidebarContent}
      </nav>
    </>
  );
}
