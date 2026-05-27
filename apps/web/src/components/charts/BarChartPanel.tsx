import { rotuloAmigavel } from "../../lib/caduLabels";

export type BarItem = {
  rotulo: string;
  total: number;
  pct: number;
};

type Props = {
  title: string;
  subtitle?: string;
  items: BarItem[];
  maxBars?: number;
  accent?: "default" | "warm" | "cool";
};

export default function BarChartPanel({
  title,
  subtitle,
  items,
  maxBars = 12,
  accent = "default",
}: Props) {
  const slice = items.slice(0, maxBars);
  const max = Math.max(...slice.map((i) => i.total), 1);

  return (
    <div className={`chart-panel fx-card bar-chart-panel bar-chart-panel--${accent}`}>
      <h3 className="chart-panel-title">{title}</h3>
      {subtitle && <p className="chart-panel-sub">{subtitle}</p>}
      {slice.length === 0 ? (
        <p className="ingestao-desc">Sem dados.</p>
      ) : (
        <ul className="chart-bars" aria-label={title}>
          {slice.map((item) => (
            <li key={item.rotulo} className="chart-bar-row">
              <span className="chart-bar-label" title={item.rotulo}>
                {rotuloAmigavel(item.rotulo)}
              </span>
              <div className="chart-bar-track">
                <div
                  className="chart-bar-fill"
                  style={{ width: `${Math.max(4, (item.total / max) * 100)}%` }}
                />
              </div>
              <span className="chart-bar-value">
                {item.total.toLocaleString("pt-BR")}{" "}
                <small>({item.pct.toLocaleString("pt-BR")}%)</small>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
