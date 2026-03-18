"use client";

import { useState, useMemo, useCallback, useEffect } from "react";
import { useConfig, useUpdateConfig, useResetConfig } from "@/lib/hooks";
import { useUIStore } from "@/store/ui";
import { TopBar } from "@/components/layout/TopBar";
import { ConfigGroup } from "@/components/config/ConfigGroup";
import { CardSkeleton, QueryError } from "@/components/ui";
import { CATEGORY_META } from "@/types";
import type { ConfigEntry } from "@/types";

export default function ConfigPage() {
  const { data: config, isLoading, isError, error: configErr, refetch } = useConfig();
  const updateMut = useUpdateConfig();
  const resetMut = useResetConfig();
  const addToast = useUIStore((s) => s.addToast);

  const [editedKeys, setEditedKeys] = useState<
    Record<string, number | string | boolean>
  >({});
  const [searchTerm, setSearchTerm] = useState("");
  const [savingKey, setSavingKey] = useState<string | null>(null);

  // Warn on navigation/close when unsaved edits exist
  useEffect(() => {
    const hasDirty = Object.keys(editedKeys).length > 0;
    const handler = (e: BeforeUnloadEvent) => {
      if (hasDirty) {
        e.preventDefault();
      }
    };
    if (hasDirty) {
      window.addEventListener("beforeunload", handler);
    }
    return () => window.removeEventListener("beforeunload", handler);
  }, [editedKeys]);

  const grouped = useMemo(() => {
    if (!config) return {};
    const groups: Record<string, ConfigEntry[]> = {};
    Object.entries(config).forEach(([key, meta]) => {
      if (
        searchTerm &&
        !key.toLowerCase().includes(searchTerm.toLowerCase()) &&
        !meta.description.toLowerCase().includes(searchTerm.toLowerCase())
      )
        return;
      if (!groups[meta.category]) groups[meta.category] = [];
      groups[meta.category].push({ key, ...meta });
    });
    return groups;
  }, [config, searchTerm]);

  const handleEdit = useCallback(
    (key: string, val: number | string | boolean) => {
      setEditedKeys((prev) => ({ ...prev, [key]: val }));
    },
    []
  );

  const handleSave = useCallback(
    async (key: string) => {
      const val = editedKeys[key];
      if (val === undefined) return;

      setSavingKey(key);
      try {
        await updateMut.mutateAsync({ key, value: val });
        setEditedKeys((prev) => {
          const next = { ...prev };
          delete next[key];
          return next;
        });
        addToast("success", `Updated ${key}`);
      } catch {
        addToast("error", `Failed to update ${key}`);
      } finally {
        setSavingKey(null);
      }
    },
    [editedKeys, updateMut, addToast]
  );

  const handleReset = useCallback(
    async (key: string) => {
      setSavingKey(key);
      try {
        await resetMut.mutateAsync(key);
        setEditedKeys((prev) => {
          const next = { ...prev };
          delete next[key];
          return next;
        });
        addToast("info", `Reset ${key} to default`);
      } catch {
        addToast("error", `Failed to reset ${key}`);
      } finally {
        setSavingKey(null);
      }
    },
    [resetMut, addToast]
  );

  if (isError) {
    return (
      <div>
        <TopBar title="Configuration Control" />
        <QueryError message={configErr?.message} onRetry={refetch} />
      </div>
    );
  }

  if (isLoading || !config) {
    return (
      <div>
        <TopBar title="Configuration Control" />
        <div className="space-y-3">
          <CardSkeleton />
          <CardSkeleton />
          <CardSkeleton />
        </div>
      </div>
    );
  }

  return (
    <div>
      <TopBar title="Configuration Control">
        <input
          className="w-56 bg-white/[0.04] border border-bah-border rounded-lg px-3 py-1.5 text-xs text-bah-heading font-mono outline-none focus:border-bah-cyan/40 placeholder:text-bah-muted"
          placeholder="Search configs..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
        />
        <span className="text-[10px] text-bah-muted">
          {Object.keys(config).length} keys
        </span>
      </TopBar>

      <div className="flex flex-col gap-2">
        {Object.entries(grouped).map(([cat, items]) => {
          const meta = CATEGORY_META[cat] ?? {
            label: cat,
            icon: "⚙️",
            color: "#64748b",
          };
          return (
            <ConfigGroup
              key={cat}
              category={cat}
              label={meta.label}
              icon={meta.icon}
              color={meta.color}
              items={items}
              editedKeys={editedKeys}
              onEdit={handleEdit}
              onSave={handleSave}
              onReset={handleReset}
              savingKey={savingKey}
            />
          );
        })}
      </div>
    </div>
  );
}
