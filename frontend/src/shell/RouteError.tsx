import { Button } from "../components/Button";

/**
 * Shown instead of a screen that failed to load or render (P5 review). The usual cause is a
 * redeploy: a tab opened earlier asks for a screen's chunk that the new build no longer has,
 * and only a reload fetches the new one. Without this, React Router shows its own developer
 * error page.
 */
export function RouteError() {
  return (
    <div role="alert" className="mx-auto max-w-md p-10 text-ink">
      <h1 className="text-lg font-semibold">This screen could not be opened</h1>
      <p className="mt-2 text-sm text-muted">
        The app may have been updated since this tab was opened. Reloading usually fixes it; your
        sign-in is kept.
      </p>
      <Button
        className="mt-4"
        onClick={() => {
          window.location.reload();
        }}
      >
        Reload
      </Button>
    </div>
  );
}
