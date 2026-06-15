import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
  LabelList,
} from "recharts";
import { rotuloExibicao } from "../../lib/caduLabels";
import { useIsMobile } from "../../hooks/useMediaQuery";
import ChartTooltip from "./ChartTooltip";

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
  accent?: "default" | "warm" | "cool" | "spectrum";
  uppercaseLabels?: boolean;
};

const PALETTES = {
  default: ["#10b981", "#34d399", "#6ee7b7", "#059669"],
  warm: ["#dc2626", "#ea580c", "#ca8a04", "#f59e0b", "#fbbf24"],
  cool: ["#1e3a8a", "#2563eb", "#3b82f6", "#60a5fa", "#93c5fd"],
  spectrum: ["#2563eb", "#16a34a", "#ca8a04", "#ea580c", "#9333ea", "#dc2626", "#0891b2", "#64748b"],
};

const CustomTooltip = ({
  active,
  payload,
  uppercaseLabels,
}: {
  active?: boolean;
  payload?: Array<{ payload: BarItem }>;
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

function fmtBarLabel(val: number | string): string {
  const n = typeof val === "number" ? val : Number(val);
  if (Number.isNaN(n)) return "";
  return n.toLocaleString("pt-BR");
}

export default function BarChartPanel({
  title,
  subtitle,
  items,
  maxBars = 12,
  accent = "default",
  uppercaseLabels = false,
}: Props) {
  const isMobile = useIsMobile();
  const slice = items.filter((i) => i.total > 0).slice(0, maxBars);
  const colors = PALETTES[accent] || PALETTES.default;
  const chartHeight = Math.max(isMobile ? 200 : 220, slice.length * (isMobile ? 40 : 44));
  const labelMax = isMobile ? 14 : 22;
  const yAxisWidth = isMobile ? 100 : uppercaseLabels ? 148 : 128;

  return (
    <div className={`chart-panel fx-card bar-chart-panel bar-chart-panel--${accent}`}>
      <h3 className="chart-panel-title">{title}</h3>
      {subtitle && <p className="chart-panel-sub">{subtitle}</p>}

      {slice.length === 0 ? (
        <p className="chart-panel-empty">Sem dados para o recorte selecionado.</p>
      ) : (
        <div className="bar-chart-panel-wrap" style={{ height: chartHeight }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              layout="vertical"
              data={slice}
              margin={{
                top: 8,
                right: isMobile ? 8 : 56,
                left: 4,
                bottom: 8,
              }}
            >
              <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="var(--fx-border-subtle)" />
              <XAxis type="number" hide />
              <YAxis
                type="category"
                dataKey="rotulo"
                tickFormatter={(val) => {
                  const label = rotuloExibicao(String(val), uppercaseLabels);
                  return label.length > labelMax ? `${label.substring(0, labelMax)}…` : label;
                }}
                axisLine={false}
                tickLine={false}
                tick={{ fill: "var(--fx-muted)", fontSize: isMobile ? 10 : 11, fontWeight: 600 }}
                width={yAxisWidth}
              />
              <Tooltip
                trigger={isMobile ? "click" : "hover"}
                cursor={{ fill: "var(--fx-border-subtle)" }}
                content={<CustomTooltip uppercaseLabels={uppercaseLabels} />}
                wrapperStyle={{ zIndex: 1000, outline: "none" }}
              />
              <Bar dataKey="total" radius={[0, 4, 4, 0]} barSize={isMobile ? 18 : 22}>
                {slice.map((entry, index) => (
                  <Cell key={entry.rotulo} fill={colors[index % colors.length]} />
                ))}
                {!isMobile && (
                  <LabelList
                    dataKey="total"
                    position="right"
                    formatter={fmtBarLabel}
                    style={{ fill: "var(--fx-text-secondary)", fontSize: 11, fontWeight: 600 }}
                  />
                )}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
      {isMobile && slice.length > 0 && (
        <p className="chart-panel-touch-hint">Toque na barra para ver o valor</p>
      )}
    </div>
  );
}
