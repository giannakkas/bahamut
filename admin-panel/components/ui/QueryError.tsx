"use client";

import { Button } from "./Button";
import { Card } from "./Card";

interface QueryErrorProps {
  message?: string;
  onRetry?: () => void;
}

export function QueryError({ message, onRetry }: QueryErrorProps) {
  return (
    <Card className="border-bah-red/20">
      <div className="flex flex-col items-center justify-center py-8 text-center">
        <div className="text-2xl mb-2">⚠️</div>
        <div className="text-sm text-bah-red font-semibold mb-1">
          Failed to load data
        </div>
        {message && (
          <div className="text-xs text-bah-muted font-mono mb-4 max-w-md">
            {message}
          </div>
        )}
        {onRetry && (
          <Button variant="outline" color="#ef4444" onClick={onRetry}>
            Retry
          </Button>
        )}
      </div>
    </Card>
  );
}
