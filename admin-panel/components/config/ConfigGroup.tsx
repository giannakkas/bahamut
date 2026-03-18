"use client";

import { useState } from "react";
import { Card, Tag } from "@/components/ui";
import { ConfigEditor } from "./ConfigEditor";
import type { ConfigEntry } from "@/types";

interface ConfigGroupProps {
  category: string;
  label: string;
  icon: string;
  color: string;
  items: ConfigEntry[];
  editedKeys: Record<string, number | string | boolean>;
  onEdit: (key: string, val: number | string | boolean) => void;
  onSave: (key: string) => void;
  onReset: (key: string) => void;
  savingKey: string | null;
  defaultExpanded?: boolean;
}

export function ConfigGroup({
  label,
  icon,
  color,
  items,
  editedKeys,
  onEdit,
  onSave,
  onReset,
  savingKey,
  defaultExpanded = false,
}: ConfigGroupProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  return (
    <Card glowColor={color}>
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex items-center justify-between w-full text-left"
      >
        <div className="flex items-center gap-2">
          <span className="text-sm">{icon}</span>
          <span className="text-[13px] font-semibold text-bah-heading">
            {label}
          </span>
          <Tag color={color}>{items.length}</Tag>
        </div>
        <span
          className="text-bah-muted text-sm transition-transform duration-200"
          style={{ transform: expanded ? "rotate(180deg)" : "none" }}
        >
          ▾
        </span>
      </button>

      {expanded && (
        <div className="mt-3 flex flex-col">
          {items.map((item) => (
            <ConfigEditor
              key={item.key}
              configKey={item.key}
              meta={item}
              editedValue={editedKeys[item.key]}
              onEdit={(val) => onEdit(item.key, val)}
              onSave={() => onSave(item.key)}
              onReset={() => onReset(item.key)}
              saving={savingKey === item.key}
            />
          ))}
        </div>
      )}
    </Card>
  );
}
