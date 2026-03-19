"use client";

import { useState, useMemo } from "react";
import {
  useOverrides,
  useConfig,
  useCreateOverride,
  useRemoveOverride,
} from "@/lib/hooks";
import { useUIStore } from "@/store/ui";
import { TopBar } from "@/components/layout/TopBar";
import { Card, Button, EmptyState, CardSkeleton, QueryError } from "@/components/ui";
import { OverrideModal } from "@/components/overrides/OverrideModal";
import { fmtTime } from "@/lib/utils";

export default function OverridesPage() {
  const { data: overrides, isLoading, isError, error, refetch } = useOverrides();
  const { data: config } = useConfig();
  const createMut = useCreateOverride();
  const removeMut = useRemoveOverride();
  const addToast = useUIStore((s) => s.addToast);
  const [showCreate, setShowCreate] = useState(false);

  const configKeys = useMemo(
    () => (config ? Object.keys(config) : []),
    [config]
  );

  if (isError) {
    return (
      <div>
        <TopBar title="Active Overrides" />
        <QueryError message={error?.message} onRetry={refetch} />
      </div>
    );
  }

  if (isLoading) {
    return (
      <div>
        <TopBar title="Active Overrides" />
        <div className="space-y-3">
          <CardSkeleton />
          <CardSkeleton />
        </div>
      </div>
    );
  }

  return (
    <div>
      <TopBar title="Active Overrides">
        <Button onClick={() => setShowCreate(true)}>+ New Override</Button>
      </TopBar>

      {!overrides || overrides.length === 0 ? (
        <Card>
          <EmptyState
            icon="🎛"
            title="No active overrides"
            description="Create a temporary override to adjust parameters for a limited time"
          />
        </Card>
      ) : (
        <div className="flex flex-col gap-2">
          {overrides.map((o: any, i: number) => {
            const isPermanent = !o.expires || o.permanent;
            let expiryText = "Permanent";
            let expiryColor = "text-bah-muted";
            if (!isPermanent) {
              const expires = new Date(o.expires);
              const now = new Date();
              const remaining = Math.max(0, Math.floor((expires.getTime() - now.getTime()) / 60000));
              if (isNaN(remaining)) {
                expiryText = "Permanent";
              } else if (remaining <= 0) {
                expiryText = "Expired";
                expiryColor = "text-bah-red";
              } else {
                expiryText = `${remaining}min remaining`;
                expiryColor = remaining < 30 ? "text-bah-red" : "text-bah-amber";
              }
            }

            return (
              <Card
                key={i}
                glowColor="#f59e0b"
                className="border-bah-amber/20"
              >
                <div className="flex items-start justify-between">
                  <div>
                    <div className="text-[13px] font-semibold text-bah-amber">
                      {o.key}
                    </div>
                    <div className="text-[11px] text-bah-subtle mt-1">
                      Override value:{" "}
                      <span className="text-bah-heading font-semibold">
                        {String(o.value)}
                      </span>
                    </div>
                    {o.reason && (
                      <div className="text-[10px] text-bah-muted mt-0.5">
                        Reason: {o.reason}
                      </div>
                    )}
                    <div className="flex gap-3 mt-2">
                      <span className="text-[10px] text-bah-muted">
                        Created: {fmtTime(o.created) || "—"}
                      </span>
                      <span className={`text-[10px] ${expiryColor}`}>
                        {expiryText}
                      </span>
                    </div>
                  </div>
                  <Button
                    variant="danger"
                    onClick={async () => {
                      try {
                        await removeMut.mutateAsync(o.key);
                        addToast("info", `Override ${o.key} removed`);
                      } catch {
                        addToast("error", "Failed to remove override");
                      }
                    }}
                    disabled={removeMut.isPending}
                  >
                    Remove
                  </Button>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      <OverrideModal
        open={showCreate}
        configKeys={configKeys}
        onClose={() => setShowCreate(false)}
        loading={createMut.isPending}
        onSubmit={async (data) => {
          try {
            await createMut.mutateAsync(data);
            addToast("success", `Override created for ${data.key}`);
            setShowCreate(false);
          } catch {
            addToast("error", "Failed to create override");
          }
        }}
      />
    </div>
  );
}
