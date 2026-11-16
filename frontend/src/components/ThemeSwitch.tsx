import { useId, type ReactNode } from "react";

import { THEME_CHOICES, type ThemeChoice, type ThemeState } from "../lib/theme";

const LABEL: Record<ThemeChoice, string> = {
  light: "Light theme",
  dark: "Dark theme",
  system: "Match the system theme",
};

function Icon({ children }: { children: ReactNode }) {
  return (
    <svg
      viewBox="0 0 20 20"
      width="16"
      height="16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

const ICON: Record<ThemeChoice, ReactNode> = {
  light: (
    <Icon>
      <circle cx="10" cy="10" r="3.4" />
      <path d="M10 2.2v1.9M10 15.9v1.9M2.2 10h1.9M15.9 10h1.9M4.5 4.5l1.3 1.3M14.2 14.2l1.3 1.3M4.5 15.5l1.3-1.3M14.2 5.8l1.3-1.3" />
    </Icon>
  ),
  dark: (
    <Icon>
      <path d="M16.4 12.3A6.8 6.8 0 0 1 7.7 3.6a6.8 6.8 0 1 0 8.7 8.7Z" />
    </Icon>
  ),
  system: (
    <Icon>
      <rect x="2.6" y="3.6" width="14.8" height="10" rx="1.6" />
      <path d="M7.2 16.6h5.6M10 13.6v3" />
    </Icon>
  ),
};

/**
 * Light, dark or the system's choice, as one radio group: arrow keys move between the three and
 * the screen reader hears "Light theme, 1 of 3" (D-040). It sits on its own surface, so it reads
 * on the employee's coloured top bar and on the sidebar portals' header alike.
 */
export function ThemeSwitch({ state }: { state: ThemeState }) {
  const name = useId();
  const current: ThemeChoice = state.choice ?? state.theme;
  return (
    <fieldset className="inline-flex items-center rounded-md border border-line bg-surface p-0.5 text-ink">
      <legend className="sr-only">Colour theme</legend>
      {THEME_CHOICES.map((choice) => (
        <label
          key={choice}
          title={LABEL[choice]}
          className={`flex cursor-pointer items-center rounded px-1.5 py-1 has-focus-visible:outline-2 has-focus-visible:outline-accent ${
            current === choice
              ? "bg-accent text-accent-ink"
              : "text-muted hover:bg-raised hover:text-ink"
          }`}
        >
          <input
            type="radio"
            name={name}
            value={choice}
            checked={current === choice}
            onChange={() => {
              state.setChoice(choice);
            }}
            className="sr-only"
          />
          {ICON[choice]}
          <span className="sr-only">{LABEL[choice]}</span>
        </label>
      ))}
    </fieldset>
  );
}
