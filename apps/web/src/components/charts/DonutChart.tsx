import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { rotuloExibicao } from "../../lib/caduLabels";
import { useIsMobile } from "../../hooks/useMediaQuery";
import ChartTooltip from "./ChartTooltip";

export type DonutSlice = {
  rotulo: string;
  total: number;
  pct: number;
};

const PALETTE = [
  "#10b981",
  "#8b5cf6",
  "#3b82f6",
  "#f59e0b",
  "#ec4899",
  "#06b6d4",
  "#6366f1",
  "#f43f5e",
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
      <ChartTooltip
        title={rotuloExibicao(data.rotulo, uppercaseLabels)}
        lines={[
          { label: "Total", value: data.total.toLocaleString("pt-BR") },
          { label: "Representa", value: `${data.pct.toLocaleString("pt-BR")}%` },
        ]}
      />
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
  const isMobile = useIsMobile();
  const total = items.reduce((s, i) => s + i.total, 0);
  const slices = items.filter((i) => i.total > 0);
  const chartHeight = isMobile ? 300 : 260;

  return (
    <div className={`chart-panel fx-card donut-chart${isMobile ? " donut-chart--mobile" : ""}`}>
      <h3 className="chart-panel-title">{title}</h3>
      {subtitle && <p className="chart-panel-sub">{subtitle}</p>}

      {slices.length === 0 ? (
        <p className="ingestao-desc" style={{ marginTop: "2rem", marginBottom: "2rem" }}>
          Sem dados.
        </p>
      ) : (
        <div
          className="donut-chart-inner"
          style={{ width: "100%", height: chartHeight, position: "relative" }}
        >
          <ResponsiveContainer>
            <PieChart>
              <Pie
                data={slices}
                cx="50%"
                cy={isMobile ? "42%" : "50%"}
                innerRadius={isMobile ? 52 : 65}
                outerRadius={isMobile ? 80 : 95}
                paddingAngle={2}
                dataKey="total"
                stroke="none"
              >
                {slices.map((_, index) => (
                  <Cell key={`cell-${index}`} fill={PALETTE[index % PALETTE.length]} />
                ))}
              </Pie>
              <Tooltip
                trigger={isMobile ? "click" : "hover"}
                content={<CustomTooltip uppercaseLabels={uppercaseLabels} />}
                wrapperStyle={{ zIndex: 1000, outline: "none" }}
              />
              <Legend
                layout={isMobile ? "horizontal" : "vertical"}
                verticalAlign={isMobile ? "bottom" : "middle"}
                align={isMobile ? "center" : "right"}
                wrapperStyle={
                  isMobile
                    ? { paddingTop: "0.5rem", fontSize: "0.75rem" }
                    : undefined
                }
                formatter={(value, entry: { payload?: DonutSlice }) => {
                  const data = entry.payload;
                  if (!data) return value;
                  const label = rotuloExibicao(data.rotulo, uppercaseLabels);
                  if (isMobile && label.length > 18) {
                    return (
                      <span className="donut-legend-label">
                        {label.substring(0, 18)}… ({data.pct}%)
                      </span>
                    );
                  }
                  return (
                    <span className="donut-legend-label">
                      {label} ({data.pct}%)
                    </span>
                  );
                }}
              />
            </PieChart>
          </ResponsiveContainer>

          {(centerValue || centerLabel) && (
            <div
              className="donut-center-label"
              style={{
                position: "absolute",
                top: isMobile ? "42%" : "50%",
                left: "50%",
                transform: "translate(-50%, -50%)",
                textAlign: "center",
                pointerEvents: "none",
                width: "120px",
              }}
            >
              {centerValue && (
                <div
                  style={{
                    fontSize: isMobile ? "1.05rem" : "1.2rem",
                    fontWeight: 700,
                    color: "var(--fx-text)",
                    lineHeight: 1.2,
                  }}
                >
                  {centerValue}
                </div>
              )}
              {centerLabel && (
                <div
                  style={{
                    fontSize: "0.7rem",
                    textTransform: "uppercase",
                    color: "var(--fx-subtle)",
                    marginTop: "0.1rem",
                  }}
                >
                  {centerLabel}
                </div>
              )}
            </div>
          )}
        </div>
      )}
      {total > 0 && !centerValue && (
        <p
          className="donut-foot"
          style={{ margin: "0", fontSize: "0.8rem", color: "var(--fx-subtle)", textAlign: "center" }}
        >
          Total: {total.toLocaleString("pt-BR")} pessoas
        </p>
      )}
      {isMobile && slices.length > 0 && (
        <p className="chart-panel-touch-hint">Toque na fatia para ver detalhes</p>
      )}
    </div>
  );
}
