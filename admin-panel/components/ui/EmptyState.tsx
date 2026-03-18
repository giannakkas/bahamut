"use client";

interface EmptyStateProps {
  icon?: string;
  title: string;
  description?: string;
}

export function EmptyState({
  icon = "📭",
  title,
  description,
}: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-center">
      <div className="text-3xl mb-3">{icon}</div>
      <div className="text-sm text-bah-subtle font-medium">{title}</div>
      {description && (
        <div className="text-xs text-bah-muted mt-1 max-w-xs">
          {description}
        </div>
      )}
    </div>
  );
}
