import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { rotuloAmigavel } from "../../lib/caduLabels";

export type DonutSlice = {
  rotulo: string;
  total: number;
  pct: number;
};

const PALETTE = [
  "#10b981", // emerald-500
  "#8b5cf6", // violet-500
  "#3b82f6", // blue-500
  "#f59e0b", // amber-500
  "#ec4899", // pink-500
  "#06b6d4", // teal-500
  "#6366f1", // indigo-500
  "#f43f5e", // rose-500
];

type Props = {
  title: string;
  subtitle?: string;
  items: DonutSlice[];
  centerLabel?: string;
  centerValue?: string;
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

export default function DonutChart({ title, subtitle, items, centerLabel, centerValue }: Props) {
  const total = items.reduce((s, i) => s + i.total, 0);
  const slices = items.filter((i) => i.total > 0);

  return (
    <div className="chart-panel fx-card donut-chart">
      <h3 className="chart-panel-title">{title}</h3>
      {subtitle && <p className="chart-panel-sub">{subtitle}</p>}
      
      {slices.length === 0 ? (
        <p className="ingestao-desc" style={{ marginTop: "2rem", marginBottom: "2rem" }}>Sem dados.</p>
      ) : (
        <div style={{ width: "100%", height: 260, position: "relative" }}>
          <ResponsiveContainer>
            <PieChart>
              <Pie
                data={slices}
                cx="50%"
                cy="50%"
                innerRadius={65}
                outerRadius={95}
                paddingAngle={2}
                dataKey="total"
                stroke="none"
              >
                {slices.map((_, index) => (
                  <Cell key={`cell-${index}`} fill={PALETTE[index % PALETTE.length]} />
                ))}
              </Pie>
              <Tooltip content={<CustomTooltip />} />
              <Legend 
                layout="vertical" 
                verticalAlign="middle" 
                align="right"
                formatter={(value, entry: any) => {
                  const data = entry.payload;
                  return (
                    <span style={{ color: "var(--fx-text-secondary)", fontSize: "0.85rem" }}>
                      {rotuloAmigavel(data.rotulo)} ({data.pct}%)
                    </span>
                  );
                }}
              />
            </PieChart>
          </ResponsiveContainer>
          
          {(centerValue || centerLabel) && (
            <div style={{
              position: "absolute",
              top: "50%",
              left: "50%",
              transform: "translate(-50%, -50%)",
              textAlign: "center",
              pointerEvents: "none",
              width: "120px"
            }}>
              {centerValue && (
                <div style={{ fontSize: "1.2rem", fontWeight: 700, color: "var(--fx-text)", lineHeight: 1.2 }}>
                  {centerValue}
                </div>
              )}
              {centerLabel && (
                <div style={{ fontSize: "0.7rem", textTransform: "uppercase", color: "var(--fx-subtle)", marginTop: "0.1rem" }}>
                  {centerLabel}
                </div>
              )}
            </div>
          )}
        </div>
      )}
      {total > 0 && !centerValue && (
        <p className="donut-foot" style={{ margin: "0", fontSize: "0.8rem", color: "var(--fx-subtle)", textAlign: "center" }}>
          Total: {total.toLocaleString("pt-BR")} pessoas
        </p>
      )}
    </div>
  );
}