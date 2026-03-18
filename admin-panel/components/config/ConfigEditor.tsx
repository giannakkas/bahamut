"use client";

import { useState, useEffect } from "react";
import { Button, Toggle } from "@/components/ui";
import { fmt } from "@/lib/utils";
import type { ConfigMeta } from "@/types";

interface ConfigEditorProps {
  configKey: string;
  meta: ConfigMeta;
  editedValue: number | string | boolean | undefined;
  onEdit: (val: number | string | boolean) => void;
  onSave: () => void;
  onReset: () => void;
  saving?: boolean;
}

export function ConfigEditor({
  configKey,
  meta,
  editedValue,
  onEdit,
  onSave,
  onReset,
  saving,
}: ConfigEditorProps) {
  const currentVal = editedValue !== undefined ? editedValue : meta.value;
  const isModified = editedValue !== undefined && editedValue !== meta.value;
  const isDefault = meta.value === meta.default;
  const shortKey = configKey.split(".").slice(1).join(".");

  // Local slider state — updates visually on every drag pixel,
  // commits to parent only on pointer release.
  const [localSlider, setLocalSlider] = useState<number>(currentVal as number);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    if (!dragging) {
      setLocalSlider(currentVal as number);
    }
  }, [currentVal, dragging]);

  const displaySliderVal = dragging ? localSlider : (currentVal as number);

  return (
    <div className="flex items-center gap-3 py-2 border-b border-white/[0.02] last:border-0">
      {/* Label */}
      <div className="flex-[1.5] min-w-0">
        <div
          className={`text-[11px] font-medium ${isModified ? "text-bah-amber" : "text-bah-heading"}`}
        >
          {shortKey}
        </div>
        <div className="text-[9px] text-bah-muted mt-0.5 truncate">
          {meta.description}
        </div>
      </div>

      {/* Input */}
      <div className="flex-1 flex items-center gap-2">
        {meta.type === "bool" ? (
          <Toggle
            value={!!currentVal}
            onChange={(v) => onEdit(v)}
            disabled={saving}
          />
        ) : meta.type === "float" ? (
          <div className="flex items-center gap-2 w-full">
            <input
              type="range"
              min={meta.min ?? 0}
              max={meta.max ?? 1}
              step={0.01}
              value={displaySliderVal}
              onChange={(e) => setLocalSlider(parseFloat(e.target.value))}
              onPointerDown={() => setDragging(true)}
              onPointerUp={(e) => {
                setDragging(false);
                onEdit(parseFloat((e.target as HTMLInputElement).value));
              }}
              onLostPointerCapture={(e) => {
                setDragging(false);
                onEdit(parseFloat((e.target as HTMLInputElement).value));
              }}
              disabled={saving}
              className="flex-1 h-1 appearance-none bg-bah-cyan/15 rounded cursor-pointer
                [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3.5
                [&::-webkit-slider-thumb]:h-3.5 [&::-webkit-slider-thumb]:rounded-full
                [&::-webkit-slider-thumb]:bg-bah-cyan [&::-webkit-slider-thumb]:shadow-[0_0_8px_rgba(6,182,212,0.4)]
                [&::-webkit-slider-thumb]:cursor-pointer"
            />
            <span className="text-[11px] text-bah-cyan font-semibold min-w-[40px] text-right">
              {fmt(displaySliderVal)}
            </span>
          </div>
        ) : meta.options ? (
          <select
            value={currentVal as string}
            onChange={(e) => onEdit(e.target.value)}
            disabled={saving}
            className="bg-bah-surface border border-bah-border rounded-md px-2.5 py-1.5 text-xs text-bah-heading font-mono outline-none"
          >
            {meta.options.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
        ) : meta.type === "int" ? (
          <input
            type="number"
            value={currentVal as number}
            min={meta.min}
            max={meta.max}
            onChange={(e) => onEdit(parseInt(e.target.value, 10))}
            disabled={saving}
            className="w-20 bg-white/[0.04] border border-bah-border rounded-md px-2.5 py-1.5 text-xs text-bah-heading font-mono outline-none focus:border-bah-cyan/40"
          />
        ) : (
          <input
            value={currentVal as string}
            onChange={(e) => onEdit(e.target.value)}
            disabled={saving}
            className="w-28 bg-white/[0.04] border border-bah-border rounded-md px-2.5 py-1.5 text-xs text-bah-heading font-mono outline-none focus:border-bah-cyan/40"
          />
        )}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-1.5 min-w-[100px] justify-end">
        {isModified && (
          <Button onClick={onSave} disabled={saving}>
            {saving ? "..." : "Save"}
          </Button>
        )}
        {!isDefault && (
          <Button
            variant="outline"
            color="#64748b"
            onClick={onReset}
            disabled={saving}
          >
            ↺
          </Button>
        )}
      </div>
    </div>
  );
}
