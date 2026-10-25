import { useEffect, useState } from "react";
import Ask from "./pages/Ask";
import Findings from "./pages/Findings";
import History from "./pages/History";
import OntologyMap from "./pages/OntologyMap";
import Steward from "./pages/Steward";
import Overview from "./pages/Overview";
import TimeTravel from "./pages/TimeTravel";
import Vocabularies from "./pages/Vocabularies";
import { useTheme } from "./theme";

const PAGES = [
  { path: "overview", label: "Overview", element: <Overview /> },
  { path: "ask", label: "Ask", element: <Ask /> },
  { path: "steward", label: "Steward", element: <Steward /> },
  { path: "history", label: "History", element: <History /> },
  { path: "ontology", label: "Ontology", element: <OntologyMap /> },
  { path: "vocabularies", label: "Vocabularies", element: <Vocabularies /> },
  { path: "findings", label: "Data findings", element: <Findings /> },
  { path: "time", label: "Time", element: <TimeTravel /> },
] as const;

function currentPath(): string {
  const hash = window.location.hash.replace(/^#\/?/, "").split("?")[0];
  return PAGES.some((p) => p.path === hash) ? hash : "overview";
}

export default function App() {
  const [path, setPath] = useState(currentPath);
  const { theme, toggle } = useTheme();

  useEffect(() => {
    const onHash = () => {
      setPath(currentPath());
      window.scrollTo({ top: 0 });
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const page = PAGES.find((p) => p.path === path) ?? PAGES[0];

  return (
    <div className="shell">
      <header className="topbar">
        <div className="topbar-inner">
          <a className="brand" href="#/overview" aria-label="GoNoGo home">
            <span className="brand-mark" aria-hidden="true">
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M3 8.5l3.2 3.2L13 4.5" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </span>
            GoNoGo
          </a>
          <nav className="nav" aria-label="Sections">
            {PAGES.map((p) => (
              <a key={p.path} href={`#/${p.path}`} aria-current={p.path === path ? "page" : undefined}>
                {p.label}
              </a>
            ))}
          </nav>
          <a className="nav-ref" href="./ontology/index.html" target="_blank" rel="noreferrer">Reference docs ↗</a>
          <button className="icon-button" onClick={toggle} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}>
            {theme === "dark" ? (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <circle cx="12" cy="12" r="4" />
                <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
              </svg>
            ) : (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z" />
              </svg>
            )}
          </button>
        </div>
      </header>
      <main key={page.path}>{page.element}</main>
      <footer className="footer">
        <div className="footer-inner">
          <span>
            Real public data from NASA, the Federal Register, and the USPTO. Every synthetic fact carries a generator
            label.
          </span>
          <a href="https://github.com/abh2050/gonogo">Source on GitHub</a>
        </div>
      </footer>
    </div>
  );
}
