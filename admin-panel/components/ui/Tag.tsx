"use client";

interface TagProps {
  color: string;
  children: React.ReactNode;
}

export function Tag({ color, children }: TagProps) {
  return (
    <span
      className="inline-block rounded px-2 py-0.5 text-[10px] font-semibold border"
      style={{
        background: `${color}15`,
        color,
        borderColor: `${color}25`,
      }}
    >
      {children}
    </span>
  );
}
