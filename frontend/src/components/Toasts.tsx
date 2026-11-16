import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { errorMessage } from "../api/client";

type Kind = "success" | "error" | "info";

interface Toast {
  id: number;
  kind: Kind;
  text: string;
}

interface ToastApi {
  success: (text: string) => void;
  info: (text: string) => void;
  /** Accepts whatever was thrown and shows the sentence the API sent. */
  error: (problem: unknown) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

const LIFETIME_MS = 6000;

const KIND: Record<Kind, string> = {
  success: "border-transparent bg-success text-white",
  error: "border-transparent bg-danger text-white",
  info: "border-transparent bg-inverse text-inverse-ink",
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const push = useCallback(
    (kind: Kind, text: string) => {
      const id = nextId.current++;
      setToasts((current) => [...current.slice(-3), { id, kind, text }]);
      window.setTimeout(() => {
        dismiss(id);
      }, LIFETIME_MS);
    },
    [dismiss],
  );

  const value = useMemo<ToastApi>(
    () => ({
      success: (text) => {
        push("success", text);
      },
      info: (text) => {
        push("info", text);
      },
      error: (problem) => {
        push("error", errorMessage(problem));
      },
    }),
    [push],
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        aria-live="polite"
        className="pointer-events-none fixed right-4 bottom-4 z-50 flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2"
      >
        {toasts.map((toast) => (
          <div
            key={toast.id}
            role={toast.kind === "error" ? "alert" : "status"}
            className={`pointer-events-auto flex items-start justify-between gap-3 rounded-md border px-3 py-2 text-sm shadow-lg ${KIND[toast.kind]}`}
          >
            <span>{toast.text}</span>
            <button
              type="button"
              aria-label="Dismiss"
              className="leading-none opacity-80 hover:opacity-100"
              onClick={() => {
                dismiss(toast.id);
              }}
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components -- the hook belongs with its provider
export function useToasts(): ToastApi {
  const api = useContext(ToastContext);
  if (api === null) throw new Error("useToasts must be used inside <ToastProvider>");
  return api;
}
