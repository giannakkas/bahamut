"use client";

import { Button } from "./Button";

interface ConfirmModalProps {
  open: boolean;
  title: string;
  message: string;
  onConfirm: () => void;
  onCancel: () => void;
  danger?: boolean;
  loading?: boolean;
  confirmLabel?: string;
}

export function ConfirmModal({
  open,
  title,
  message,
  onConfirm,
  onCancel,
  danger,
  loading,
  confirmLabel,
}: ConfirmModalProps) {
  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/70 backdrop-blur-sm"
      onClick={onCancel}
    >
      <div
        className="w-[90%] max-w-md rounded-2xl border border-bah-border-strong bg-bah-surface p-6 animate-slide-up"
        onClick={(e) => e.stopPropagation()}
      >
        <h3
          className={`text-base font-bold mb-2 ${
            danger ? "text-bah-red" : "text-bah-heading"
          }`}
        >
          {title}
        </h3>
        <p className="text-bah-subtle text-xs leading-relaxed mb-5">
          {message}
        </p>
        <div className="flex gap-2 justify-end">
          <Button variant="ghost" onClick={onCancel} disabled={loading}>
            Cancel
          </Button>
          {danger ? (
            <Button
              variant="danger"
              onClick={onConfirm}
              disabled={loading}
            >
              {loading ? "Processing..." : confirmLabel ?? "Confirm"}
            </Button>
          ) : (
            <Button onClick={onConfirm} disabled={loading}>
              {loading ? "Processing..." : confirmLabel ?? "Apply"}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
