"use client";

import { useState } from "react";
import { Card, Badge, Button, Toggle, ConfirmModal, Pulse } from "@/components/ui";
import { fmtTime } from "@/lib/utils";
import type { KillSwitchState, SafeModeState } from "@/types";

interface KillSwitchPanelProps {
  killSwitch: KillSwitchState;
  safeMode: SafeModeState;
  onToggleKill: (active: boolean) => void;
  onToggleSafe: () => void;
  toggling?: boolean;
}

export function KillSwitchPanel({
  killSwitch,
  safeMode,
  onToggleKill,
  onToggleSafe,
  toggling,
}: KillSwitchPanelProps) {
  const [showConfirm, setShowConfirm] = useState(false);

  const handleConfirm = () => {
    onToggleKill(!killSwitch.active);
    setShowConfirm(false);
  };

  return (
    <>
      {/* Kill Switch */}
      <Card
        glowColor={killSwitch.active ? "#ef4444" : "#10b981"}
        className={
          killSwitch.active ? "border-bah-red/30" : undefined
        }
      >
        <div className="flex items-start justify-between">
          <div>
            <div className="text-sm font-bold text-bah-heading">
              🚨 Kill Switch Engine
            </div>
            <div className="text-[12px] text-bah-subtle mt-1">
              Status:{" "}
              <span
                className={`font-semibold ${
                  killSwitch.active ? "text-bah-red" : "text-bah-green"
                }`}
              >
                {killSwitch.active
                  ? "ACTIVE — All trading halted"
                  : "Inactive — Trading enabled"}
              </span>
            </div>
            {killSwitch.reason && (
              <div className="text-[12px] text-bah-red mt-1">
                Trigger: {killSwitch.reason}
              </div>
            )}
            <div className="text-[11px] text-bah-muted mt-2">
              Last triggered: {fmtTime(killSwitch.last_triggered)}
            </div>
          </div>
          <Button
            variant={killSwitch.active ? "primary" : "danger"}
            color={killSwitch.active ? "#10b981" : undefined}
            onClick={() => setShowConfirm(true)}
            disabled={toggling}
          >
            {killSwitch.active ? "Resume Trading" : "Force Kill Switch"}
          </Button>
        </div>
      </Card>

      {/* Safe Mode */}
      <Card glowColor="#f59e0b" className="mt-3">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-xs font-semibold text-bah-heading">
              🛡️ Safe Mode
            </div>
            <div className="text-[11px] text-bah-muted mt-0.5">
              Reduces exposure and tightens risk parameters
            </div>
          </div>
          <Toggle value={safeMode.active} onChange={onToggleSafe} />
        </div>
      </Card>

      <ConfirmModal
        open={showConfirm}
        title={
          killSwitch.active
            ? "Resume Trading"
            : "⚠️ Activate Kill Switch"
        }
        message={
          killSwitch.active
            ? "This will resume all trading operations. Ensure market conditions are stable before proceeding."
            : "This will immediately halt ALL trading operations and close pending orders. This is a critical safety action."
        }
        danger={!killSwitch.active}
        loading={toggling}
        onConfirm={handleConfirm}
        onCancel={() => setShowConfirm(false)}
        confirmLabel={killSwitch.active ? "Resume" : "Activate Kill"}
      />
    </>
  );
}
