/** Weighted workload against the 10-point cap (blueprint §5.3, BR-06). */
export function LoadBar({ load, max }: { load: number; max: number }) {
  const share = max <= 0 ? 0 : Math.min(1, load / max);
  const tone = share >= 1 ? "bg-danger" : share >= 0.7 ? "bg-caution" : "bg-success";
  return (
    <div className="flex items-center gap-2">
      <div
        role="meter"
        aria-valuemin={0}
        aria-valuemax={max}
        aria-valuenow={load}
        aria-label="Workload"
        className="h-2 w-24 overflow-hidden rounded-full bg-raised"
      >
        <div className={`h-full ${tone}`} style={{ width: `${String(share * 100)}%` }} />
      </div>
      <span className="text-xs whitespace-nowrap text-muted">
        {String(load)} / {String(max)}
      </span>
    </div>
  );
}
