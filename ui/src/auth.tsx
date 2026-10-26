import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import type { Role } from "./api";

// In AWS mode the app signs in against Cognito and sends the ID token with every call. API Gateway checks the token
// and the Lambdas read the user and role from it. The page reads the same claims to show who is signed in, and it
// never decides anything from them: a changed token fails at the gateway.

export interface Config {
  mode: "demo" | "aws";
  region?: string;
  userPoolClientId?: string;
  neptune?: boolean;
}

export interface Identity {
  name: string;
  role: Role;
  expires: number;
}

interface AuthValue {
  config: Config | null;
  identity: Identity | null;
  signIn: (username: string, password: string) => Promise<void>;
  signOut: () => void;
}

const KEY = "gonogo-token";
const AuthContext = createContext<AuthValue>({ config: null, identity: null, signIn: async () => undefined, signOut: () => undefined });

let token: string | null = null;
export const authHeader = (): Record<string, string> => (token ? { Authorization: token } : {});

function read(jwt: string): Identity | null {
  try {
    const claims = JSON.parse(atob(jwt.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
    const groups: string[] = Array.isArray(claims["cognito:groups"]) ? claims["cognito:groups"] : [];
    if (groups.length !== 1) return null;
    return { name: String(claims["cognito:username"] ?? claims.sub), role: groups[0] as Role, expires: Number(claims.exp) * 1000 };
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<Config | null>(null);
  const [identity, setIdentity] = useState<Identity | null>(null);

  const adopt = useCallback((jwt: string | null) => {
    token = jwt;
    const who = jwt ? read(jwt) : null;
    setIdentity(who && who.expires > Date.now() ? who : null);
    try {
      if (who && jwt) sessionStorage.setItem(KEY, jwt);
      else sessionStorage.removeItem(KEY);
    } catch {
      // Storage can be blocked. The sign-in lasts for this page view.
    }
  }, []);

  useEffect(() => {
    fetch("./config.json", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : { mode: "demo" }))
      .catch(() => ({ mode: "demo" }))
      .then((c: Config) => {
        setConfig(c);
        if (c.mode === "aws") {
          try {
            adopt(sessionStorage.getItem(KEY));
          } catch {
            adopt(null);
          }
        }
      });
  }, [adopt]);

  const signIn = useCallback(
    async (username: string, password: string) => {
      if (!config?.userPoolClientId) throw new Error("This deployment has no sign-in configured.");
      const res = await fetch(`https://cognito-idp.${config.region}.amazonaws.com/`, {
        method: "POST",
        headers: { "Content-Type": "application/x-amz-json-1.1", "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth" },
        body: JSON.stringify({ AuthFlow: "USER_PASSWORD_AUTH", ClientId: config.userPoolClientId, AuthParameters: { USERNAME: username, PASSWORD: password } }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.message ?? "Sign-in failed.");
      if (body.ChallengeName) throw new Error("This user must set a new password first. Ask the deployer to reset it.");
      const jwt: string = body.AuthenticationResult.IdToken;
      if (!read(jwt)) throw new Error("This user must belong to exactly one role group.");
      adopt(jwt);
    },
    [config, adopt],
  );

  const signOut = useCallback(() => adopt(null), [adopt]);
  const value = useMemo(() => ({ config, identity, signIn, signOut }), [config, identity, signIn, signOut]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export const useAuth = () => useContext(AuthContext);
