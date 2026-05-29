import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { rotuloAmigavel } from "../../lib/caduLabels";

export type StackedBarItem = {
  name: string;
  [key: string]: string | number;
};

type Props = {
  title: string;
  subtitle?: string;
  data: StackedBarItem[];
  keys: { key: string; color: string; label?: string }[];
};

const CustomTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    return (
      <div className="fx-card" style={{ padding: "0.75rem", minWidth: "150px" }}>
        <p style={{ margin: "0 0 0.5rem", fontWeight: 600, color: "var(--fx-text)" }}>
          {rotuloAmigavel(label)}
        </p>
        {payload.map((entry: any, index: number) => (
          <div key={`item-${index}`} style={{ display: "flex", justifyContent: "space-between", gap: "1rem", margin: "0.25rem 0", fontSize: "0.85rem" }}>
            <span style={{ color: entry.color, display: "flex", alignItems: "center", gap: "0.4rem" }}>
              <span style={{ width: 8, height: 8, borderRadius: "50%", background: entry.color }} />
              {entry.name}
            </span>
            <strong style={{ color: "var(--fx-text)" }}>{entry.value.toLocaleString("pt-BR")}</strong>
          </div>
        ))}
      </div>
    );
  }
  return null;
};

export default function StackedBarChartPanel({ title, subtitle, data, keys }: Props) {
  return (
    <div className="chart-panel fx-card">
      <h3 className="chart-panel-title">{title}</h3>
      {subtitle && <p className="chart-panel-sub">{subtitle}</p>}
      
      {data.length === 0 ? (
        <p className="ingestao-desc" style={{ margin: "2rem 0" }}>Sem dados.</p>
      ) : (
        <div style={{ width: "100%", height: 300 }}>
          <ResponsiveContainer>
            <BarChart
              data={data}
              margin={{ top: 20, right: 10, left: 0, bottom: 20 }}
            >
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--fx-border-subtle)" />
              <XAxis 
                dataKey="name" 
                tickFormatter={rotuloAmigavel} 
                axisLine={false} 
                tickLine={false}
                tick={{ fill: "var(--fx-muted)", fontSize: 12 }}
                dy={10}
              />
              <YAxis 
                axisLine={false} 
                tickLine={false}
                tick={{ fill: "var(--fx-muted)", fontSize: 12 }}
                tickFormatter={(val) => val.toLocaleString("pt-BR")}
              />
              <Tooltip cursor={{ fill: "var(--fx-border-subtle)" }} content={<CustomTooltip />} />
              <Legend 
                wrapperStyle={{ paddingTop: "1rem" }}
                formatter={(value) => <span style={{ color: "var(--fx-text-secondary)", fontSize: "0.85rem" }}>{value}</span>}
              />
              {keys.map((k) => (
                <Bar key={k.key} dataKey={k.key} name={k.label || rotuloAmigavel(k.key)} stackId="a" fill={k.color} radius={[0, 0, 0, 0]} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}