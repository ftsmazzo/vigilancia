import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from "recharts";
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

const PALETTES = {
  default: ["#10b981", "#34d399", "#6ee7b7"],
  warm: ["#f59e0b", "#fbbf24", "#fcd34d"],
  cool: ["#3b82f6", "#60a5fa", "#93c5fd"],
};

const CustomTooltip = ({ active, payload }: any) => {
  if (active && payload && payload.length) {
    const data = payload[0].payload;
    return (
      <div className="fx-card" style={{ padding: "0.75rem", minWidth: "150px" }}>
        <p style={{ margin: "0 0 0.5rem", fontWeight: 600, color: "var(--fx-text)" }}>
          {rotuloAmigavel(data.rotulo)}
        </p>
        <p style={{ margin: 0, fontSize: "0.85rem", color: "var(--fx-muted)" }}>
          Total: <strong>{data.total.toLocaleString("pt-BR")}</strong>
        </p>
        <p style={{ margin: "0.25rem 0 0", fontSize: "0.85rem", color: "var(--fx-muted)" }}>
          Representa: <strong>{data.pct.toLocaleString("pt-BR")}%</strong>
        </p>
      </div>
    );
  }
  return null;
};

export default function BarChartPanel({
  title,
  subtitle,
  items,
  maxBars = 12,
  accent = "default",
}: Props) {
  const slice = items.slice(0, maxBars);
  const colors = PALETTES[accent] || PALETTES.default;

  return (
    <div className={`chart-panel fx-card bar-chart-panel bar-chart-panel--${accent}`}>
      <h3 className="chart-panel-title">{title}</h3>
      {subtitle && <p className="chart-panel-sub">{subtitle}</p>}
      
      {slice.length === 0 ? (
        <p className="ingestao-desc" style={{ margin: "2rem 0" }}>Sem dados.</p>
      ) : (
        <div style={{ width: "100%", height: Math.max(200, slice.length * 40) }}>
          <ResponsiveContainer>
            <BarChart
              layout="vertical"
              data={slice}
              margin={{ top: 5, right: 20, left: 10, bottom: 5 }}
            >
              <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="var(--fx-border-subtle)" />
              <XAxis type="number" hide />
              <YAxis 
                type="category" 
                dataKey="rotulo" 
                tickFormatter={(val) => {
                  const label = rotuloAmigavel(val);
                  return label.length > 15 ? label.substring(0, 15) + "..." : label;
                }}
                axisLine={false}
                tickLine={false}
                tick={{ fill: "var(--fx-muted)", fontSize: 12 }}
                width={110}
              />
              <Tooltip cursor={{ fill: "var(--fx-border-subtle)" }} content={<CustomTooltip />} />
              <Bar dataKey="total" radius={[0, 4, 4, 0]} barSize={20}>
                {slice.map((_, index) => (
                  <Cell key={`cell-${index}`} fill={colors[0]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}