import { rotuloAmigavel } from "../../lib/caduLabels";

export type DonutSlice = {
  rotulo: string;
  total: number;
  pct: number;
};

const PALETTE = [
  "#5b9fd4",
  "#e87b9f",
  "#6ee7b7",
  "#f0a060",
  "#a78bfa",
  "#f472b6",
  "#94a3b8",
  "#fbbf24",
];

function conicGradient(slices: DonutSlice[]): string {
  if (slices.length === 0) return "conic-gradient(#334155 0% 100%)";
  let acc = 0;
  const stops: string[] = [];
  slices.forEach((s, i) => {
    const color = PALETTE[i % PALETTE.length];
    const end = acc + Math.max(s.pct, 0);
    stops.push(`${color} ${acc}% ${end}%`);
    acc = end;
  });
  if (acc < 100 && slices.length > 0) {
    stops.push(`${PALETTE[slices.length % PALETTE.length]} ${acc}% 100%`);
  }
  return `conic-gradient(${stops.join(", ")})`;
}

type Props = {
  title: string;
  subtitle?: string;
  items: DonutSlice[];
  centerLabel?: string;
  centerValue?: string;
};

export default function DonutChart({ title, subtitle, items, centerLabel, centerValue }: Props) {
  const total = items.reduce((s, i) => s + i.total, 0);
  const slices = items.filter((i) => i.total > 0);

  return (
    <div className="chart-panel fx-card donut-chart">
      <h3 className="chart-panel-title">{title}</h3>
      {subtitle && <p className="chart-panel-sub">{subtitle}</p>}
      {slices.length === 0 ? (
        <p className="ingestao-desc">Sem dados.</p>
      ) : (
        <div className="donut-chart-body">
          <div
            className="donut-ring"
            style={{ background: conicGradient(slices) }}
            role="img"
            aria-label={title}
          >
            <div className="donut-hole">
              {centerValue && <strong className="donut-center-value">{centerValue}</strong>}
              {centerLabel && <span className="donut-center-label">{centerLabel}</span>}
            </div>
          </div>
          <ul className="donut-legend">
            {slices.map((item, i) => (
              <li key={item.rotulo}>
                <span className="donut-swatch" style={{ background: PALETTE[i % PALETTE.length] }} />
                <span className="donut-legend-text">
                  <strong>{rotuloAmigavel(item.rotulo)}</strong>
                  <small>
                    {item.total.toLocaleString("pt-BR")} ({item.pct.toLocaleString("pt-BR")}%)
                  </small>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {total > 0 && !centerValue && (
        <p className="donut-foot">Total: {total.toLocaleString("pt-BR")} pessoas</p>
      )}
    </div>
  );
}
