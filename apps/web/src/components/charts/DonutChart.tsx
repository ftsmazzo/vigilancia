import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { rotuloExibicao } from "../../lib/caduLabels";

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
  uppercaseLabels?: boolean;
};

const CustomTooltip = ({
  active,
  payload,
  uppercaseLabels,
}: {
  active?: boolean;
  payload?: Array<{ payload: DonutSlice }>;
  uppercaseLabels?: boolean;
}) => {
  if (active && payload && payload.length) {
    const data = payload[0].payload;
    return (
      <div className="fx-card chart-tooltip">
        <p className="chart-tooltip-title">{rotuloExibicao(data.rotulo, uppercaseLabels)}</p>
        <p className="chart-tooltip-line">
          Total: <strong>{data.total.toLocaleString("pt-BR")}</strong>
        </p>
        <p className="chart-tooltip-line">
          Representa: <strong>{data.pct.toLocaleString("pt-BR")}%</strong>
        </p>
      </div>
    );
  }
  return null;
};

export default function DonutChart({
  title,
  subtitle,
  items,
  centerLabel,
  centerValue,
  uppercaseLabels = false,
}: Props) {
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
              <Tooltip content={<CustomTooltip uppercaseLabels={uppercaseLabels} />} />
              <Legend 
                layout="vertical" 
                verticalAlign="middle" 
                align="right"
                formatter={(value, entry: { payload?: DonutSlice }) => {
                  const data = entry.payload;
                  if (!data) return value;
                  return (
                    <span className="donut-legend-label">
                      {rotuloExibicao(data.rotulo, uppercaseLabels)} ({data.pct}%)
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