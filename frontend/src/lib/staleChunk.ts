const RELOADED_AT = "iitsm.reloaded-for-chunk";

/**
 * Vite fires ``vite:preloadError`` when a screen's chunk cannot be fetched. Reload once to pick
 * up the new build; if that reload happened in the last ten seconds, stop and let RouteError
 * say so rather than reloading for ever.
 */
export function reloadOnStaleChunk(now: () => number = Date.now): void {
  window.addEventListener("vite:preloadError", (event) => {
    try {
      const last = Number(window.sessionStorage.getItem(RELOADED_AT) ?? 0);
      if (now() - last < 10_000) return;
      window.sessionStorage.setItem(RELOADED_AT, String(now()));
    } catch {
      return; // no storage: no way to avoid a loop, so leave it to RouteError
    }
    event.preventDefault();
    window.location.reload();
  });
}
