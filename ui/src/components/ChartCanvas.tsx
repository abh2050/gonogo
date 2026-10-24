import { Chart, type ChartConfiguration } from "chart.js/auto";
import { useEffect, useRef } from "react";
import { cssVar, useTheme } from "../theme";

/** Draw a Chart.js chart. The factory runs again when the theme changes, so colors follow the page. */
export default function ChartCanvas({
  build,
  label,
  height = 320,
}: {
  build: (colors: ChartColors) => ChartConfiguration;
  label: string;
  height?: number;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const { theme } = useTheme();

  useEffect(() => {
    if (!canvas.current) return;
    const colors = readColors();
    Chart.defaults.font.family = '"Inter Variable", system-ui, sans-serif';
    Chart.defaults.font.size = 13;
    Chart.defaults.color = colors.muted;
    Chart.defaults.borderColor = colors.line;
    const chart = new Chart(canvas.current, build(colors));
    return () => chart.destroy();
    // The factory is rebuilt by the parent on each render; only the theme should restart the chart.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theme, build]);

  return (
    <div className="chart-box" style={{ height }}>
      <canvas ref={canvas} role="img" aria-label={label} />
    </div>
  );
}

export interface ChartColors {
  ink: string;
  muted: string;
  line: string;
  surface: string;
  accent: string;
  amber: string;
  go: string;
  nogo: string;
  counsel: string;
  nodata: string;
  hold: string;
}

export function readColors(): ChartColors {
  return {
    ink: cssVar("--ink"),
    muted: cssVar("--muted"),
    line: cssVar("--line"),
    surface: cssVar("--surface"),
    accent: cssVar("--accent"),
    amber: cssVar("--amber"),
    go: cssVar("--go"),
    nogo: cssVar("--nogo"),
    counsel: cssVar("--counsel"),
    nodata: cssVar("--nodata"),
    hold: cssVar("--hold"),
  };
}
