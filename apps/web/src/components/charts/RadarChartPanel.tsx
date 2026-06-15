import { Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, ResponsiveContainer, Tooltip } from "recharts";
import { rotuloAmigavel } from "../../lib/caduLabels";
import { useIsMobile } from "../../hooks/useMediaQuery";
import ChartTooltip from "./ChartTooltip";

export type RadarItem = {
  name: string;
  [key: string]: string | number;
};

type Props = {
  title: string;
  subtitle?: string;
  data: RadarItem[];
  dataKey: string;
  fill?: string;
  stroke?: string;
};

const CustomTooltip = ({ active, payload }: { active?: boolean; payload?: Array<{ payload: RadarItem; value: number; stroke?: string }> }) => {
  if (active && payload && payload.length) {
    const data = payload[0].payload;
    return (
      <ChartTooltip
        title={rotuloAmigavel(data.name)}
        lines={[{ label: "Valor", value: payload[0].value.toLocaleString("pt-BR") }]}
      />
    );
  }
  return null;
};

export default function RadarChartPanel({ title, subtitle, data, dataKey, fill = "rgba(16, 185, 129, 0.4)", stroke = "#10b981" }: Props) {
  const isMobile = useIsMobile();
  return (
    <div className="chart-panel fx-card">
      <h3 className="chart-panel-title">{title}</h3>
      {subtitle && <p className="chart-panel-sub">{subtitle}</p>}
      
      {data.length === 0 ? (
        <p className="ingestao-desc" style={{ margin: "2rem 0" }}>Sem dados.</p>
      ) : (
        <div style={{ width: "100%", height: 300 }}>
          <ResponsiveContainer>
            <RadarChart cx="50%" cy="50%" outerRadius="75%" data={data}>
              <PolarGrid stroke="var(--fx-border)" />
              <PolarAngleAxis 
                dataKey="name" 
                tickFormatter={(val) => {
                  const label = rotuloAmigavel(val);
                  return label.length > 12 ? label.substring(0, 12) + "..." : label;
                }}
                tick={{ fill: "var(--fx-muted)", fontSize: 11 }}
              />
              <PolarRadiusAxis angle={30} domain={[0, 'auto']} tick={{ fill: "var(--fx-subtle)", fontSize: 10 }} />
              <Tooltip
                trigger={isMobile ? "click" : "hover"}
                content={<CustomTooltip />}
                wrapperStyle={{ zIndex: 1000, outline: "none" }}
              />
              <Radar name={title} dataKey={dataKey} stroke={stroke} fill={fill} fillOpacity={0.6} />
            </RadarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}