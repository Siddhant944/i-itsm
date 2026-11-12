/**
 * The access token, kept per browser tab (sessionStorage) so that the Employee, Technician and
 * Admin portals can be open side by side with three different people signed in.
 */
const KEY = "iitsm.token";

type Listener = () => void;
const listeners = new Set<Listener>();

export function getToken(): string | null {
  try {
    return window.sessionStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token === null) window.sessionStorage.removeItem(KEY);
    else window.sessionStorage.setItem(KEY, token);
  } catch {
    // Storage can be unavailable (private mode); the session then lasts until reload.
  }
  listeners.forEach((listener) => {
    listener();
  });
}

export function subscribeToken(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
