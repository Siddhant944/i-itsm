/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** API origin; empty means same origin (Vite proxy in dev, nginx in Docker). */
  readonly VITE_API_URL?: string;
  readonly VITE_GOOGLE_CLIENT_ID?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
