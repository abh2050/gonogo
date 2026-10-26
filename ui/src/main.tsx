import "@fontsource-variable/inter";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Analytics } from "@vercel/analytics/react";
import App from "./App";
import { AuthProvider } from "./auth";
import { SessionProvider } from "./session";
import { ThemeProvider } from "./theme";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
      <AuthProvider>
        <SessionProvider>
          <App />
          <Analytics />
        </SessionProvider>
      </AuthProvider>
    </ThemeProvider>
  </StrictMode>,
);
