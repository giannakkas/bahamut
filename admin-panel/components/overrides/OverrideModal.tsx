"use client";

import { useState } from "react";
import { Button } from "@/components/ui";
import type { ConfigMap } from "@/types";

interface OverrideModalProps {
  open: boolean;
  configKeys: string[];
  onClose: () => void;
  onSubmit: (data: {
    key: string;
    value: number | string | boolean;
    ttl: number;
    reason: string;
  }) => void;
  loading?: boolean;
}

export function OverrideModal({
  open,
  configKeys,
  onClose,
  onSubmit,
  loading,
}: OverrideModalProps) {
  const [key, setKey] = useState("");
  const [value, setValue] = useState("");
  const [ttl, setTtl] = useState(3600);
  const [reason, setReason] = useState("");

  if (!open) return null;

  const handleSubmit = () => {
    if (!key || !value) return;
    const numVal = parseFloat(value);
    onSubmit({
      key,
      value: isNaN(numVal) ? value : numVal,
      ttl,
      reason,
    });
    setKey("");
    setValue("");
    setTtl(3600);
    setReason("");
  };

  const inputClass =
    "w-full bg-white/[0.04] border border-bah-border rounded-md px-2.5 py-2 text-xs text-bah-heading font-mono outline-none focus:border-bah-cyan/40";
  const labelClass = "text-[10px] text-bah-muted block mb-1";

  return (
    <div
      className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/70 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-[90%] max-w-md rounded-2xl border border-bah-border-strong bg-bah-surface p-6 animate-slide-up"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-sm font-bold text-bah-heading mb-4">
          Create Override
        </h3>

        <div className="flex flex-col gap-3">
          <div>
            <label className={labelClass}>Config Key</label>
            <select
              className={inputClass}
              value={key}
              onChange={(e) => setKey(e.target.value)}
            >
              <option value="">Select key...</option>
              {configKeys.map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className={labelClass}>Override Value</label>
            <input
              className={inputClass}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder="New value"
            />
          </div>

          <div>
            <label className={labelClass}>TTL (seconds)</label>
            <input
              type="number"
              className={inputClass}
              value={ttl}
              onChange={(e) => setTtl(parseInt(e.target.value, 10))}
              min={60}
              max={86400}
            />
          </div>

          <div>
            <label className={labelClass}>Reason</label>
            <input
              className={inputClass}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Why is this override needed?"
            />
          </div>
        </div>

        <div className="flex gap-2 justify-end mt-5">
          <Button variant="ghost" onClick={onClose} disabled={loading}>
            Cancel
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={loading || !key || !value}
          >
            {loading ? "Creating..." : "Create Override"}
          </Button>
        </div>
      </div>
    </div>
  );
}
