"use client";

export function Pulse({ color }: { color: string }) {
  return (
    <span
      className="inline-block h-2 w-2 rounded-full"
      style={{
        background: color,
        boxShadow: `0 0 8px ${color}60`,
      }}
    />
  );
}
