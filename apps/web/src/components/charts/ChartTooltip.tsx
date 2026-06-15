type Line = {
  label: string;
  value: string;
};

type Props = {
  title: string;
  lines: Line[];
};

export default function ChartTooltip({ title, lines }: Props) {
  return (
    <div className="fx-card chart-tooltip chart-tooltip--touch">
      <p className="chart-tooltip-title">{title}</p>
      {lines.map((line) => (
        <p key={line.label} className="chart-tooltip-line">
          {line.label}: <strong>{line.value}</strong>
        </p>
      ))}
    </div>
  );
}
