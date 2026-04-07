"use client";

import { useState, useMemo } from "react";
import { Card, Tag, EmptyState } from "@/components/ui";
import { fmtTime } from "@/lib/utils";
import { CATEGORY_META } from "@/types";
import type { AuditLogEntry } from "@/types";

interface AuditTableProps {
  entries: AuditLogEntry[];
}

export function AuditTable({ entries }: AuditTableProps) {
  const [filterCat, setFilterCat] = useState("");
  const [filterSource, setFilterSource] = useState("");

  const filtered = useMemo(
    () =>
      entries.filter((e) => {
        if (filterCat && !e.key.startsWith(filterCat)) return false;
        if (filterSource && e.source !== filterSource) return false;
        return true;
      }),
    [entries, filterCat, filterSource]
  );

  const selectClass =
    "bg-bah-surface border border-bah-border rounded-md px-2.5 py-1.5 text-xs text-bah-heading font-mono outline-none";

  return (
    <div>
      {/* Filters */}
      <div className="flex gap-2 mb-4">
        <select
          className={selectClass}
          value={filterCat}
          onChange={(e) => setFilterCat(e.target.value)}
        >
          <option value="">All categories</option>
          {Object.entries(CATEGORY_META).map(([k, v]) => (
            <option key={k} value={k}>
              {v.label}
            </option>
          ))}
        </select>
        <select
          className={selectClass}
          value={filterSource}
          onChange={(e) => setFilterSource(e.target.value)}
        >
          <option value="">All sources</option>
          <option value="user">User</option>
          <option value="system">System</option>
        </select>
      </div>

      <Card>
        {filtered.length === 0 ? (
          <EmptyState
            icon="📭"
            title="No audit entries match filters"
            description="Try adjusting your filter criteria"
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-[12px]">
              <thead>
                <tr>
                  {["Timestamp", "Config Key", "Old → New", "Source", "User"].map(
                    (h) => (
                      <th
                        key={h}
                        className="px-2.5 py-2 text-left text-[11px] text-bah-muted uppercase tracking-widest border-b border-bah-border/60 font-medium"
                      >
                        {h}
                      </th>
                    )
                  )}
                </tr>
              </thead>
              <tbody>
                {filtered.map((e) => {
                  const cat = e.key.split(".")[0];
                  const catMeta = CATEGORY_META[cat];
                  return (
                    <tr
                      key={e.id}
                      className="hover:bg-bah-cyan/[0.02] transition-colors"
                    >
                      <td className="px-2.5 py-2 text-bah-subtle text-[11px] border-b border-white/[0.02]">
                        {fmtTime(e.timestamp)}
                      </td>
                      <td className="px-2.5 py-2 text-bah-heading font-medium border-b border-white/[0.02]">
                        <span style={{ color: catMeta?.color ?? "#64748b" }}>
                          {cat}
                        </span>
                        .{e.key.split(".").slice(1).join(".")}
                      </td>
                      <td className="px-2.5 py-2 border-b border-white/[0.02]">
                        <span className="text-bah-red/60 line-through">
                          {e.old_value}
                        </span>
                        <span className="text-bah-muted mx-1.5">→</span>
                        <span className="text-bah-green font-semibold">
                          {e.new_value}
                        </span>
                      </td>
                      <td className="px-2.5 py-2 border-b border-white/[0.02]">
                        <Tag
                          color={
                            e.source === "system" ? "#8b5cf6" : "#06b6d4"
                          }
                        >
                          {e.source}
                        </Tag>
                      </td>
                      <td className="px-2.5 py-2 text-bah-subtle border-b border-white/[0.02]">
                        {e.user}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
