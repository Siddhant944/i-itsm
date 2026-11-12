import type { SyntheticEvent, ReactNode } from "react";

import { Button } from "./Button";

interface FilterBarProps {
  children: ReactNode;
  onApply: () => void;
  onReset: () => void;
  /** How many filters are narrowing the list, shown so a filtered view is never mistaken for all. */
  activeCount: number;
  extra?: ReactNode | undefined;
}

/** The shared frame around a set of filters: apply on submit, reset, and an active count. */
export function FilterBar({ children, onApply, onReset, activeCount, extra }: FilterBarProps) {
  const submit = (event: SyntheticEvent) => {
    event.preventDefault();
    onApply();
  };
  return (
    <form
      onSubmit={submit}
      aria-label="Filters"
      className="mb-4 rounded-lg border border-line bg-surface p-4"
    >
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{children}</div>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Button type="submit" variant="primary">
          Apply filters
        </Button>
        <Button onClick={onReset}>Reset</Button>
        <span className="text-xs text-muted" data-testid="active-filters">
          {activeCount === 0
            ? "No filters applied"
            : `${String(activeCount)} filter${activeCount === 1 ? "" : "s"} applied`}
        </span>
        <div className="ml-auto flex gap-2">{extra}</div>
      </div>
    </form>
  );
}
