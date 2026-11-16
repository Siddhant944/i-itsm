import {
  useId,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";

const CONTROL =
  "w-full rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink placeholder:text-muted focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-60";

interface FieldShell {
  label: string;
  hint?: string | undefined;
  error?: string | undefined;
}

function Shell({
  id,
  label,
  hint,
  error,
  children,
}: FieldShell & { id: string; children: ReactNode }) {
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-medium text-ink">
        {label}
      </label>
      {children}
      {hint !== undefined && error === undefined && (
        <p className="mt-1 text-xs text-muted">{hint}</p>
      )}
      {error !== undefined && (
        <p role="alert" className="mt-1 text-xs text-bad">
          {error}
        </p>
      )}
    </div>
  );
}

export function TextField({
  label,
  hint,
  error,
  className = "",
  ...rest
}: FieldShell & InputHTMLAttributes<HTMLInputElement>) {
  const id = useId();
  return (
    <Shell id={id} label={label} hint={hint} error={error}>
      <input
        id={id}
        aria-invalid={error !== undefined}
        className={`${CONTROL} ${className}`}
        {...rest}
      />
    </Shell>
  );
}

export function TextArea({
  label,
  hint,
  error,
  className = "",
  ...rest
}: FieldShell & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const id = useId();
  return (
    <Shell id={id} label={label} hint={hint} error={error}>
      <textarea
        id={id}
        rows={4}
        aria-invalid={error !== undefined}
        className={`${CONTROL} ${className}`}
        {...rest}
      />
    </Shell>
  );
}

export function SelectField({
  label,
  hint,
  error,
  className = "",
  children,
  ...rest
}: FieldShell & SelectHTMLAttributes<HTMLSelectElement>) {
  const id = useId();
  return (
    <Shell id={id} label={label} hint={hint} error={error}>
      <select
        id={id}
        aria-invalid={error !== undefined}
        className={`${CONTROL} ${className}`}
        {...rest}
      >
        {children}
      </select>
    </Shell>
  );
}

/** A labelled group of on/off chips, for multi-value filters and skill pickers. */
export function ChipGroup<Value extends string | number>({
  label,
  options,
  selected,
  onChange,
}: {
  label: string;
  options: readonly { value: Value; label: string }[];
  selected: readonly Value[];
  onChange: (next: Value[]) => void;
}) {
  return (
    <fieldset>
      <legend className="mb-1 text-sm font-medium text-ink">{label}</legend>
      <div className="flex flex-wrap gap-1.5">
        {options.map((option) => {
          const on = selected.includes(option.value);
          return (
            <button
              key={option.value}
              type="button"
              aria-pressed={on}
              onClick={() => {
                onChange(
                  on ? selected.filter((v) => v !== option.value) : [...selected, option.value],
                );
              }}
              className={`rounded-full border px-2.5 py-1 text-xs font-medium transition-colors focus-visible:outline-2 focus-visible:outline-accent ${on ? "border-accent bg-accent text-accent-ink" : "border-line bg-surface text-muted hover:bg-raised"}`}
            >
              {option.label}
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}
