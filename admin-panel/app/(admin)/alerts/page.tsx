"use client";

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
          <CardSkeleton />
        </div>
      </div>
    );
  }

  const active = alerts?.filter((a) => !a.dismissed) ?? [];

  return (
    <div>
      <TopBar title="Alerts">
        <Badge color="#f59e0b">{active.length} active</Badge>
      </TopBar>

      {!alerts || alerts.length === 0 ? (
        <Card>
          <EmptyState
            icon="🔔"
            title="No alerts"
            description="System is running normally"
          />
        </Card>
      ) : (
        <div className="flex flex-col gap-1.5">
          {alerts.map((a) => {
            const color = typeColor[a.type] ?? "#64748b";
            return (
              <Card
                key={a.id}
                className={`border-l-[3px] ${a.dismissed ? "opacity-40" : ""}`}
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
                            await dismissMut.mutateAsync(a.id);
                          } catch {
                            addToast("error", "Failed to dismiss alert");
                          }
                        }}
                        disabled={dismissMut.isPending}
                      >
                        Dismiss
                      </Button>
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
