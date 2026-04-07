"use client";

import { useEffect, useState } from "react";
import { isMockMode } from "@/lib/utils";
import { checkHealth } from "@/lib/api";
import { Pulse } from "./Pulse";

export function EnvIndicator() {
  const mock = isMockMode();
  const [healthy, setHealthy] = useState<boolean | null>(null);

  useEffect(() => {
    let mounted = true;
    const check = async () => {
      const ok = await checkHealth();
      if (mounted) setHealthy(ok);
    };
    check();
    const iv = setInterval(check, 30_000); // check every 30s
    return () => {
      mounted = false;
      clearInterval(iv);
    };
  }, []);

  return (
    <div className="flex flex-col gap-1.5 text-[11px]">
      <div className="flex items-center gap-1.5">
        <Pulse color={mock ? "#f59e0b" : "#10b981"} />
        <span className={mock ? "text-bah-amber" : "text-bah-green"}>
          {mock ? "MOCK MODE" : "LIVE"}
        </span>
      </div>
      {!mock && (
        <div className="flex items-center gap-1.5">
          <Pulse
            color={
              healthy === null ? "#64748b" : healthy ? "#10b981" : "#ef4444"
            }
          />
          <span
            className={
              healthy === null
                ? "text-bah-muted"
                : healthy
                  ? "text-bah-green"
                  : "text-bah-red"
            }
          >
            {healthy === null
              ? "Checking..."
              : healthy
                ? "Backend OK"
                : "Backend Down"}
          </span>
        </div>
      )}
    </div>
  );
}
