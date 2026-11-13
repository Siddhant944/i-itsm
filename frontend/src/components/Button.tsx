import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary" | "danger" | "ghost";

const VARIANT: Record<Variant, string> = {
  primary: "bg-accent text-accent-ink hover:bg-accent-strong border-transparent",
  secondary: "bg-surface text-ink border-line hover:bg-raised",
  danger: "bg-danger text-white hover:bg-danger-strong border-transparent",
  ghost: "bg-transparent text-ink border-transparent hover:bg-raised",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant | undefined;
  /** Shows the action is running and blocks a second click. */
  busy?: boolean | undefined;
  small?: boolean | undefined;
  children: ReactNode;
}

export function Button({
  variant = "secondary",
  busy = false,
  small = false,
  disabled,
  className = "",
  children,
  type = "button",
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled === true || busy}
      aria-busy={busy}
      className={`inline-flex items-center justify-center gap-2 rounded-md border font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50 ${small ? "px-2.5 py-1 text-xs" : "px-3.5 py-2 text-sm"} ${VARIANT[variant]} ${className}`}
      {...rest}
    >
      {busy ? "Working…" : children}
    </button>
  );
}
