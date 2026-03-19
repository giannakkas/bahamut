"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { EnvIndicator } from "@/components/ui";
import { useAuthStore } from "@/store/auth";
import { useAlerts } from "@/lib/hooks";
import { useOverrides } from "@/lib/hooks";

const NAV_ITEMS = [
  // Admin + Super Admin
  { href: "/dashboard", label: "Dashboard", icon: "◉", minRole: "admin" },
  { href: "/risk", label: "Risk & Kill Switch", icon: "⚡", minRole: "admin" },
  { href: "/alerts", label: "Alerts", icon: "🔔", minRole: "admin" },
  { href: "/audit", label: "Audit Log", icon: "📜", minRole: "admin" },
  { href: "/learning", label: "Learning", icon: "🧬", minRole: "admin" },
  { href: "/ai-opt", label: "AI Optimizer", icon: "🤖", minRole: "admin" },
  { href: "/users", label: "Users", icon: "👥", minRole: "admin" },
  // Super Admin only
  { href: "/config", label: "Configuration", icon: "⚙", minRole: "super_admin" },
  { href: "/overrides", label: "Overrides", icon: "🎛", minRole: "super_admin" },
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

  const activeAlerts = alerts?.filter((a) => !a.dismissed).length ?? 0;
  const activeOverrides = overrides?.length ?? 0;

  // Get role from sessionStorage
  const userRole = typeof window !== "undefined" ? sessionStorage.getItem("bah_user_role") || "admin" : "admin";
  const userLevel = ROLE_LEVELS[userRole] ?? 0;
  const visibleNav = NAV_ITEMS.filter((item) => userLevel >= (ROLE_LEVELS[item.minRole] ?? 0));

  return (
    <nav className="flex flex-col w-[220px] shrink-0 sticky top-0 h-screen overflow-y-auto border-r border-bah-border bg-gradient-to-b from-bah-surface to-bah-bg">
      {/* Logo */}
      <div className="px-4 pt-5 pb-4 border-b border-bah-border/60">
        <img src="/logo.png" alt="Bahamut.AI" className="h-12 w-auto object-contain" />
        <div className="text-[9px] text-bah-muted tracking-[0.15em] uppercase mt-1">
          Trading Intelligence Control
        </div>
      </div>

      {/* Nav Items */}
      <div className="py-2 flex-1">
        {visibleNav.map((item) => {
          const active = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-2.5 px-4 py-2.5 text-xs border-l-2 transition-all duration-200",
                active
                  ? "border-bah-cyan bg-bah-cyan/[0.08] text-bah-cyan font-semibold"
                  : "border-transparent text-bah-subtle hover:bg-white/[0.02] hover:text-bah-text"
              )}
            >
              <span className="text-sm w-5 text-center">{item.icon}</span>
              <span>{item.label}</span>

              {/* Alert count badge */}
              {item.href === "/alerts" && activeAlerts > 0 && (
                <span className="ml-auto bg-bah-red text-white text-[9px] font-bold px-1.5 py-px rounded-full">
                  {activeAlerts}
                </span>
              )}

              {/* Override count badge */}
              {item.href === "/overrides" && activeOverrides > 0 && (
                <span className="ml-auto bg-bah-amber text-black text-[9px] font-bold px-1.5 py-px rounded-full">
                  {activeOverrides}
                </span>
              )}
            </Link>
          );
        })}
      </div>

      {/* Footer */}
      <div className="px-4 py-3 border-t border-bah-border/60 text-[10px] text-bah-muted">
        <EnvIndicator />
        {userRole === "super_admin" && (
          <div className="text-[9px] text-purple-400 font-semibold tracking-wider uppercase mt-1">⚡ Super Admin</div>
        )}
        <div className="flex justify-between mt-2">
          <span>v1.0.0</span>
          <button
            onClick={logout}
            className="text-bah-cyan hover:text-bah-cyan/80 transition-colors"
          >
            Logout
          </button>
        </div>
      </div>
    </nav>
  );
}
