import { useState } from "react";
import { ROLE_LABEL } from "../api";
import { useAuth } from "../auth";

export default function SignIn() {
  const { signIn } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  return (
    <div className="page signin">
      <header className="page-head">
        <div className="eyebrow">AWS deployment</div>
        <h1>Sign in to GoNoGo</h1>
        <p className="lede">
          This copy of GoNoGo runs on AWS. Your user belongs to one role, and Cognito puts that role in your token. API
          Gateway checks the token on every call, and Cedar decides what the role may do. The public demo, by contrast,
          lets you type your own role.
        </p>
      </header>
      <form
        className="card form-grid"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError(null);
          try {
            await signIn(username.trim(), password);
          } catch (err) {
            setError((err as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <label className="span-2">
          User name
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required />
        </label>
        <label className="span-2">
          Password
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
        </label>
        <button className="button primary" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
        {error ? (
          <div className="error span-all" role="alert">
            {error}
          </div>
        ) : null}
      </form>
      <p className="muted small">
        The roles are {Object.values(ROLE_LABEL).join(", ")}. A user in more than one group is refused, so nobody can play
        both parts of a two-person rule.
      </p>
    </div>
  );
}
