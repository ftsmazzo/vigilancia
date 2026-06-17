import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import ChartTooltip from "./ChartTooltip";

export type LineChartPoint = {
  rotulo: string;
  valor: number;
};

type Props = {
  title: string;
  items: LineChartPoint[];
  color?: string;
  emptyMessage?: string;
};

export default function LineChartPanel({
  title,
  items,
  color = "#2563eb",
  emptyMessage = "Sem dados para exibir.",
}: Props) {
  return (
    <div className="chart-panel fx-card">
      <h3 className="chart-panel-title">{title}</h3>
      {items.length === 0 ? (
        <p className="ingestao-desc" style={{ margin: "2rem 0" }}>
          {emptyMessage}
        </p>
      ) : (
        <div style={{ width: "100%", height: 280 }}>
          <ResponsiveContainer>
            <LineChart data={items} margin={{ top: 12, right: 12, left: 0, bottom: 8 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--fx-border-subtle)" />
              <XAxis
                dataKey="rotulo"
                axisLine={false}
                tickLine={false}
                tick={{ fill: "var(--fx-muted)", fontSize: 12 }}
                dy={8}
              />
              <YAxis
                axisLine={false}
                tickLine={false}
                tick={{ fill: "var(--fx-muted)", fontSize: 12 }}
                tickFormatter={(v) => Number(v).toLocaleString("pt-BR")}
                width={48}
              />
              <Tooltip
                content={({ active, payload }) => {
                  if (!active || !payload?.length) return null;
                  const p = payload[0].payload as LineChartPoint;
                  return (
                    <ChartTooltip
                      title={p.rotulo}
                      lines={[{ label: "Famílias", value: p.valor.toLocaleString("pt-BR") }]}
                    />
                  );
                }}
              />
              <Line
                type="monotone"
                dataKey="valor"
                stroke={color}
                strokeWidth={2.5}
                dot={{ r: 4, fill: color, strokeWidth: 0 }}
                activeDot={{ r: 6 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
