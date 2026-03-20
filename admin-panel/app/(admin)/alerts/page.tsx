"use client";

import { useState } from "react";
import { useAlerts, useDismissAlert } from "@/lib/hooks";
import { useUIStore } from "@/store/ui";
import { TopBar } from "@/components/layout/TopBar";
import { Card, Badge, Tag, Button, EmptyState, CardSkeleton, QueryError } from "@/components/ui";
import { fmtTime } from "@/lib/utils";

const typeColor: Record<string, string> = {
  warning: "#f59e0b",
  error: "#ef4444",
  info: "#06b6d4",
  critical: "#dc2626",
};

export default function AlertsPage() {
  const { data: alerts, isLoading, isError, error, refetch } = useAlerts();
  const dismissMut = useDismissAlert();
  const addToast = useUIStore((s) => s.addToast);
  const [tab, setTab] = useState<"active" | "archived">("active");

  if (isError) {
    return (
      <div>
        <TopBar title="Alerts" />
        <QueryError message={error?.message} onRetry={refetch} />
      </div>
    );
  }

  if (isLoading) {
    return (
      <div>
        <TopBar title="Alerts" />
        <div className="space-y-2">
          <CardSkeleton />
          <CardSkeleton />
        </div>
      </div>
    );
  }

  const active = alerts?.filter((a: any) => !a.dismissed) ?? [];
  const archived = alerts?.filter((a: any) => a.dismissed) ?? [];
  const shown = tab === "active" ? active : archived;

  return (
    <div>
      <TopBar title="Alerts">
        <Badge color="#f59e0b">{active.length} active</Badge>
      </TopBar>

      {/* Tabs */}
      <div className="flex gap-2 mb-4">
        <button onClick={() => setTab("active")}
          className={`px-4 py-1.5 rounded-md text-xs font-semibold transition-colors ${
            tab === "active"
              ? "bg-bah-cyan/10 text-bah-cyan border border-bah-cyan/30"
              : "text-bah-muted hover:text-bah-heading"
          }`}>
          Active ({active.length})
        </button>
        <button onClick={() => setTab("archived")}
          className={`px-4 py-1.5 rounded-md text-xs font-semibold transition-colors ${
            tab === "archived"
              ? "bg-bah-muted/10 text-bah-subtle border border-bah-border"
              : "text-bah-muted hover:text-bah-heading"
          }`}>
          Archived ({archived.length})
        </button>
      </div>

      {shown.length === 0 ? (
        <Card>
          <EmptyState
            icon={tab === "active" ? "✅" : "📁"}
            title={tab === "active" ? "No active alerts" : "No archived alerts"}
            description={tab === "active" ? "System is running normally" : "Dismissed alerts will appear here"}
          />
        </Card>
      ) : (
        <div className="flex flex-col gap-1.5">
          {shown.map((a: any) => {
            const color = typeColor[a.type] ?? "#64748b";
            return (
              <Card
                key={a.id}
                className={`border-l-[3px] ${a.dismissed ? "opacity-60" : ""}`}
                style={{ borderLeftColor: color } as React.CSSProperties}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Tag color={color}>{a.type}</Tag>
                    <span className="text-[11px] text-bah-heading">
                      {a.message}
                    </span>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-[10px] text-bah-muted">
                      {fmtTime(a.timestamp)}
                    </span>
                    {!a.dismissed && (
                      <Button
                        variant="ghost"
                        onClick={async () => {
                          try {
                            await dismissMut.mutateAsync({ id: a.id, subsystem: a.subsystem });
                          } catch {
                            addToast("error", "Failed to dismiss alert");
                          }
                        }}
                        disabled={dismissMut.isPending}
                      >
                        Dismiss
                      </Button>
                    )}
                    {a.dismissed && (
                      <span className="text-[10px] text-bah-muted italic">Dismissed</span>
                    )}
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
