"use client";

import { useState } from "react";
import { useAISuggestions, useUpdateConfig } from "@/lib/hooks";
import { useUIStore } from "@/store/ui";
import { TopBar } from "@/components/layout/TopBar";
import { Card, Button, EmptyState } from "@/components/ui";
import { fmt } from "@/lib/utils";
import type { AISuggestion } from "@/types";

export default function AIOptPage() {
  const aiMut = useAISuggestions();
  const updateMut = useUpdateConfig();
  const addToast = useUIStore((s) => s.addToast);
  const [suggestions, setSuggestions] = useState<AISuggestion[] | null>(null);
  const [applyingKey, setApplyingKey] = useState<string | null>(null);

  const runOptimization = async () => {
    try {
      const result = await aiMut.mutateAsync();
      setSuggestions(result);
    } catch {
      addToast("error", "AI optimization failed");
    }
  };

  const applySingle = async (s: AISuggestion) => {
    setApplyingKey(s.key);
    try {
      await updateMut.mutateAsync({ key: s.key, value: s.suggested });
      addToast("success", `Applied: ${s.key} → ${fmt(s.suggested)}`);
      setSuggestions((prev) =>
        prev ? prev.filter((x) => x.key !== s.key) : null
      );
    } catch {
      addToast("error", `Failed to apply ${s.key}`);
    } finally {
      setApplyingKey(null);
    }
  };

  const applyAll = async () => {
    if (!suggestions) return;
    for (const s of suggestions) {
      try {
        await updateMut.mutateAsync({ key: s.key, value: s.suggested });
      } catch {
        addToast("error", `Failed: ${s.key}`);
      }
    }
    addToast("success", "All suggestions applied");
    setSuggestions([]);
  };

  return (
    <div>
      <TopBar title="🤖 AI Optimization">
        <Button
          color="#8b5cf6"
          onClick={runOptimization}
          disabled={aiMut.isPending}
        >
          {aiMut.isPending
            ? "⏳ Analyzing..."
            : "Suggest Optimal Settings"}
        </Button>
      </TopBar>

      {/* Loading state */}
      {aiMut.isPending && (
        <Card className="text-center py-10">
          <div className="text-3xl mb-3 animate-pulse">🧠</div>
          <div className="text-xs text-bah-purple">
            Running portfolio optimization analysis...
          </div>
          <div className="text-[10px] text-bah-muted mt-1">
            Evaluating risk-return tradeoffs across all scenarios
          </div>
        </Card>
      )}

      {/* Results */}
      {suggestions && !aiMut.isPending && (
        <div className="flex flex-col gap-2">
          {suggestions.length === 0 ? (
            <Card>
              <EmptyState
                icon="✅"
                title="All suggestions applied"
                description="Run analysis again to check for new optimizations"
              />
            </Card>
          ) : (
            <>
              <Card className="bg-bah-purple/[0.04] border-bah-purple/15">
                <div className="text-[11px] text-bah-subtle">
                  AI has analyzed current market conditions, portfolio
                  performance, and risk metrics.
                </div>
                <div className="text-[11px] text-bah-purple mt-1">
                  {suggestions.length} optimization suggestions available.
                </div>
              </Card>

              {suggestions.map((s) => {
                const delta =
                  ((s.suggested - s.current) / s.current) * 100;
                return (
                  <Card key={s.key} glowColor="#8b5cf6">
                    <div className="flex items-start justify-between">
                      <div>
                        <div className="text-xs font-semibold text-bah-heading">
                          {s.key}
                        </div>
                        <div className="flex items-center gap-3 mt-1.5">
                          <span className="text-[11px] text-bah-red/60">
                            {fmt(s.current)}
                          </span>
                          <span className="text-bah-muted">→</span>
                          <span className="text-[11px] text-bah-green font-bold">
                            {fmt(s.suggested)}
                          </span>
                          <span
                            className={`text-[10px] ${
                              delta > 0 ? "text-bah-green" : "text-bah-amber"
                            }`}
                          >
                            ({delta > 0 ? "+" : ""}
                            {fmt(delta, 1)}%)
                          </span>
                        </div>
                        <div className="text-[10px] text-bah-muted mt-1">
                          {s.reason}
                        </div>
                      </div>
                      <Button
                        onClick={() => applySingle(s)}
                        disabled={applyingKey === s.key}
                      >
                        {applyingKey === s.key ? "..." : "Apply"}
                      </Button>
                    </div>
                  </Card>
                );
              })}

              <div className="flex justify-end mt-2">
                <Button color="#10b981" onClick={applyAll}>
                  Apply All
                </Button>
              </div>
            </>
          )}
        </div>
      )}

      {/* Empty state */}
      {!suggestions && !aiMut.isPending && (
        <Card className="text-center py-10">
          <div className="text-3xl mb-2">🤖</div>
          <div className="text-sm text-bah-muted">
            Click &quot;Suggest Optimal Settings&quot; to run AI analysis
          </div>
        </Card>
      )}
    </div>
  );
}
