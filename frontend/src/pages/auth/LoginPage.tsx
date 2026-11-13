import { type SyntheticEvent, useCallback, useState } from "react";
import { Link, Navigate } from "react-router";

import { ApiError, errorMessage } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { portalOf } from "../../auth/portal";
import { Button } from "../../components/Button";
import { TextField } from "../../components/Field";
import { PORTAL_HOME } from "../../shell/nav";
import { GoogleSignInButton } from "../../components/GoogleSignInButton";

export function AuthFrame({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-page px-4 py-10 text-ink">
      <div className="w-full max-w-sm">
        <p className="text-center text-sm font-semibold tracking-widest text-accent uppercase">
          I-ITSM
        </p>
        <h1 className="mt-1 mb-6 text-center text-2xl font-semibold">{title}</h1>
        <div className="rounded-lg border border-line bg-surface p-6 shadow-sm">{children}</div>
      </div>
    </div>
  );
}

export function LoginPage() {
  const { status, user, signIn, signInWithGoogle } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const googleClientId = import.meta.env.VITE_GOOGLE_CLIENT_ID ?? "";
  const onGoogle = useCallback(
    (credential: string) => {
      setProblem(null);
      signInWithGoogle(credential).catch((error: unknown) => {
        setProblem(errorMessage(error));
      });
    },
    [signInWithGoogle],
  );
  const onGoogleUnavailable = useCallback((message: string) => {
    setProblem(message);
  }, []);

  if (status === "signed-in" && user !== null) {
    return <Navigate to={PORTAL_HOME[portalOf(user)]} replace />;
  }

  const submit = (event: SyntheticEvent) => {
    event.preventDefault();
    setBusy(true);
    setProblem(null);
    signIn(email.trim(), password)
      .catch((error: unknown) => {
        // D-019: the API gives one answer for every failure, so we explain the possibilities.
        setProblem(
          error instanceof ApiError && error.status === 401
            ? "That email and password did not sign you in. After five failed attempts an account is locked for 15 minutes."
            : errorMessage(error),
        );
      })
      .finally(() => {
        setBusy(false);
      });
  };

  return (
    <AuthFrame title="Sign in">
      <form onSubmit={submit} className="space-y-4" noValidate>
        <TextField
          label="Email"
          type="email"
          autoComplete="username"
          required
          value={email}
          onChange={(event) => {
            setEmail(event.target.value);
          }}
        />
        <TextField
          label="Password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => {
            setPassword(event.target.value);
          }}
        />
        {problem !== null && (
          <p role="alert" className="text-sm text-bad">
            {problem}
          </p>
        )}
        <Button
          type="submit"
          variant="primary"
          className="w-full"
          busy={busy}
          disabled={email.trim() === "" || password === ""}
        >
          Sign in
        </Button>
      </form>
      {googleClientId !== "" && (
        <div className="mt-4 space-y-3">
          <p className="text-center text-xs text-muted">or, with your campus Google account</p>
          <GoogleSignInButton
            clientId={googleClientId}
            onCredential={onGoogle}
            onUnavailable={onGoogleUnavailable}
          />
        </div>
      )}
      <p className="mt-4 text-center text-sm text-muted">
        New here?{" "}
        <Link to="/register" className="font-medium text-accent underline">
          Create an account
        </Link>
      </p>
    </AuthFrame>
  );
}
