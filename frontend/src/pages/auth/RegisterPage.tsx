import { useState, type SyntheticEvent } from "react";
import { Link, Navigate } from "react-router";

import { ApiError, errorMessage } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { portalOf } from "../../auth/portal";
import { Button } from "../../components/Button";
import { TextField } from "../../components/Field";
import { PORTAL_HOME } from "../../shell/nav";
import { AuthFrame } from "./LoginPage";

/** Self-registration creates an Employee; other roles are given by an administrator (D-008). */
export function RegisterPage() {
  const { status, user, register } = useAuth();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fields, setFields] = useState<Readonly<Record<string, string>>>({});
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (status === "signed-in" && user !== null) {
    return <Navigate to={PORTAL_HOME[portalOf(user)]} replace />;
  }

  const submit = (event: SyntheticEvent) => {
    event.preventDefault();
    setBusy(true);
    setProblem(null);
    setFields({});
    register(fullName.trim(), email.trim(), password)
      .catch((error: unknown) => {
        if (error instanceof ApiError && Object.keys(error.fieldErrors).length > 0) {
          setFields(error.fieldErrors);
        } else {
          setProblem(errorMessage(error));
        }
      })
      .finally(() => {
        setBusy(false);
      });
  };

  return (
    <AuthFrame title="Create an account">
      <form onSubmit={submit} className="space-y-4" noValidate>
        <TextField
          label="Full name"
          autoComplete="name"
          required
          value={fullName}
          error={fields.full_name}
          onChange={(event) => {
            setFullName(event.target.value);
          }}
        />
        <TextField
          label="Email"
          type="email"
          autoComplete="username"
          required
          value={email}
          error={fields.email}
          onChange={(event) => {
            setEmail(event.target.value);
          }}
        />
        <TextField
          label="Password"
          type="password"
          autoComplete="new-password"
          required
          hint="At least 8 characters."
          value={password}
          error={fields.password}
          onChange={(event) => {
            setPassword(event.target.value);
          }}
        />
        {problem !== null && (
          <p role="alert" className="text-sm text-red-600">
            {problem}
          </p>
        )}
        <Button
          type="submit"
          variant="primary"
          className="w-full"
          busy={busy}
          disabled={fullName.trim() === "" || email.trim() === "" || password === ""}
        >
          Create account
        </Button>
      </form>
      <p className="mt-4 text-center text-sm text-muted">
        Already registered?{" "}
        <Link to="/login" className="font-medium text-accent underline">
          Sign in
        </Link>
      </p>
    </AuthFrame>
  );
}
