import { ReactNode } from "react";

export function MetricCard({
  label,
  value,
  delta,
  sublabel,
  children,
}: {
  label: string;
  value: string;
  delta?: { value: string; positive?: boolean | null };
  sublabel?: string;
  children?: ReactNode;
}) {
  const deltaColor =
    delta?.positive === true
      ? "text-emerald-500"
      : delta?.positive === false
      ? "text-rose-500"
      : "text-zinc-400";
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-950 p-4">
      <div className="text-xs uppercase tracking-wider text-zinc-500">
        {label}
      </div>
      <div className="mt-1 flex items-baseline gap-2">
        <div className="text-2xl font-semibold tabular-nums text-zinc-50">
          {value}
        </div>
        {delta && (
          <div className={`text-sm tabular-nums ${deltaColor}`}>
            {delta.value}
          </div>
        )}
      </div>
      {sublabel && (
        <div className="mt-1 text-xs text-zinc-500">{sublabel}</div>
      )}
      {children && <div className="mt-3">{children}</div>}
    </div>
  );
}
