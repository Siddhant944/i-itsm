import { useEffect, useRef } from "react";

/** The little of Google Identity Services this page uses. */
interface GoogleIdentity {
  accounts: {
    id: {
      initialize: (options: {
        client_id: string;
        callback: (response: { credential: string }) => void;
      }) => void;
      renderButton: (parent: HTMLElement, options: Record<string, unknown>) => void;
    };
  };
}

declare global {
  interface Window {
    google?: GoogleIdentity;
  }
}

const SCRIPT_URL = "https://accounts.google.com/gsi/client";

function loadScript(): Promise<GoogleIdentity> {
  if (window.google !== undefined) return Promise.resolve(window.google);
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = SCRIPT_URL;
    script.async = true;
    script.onload = () => {
      if (window.google !== undefined) resolve(window.google);
      else reject(new Error("Google Sign-In did not load."));
    };
    script.onerror = () => {
      reject(new Error("Google Sign-In could not be loaded."));
    };
    document.head.appendChild(script);
  });
}

/**
 * P4.10: Google's own "Sign in with Google" button. Google hands back an ID token; the API
 * checks it, including that the account is on the campus domain (D-008), and signs in.
 */
export function GoogleSignInButton({
  clientId,
  onCredential,
  onUnavailable,
}: {
  clientId: string;
  onCredential: (credential: string) => void;
  onUnavailable: (message: string) => void;
}) {
  const slot = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let cancelled = false;
    loadScript()
      .then((google) => {
        if (cancelled || slot.current === null) return;
        google.accounts.id.initialize({
          client_id: clientId,
          callback: (response) => {
            onCredential(response.credential);
          },
        });
        google.accounts.id.renderButton(slot.current, {
          theme: "outline",
          size: "large",
          text: "signin_with",
          width: 320,
        });
      })
      .catch((error: unknown) => {
        if (!cancelled) onUnavailable(error instanceof Error ? error.message : String(error));
      });
    return () => {
      cancelled = true;
    };
  }, [clientId, onCredential, onUnavailable]);
  return <div ref={slot} data-testid="google-sign-in" className="flex justify-center" />;
}
