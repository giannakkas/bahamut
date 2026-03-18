"use client";

import { useAuditLog } from "@/lib/hooks";
import { TopBar } from "@/components/layout/TopBar";
import { AuditTable } from "@/components/audit/AuditTable";
import { TableSkeleton, QueryError } from "@/components/ui";

export default function AuditPage() {
  const { data: entries, isLoading, isError, error, refetch } = useAuditLog();

  return (
    <div>
      <TopBar title="Audit Log" />
      {isError ? (
        <QueryError message={error?.message} onRetry={refetch} />
      ) : isLoading || !entries ? (
        <TableSkeleton rows={8} />
      ) : (
        <AuditTable entries={entries} />
      )}
    </div>
  );
}
