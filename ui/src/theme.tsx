import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type Theme = "light" | "dark";

interface ThemeValue {
  theme: Theme;
  toggle: () => void;
}

const ThemeContext = createContext<ThemeValue>({ theme: "light", toggle: () => undefined });

function initialTheme(): Theme {
  // A link such as #/findings?theme=dark picks a theme for that visit.
  const requested = new URLSearchParams(window.location.hash.split("?")[1] ?? "").get("theme");
  if (requested === "light" || requested === "dark") return requested;
  const attr = document.documentElement.getAttribute("data-theme");
  if (attr === "light" || attr === "dark") return attr;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(initialTheme);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  const toggle = useCallback(() => {
    setTheme((current) => {
      const next: Theme = current === "dark" ? "light" : "dark";
      try {
        localStorage.setItem("gonogo-theme", next);
      } catch {
        // Storage can be blocked. The theme still changes for this visit.
      }
      return next;
    });
  }, []);

  const value = useMemo(() => ({ theme, toggle }), [theme, toggle]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export const useTheme = () => useContext(ThemeContext);

/** Read a CSS custom property, so canvas and SVG drawings use the same colors as the page. */
export function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
