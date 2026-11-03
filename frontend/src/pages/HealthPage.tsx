import { useHealth } from "../api/health";

/** P0 placeholder: shows API health with explicit loading, error and success states. */
export function HealthPage() {
  const health = useHealth();

  return (
    <main className="mx-auto flex min-h-screen max-w-xl flex-col justify-center gap-6 px-4">
      <header>
        <h1 className="text-3xl font-semibold text-slate-900">I-ITSM</h1>
        <p className="text-slate-600">Campus IT incident reporting and resolution</p>
      </header>

      <section
        aria-live="polite"
        className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
      >
        <h2 className="mb-2 text-sm font-medium tracking-wide text-slate-500 uppercase">
          System status
        </h2>
        {health.isPending && <p role="status">Checking the API…</p>}
        {health.isError && (
          <div role="alert" className="text-red-700">
            <p>The API is unreachable: {health.error.message}</p>
            <button
              type="button"
              className="mt-3 rounded-md bg-red-700 px-3 py-1.5 text-sm text-white hover:bg-red-800"
              onClick={() => void health.refetch()}
            >
              Retry
            </button>
          </div>
        )}
        {health.isSuccess && (
          <dl className="grid grid-cols-2 gap-y-1 text-sm">
            <dt className="text-slate-500">API</dt>
            <dd data-testid="api-status" className="font-medium text-slate-900">
              {health.data.status}
            </dd>
            <dt className="text-slate-500">Database</dt>
            <dd className="font-medium text-slate-900">{health.data.database}</dd>
            <dt className="text-slate-500">Version</dt>
            <dd className="text-slate-900">{health.data.version}</dd>
            <dt className="text-slate-500">Environment</dt>
            <dd className="text-slate-900">{health.data.env}</dd>
          </dl>
        )}
      </section>
    </main>
  );
}
