import type { ReactNode } from "react";

import { errorMessage } from "../api/client";
import { Button } from "./Button";

/** Placeholder rows shown while a list loads. */
export function Skeleton({ rows = 4, label = "Loading" }: { rows?: number; label?: string }) {
  return (
    <div role="status" aria-label={label} className="animate-pulse space-y-3">
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="h-9 rounded-md bg-raised" />
      ))}
      <span className="sr-only">{label}…</span>
    </div>
  );
}

export function EmptyState({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: string | undefined;
  action?: ReactNode | undefined;
}) {
  return (
    <div className="rounded-lg border border-dashed border-line px-6 py-10 text-center">
      <p className="font-medium text-ink">{title}</p>
      {hint !== undefined && <p className="mt-1 text-sm text-muted">{hint}</p>}
      {action !== undefined && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <div
      role="alert"
      className="rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-700 dark:text-red-300"
    >
      <p className="font-medium">{errorMessage(error)}</p>
      {onRetry !== undefined && (
        <Button small className="mt-2" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

interface AsyncLike<T> {
  isPending: boolean;
  isError: boolean;
  error: unknown;
  data: T | undefined;
  refetch: () => unknown;
}

/**
 * The three states every API-backed view has to handle (AGENTS.md: loading, empty, error),
 * in one place so no screen can forget one.
 */
export function QueryView<T>({
  query,
  isEmpty,
  empty,
  loadingLabel,
  children,
}: {
  query: AsyncLike<T>;
  isEmpty?: (data: T) => boolean;
  empty?: ReactNode | undefined;
  loadingLabel?: string | undefined;
  children: (data: T) => ReactNode;
}) {
  if (query.isPending) return <Skeleton label={loadingLabel ?? "Loading"} />;
  if (query.isError || query.data === undefined) {
    return (
      <ErrorState
        error={query.error}
        onRetry={() => {
          void query.refetch();
        }}
      />
    );
  }
  if (isEmpty?.(query.data) === true)
    return <>{empty ?? <EmptyState title="Nothing here yet" />}</>;
  return <>{children(query.data)}</>;
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string | undefined;
  actions?: ReactNode | undefined;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-ink">{title}</h1>
        {subtitle !== undefined && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
      </div>
      {actions !== undefined && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function Card({
  title,
  children,
  className = "",
  actions,
}: {
  title?: string | undefined;
  children: ReactNode;
  className?: string | undefined;
  actions?: ReactNode | undefined;
}) {
  return (
    <section className={`rounded-lg border border-line bg-surface p-4 shadow-xs ${className}`}>
      {(title !== undefined || actions !== undefined) && (
        <div className="mb-3 flex items-center justify-between gap-2">
          {title !== undefined && <h2 className="text-sm font-semibold text-ink">{title}</h2>}
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}
