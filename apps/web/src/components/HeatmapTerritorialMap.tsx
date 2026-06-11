import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

export type HeatmapMetric =
  | "criancas"
  | "idosos"
  | "familias_pbf"
  | "adultos_sem_medio";

export type HeatmapPonto = {
  bairro: string;
  num_cras: string;
  lat: number;
  lng: number;
  familias: number;
  pessoas: number;
  criancas: number;
  idosos: number;
  familias_pbf: number;
  adultos_sem_medio: number;
};

export type HeatmapTotais = {
  criancas: number;
  idosos: number;
  familias_pbf: number;
  adultos_sem_medio: number;
  pessoas: number;
  familias: number;
  bairros?: number;
};

export type HeatmapPayload = {
  disponivel: boolean;
  mensagem?: string;
  centro: [number, number];
  bounds?: [[number, number], [number, number]] | null;
  pontos: HeatmapPonto[];
  totais_geo?: HeatmapTotais;
  totais_cadu?: HeatmapTotais;
};

type Props = {
  mapa: HeatmapPayload;
  metric: HeatmapMetric;
  titulo: string;
  subtitulo: string;
  totalGeo: number;
  totalCadu: number;
  unidadeLabel: string;
};

const METRIC_TOOLTIP: Record<HeatmapMetric, string> = {
  criancas: "crianças (0–11 anos)",
  idosos: "idosos (60 anos ou mais)",
  familias_pbf: "famílias na folha PBF",
  adultos_sem_medio: "pessoas 18–59 sem ensino médio completo",
};

function metricValue(p: HeatmapPonto, metric: HeatmapMetric): number {
  return p[metric];
}

/** Transparente (baixo) → amarelo → laranja → vermelho (alto). */
function heatStyle(ratio: number): { color: string; fillOpacity: number; radius: number } {
  const t = Math.min(1, Math.max(0, ratio));

  if (t <= 0) {
    return { color: "#e63900", fillOpacity: 0, radius: 0 };
  }

  const hue = 48 - t * 48;
  const sat = 78 + t * 18;
  const light = 58 - t * 22;
  const fillOpacity = 0.06 + Math.pow(t, 0.72) * 0.52;
  const radius = 280 + Math.pow(t, 0.55) * 3200;

  return {
    color: `hsl(${hue}, ${sat}%, ${light}%)`,
    fillOpacity,
    radius,
  };
}

export default function HeatmapTerritorialMap({
  mapa,
  metric,
  titulo,
  subtitulo,
  totalGeo,
  totalCadu,
  unidadeLabel,
}: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);

  useEffect(() => {
    if (!ref.current || !mapa.disponivel) return undefined;

    if (mapRef.current) {
      mapRef.current.remove();
      mapRef.current = null;
    }

    const valores = mapa.pontos.map((p) => metricValue(p, metric));
    const maxVal = Math.max(1, ...valores);

    const map = L.map(ref.current, { scrollWheelZoom: true });
    mapRef.current = map;

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      maxZoom: 18,
    }).addTo(map);

    for (const p of mapa.pontos) {
      const val = metricValue(p, metric);
      if (val <= 0) continue;

      const ratio = val / maxVal;
      const style = heatStyle(ratio);
      if (style.radius <= 0) continue;

      L.circle([p.lat, p.lng], {
        radius: style.radius,
        color: style.color,
        fillColor: style.color,
        fillOpacity: style.fillOpacity,
        weight: 0,
        opacity: 0,
      })
        .bindTooltip(
          `<strong>${p.bairro}</strong><br/>` +
            `${val.toLocaleString("pt-BR")} ${METRIC_TOOLTIP[metric]}<br/>` +
            `${p.pessoas.toLocaleString("pt-BR")} pessoas · ` +
            `${p.familias.toLocaleString("pt-BR")} famílias` +
            (p.num_cras ? `<br/>CRAS ${p.num_cras}` : ""),
          { sticky: true },
        )
        .addTo(map);
    }

    if (mapa.bounds && mapa.bounds.length === 2) {
      map.fitBounds(mapa.bounds as L.LatLngBoundsExpression, { padding: [24, 24] });
    } else {
      map.setView(mapa.centro as L.LatLngExpression, 12);
    }

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, [mapa, metric]);

  const diff = totalCadu - totalGeo;
  const cobertura =
    totalCadu > 0 ? Math.round((1000 * totalGeo) / totalCadu) / 10 : 100;

  if (!mapa.disponivel) {
    return (
      <article className="mapas-heatmap fx-card">
        <header className="mapas-heatmap-head">
          <h2>{titulo}</h2>
          <p>{subtitulo}</p>
        </header>
        <div className="mapas-heatmap mapas-heatmap--empty">
          <p>{mapa.mensagem}</p>
        </div>
      </article>
    );
  }

  return (
    <article className="mapas-heatmap fx-card">
      <header className="mapas-heatmap-head">
        <div>
          <h2>{titulo}</h2>
          <p>{subtitulo}</p>
        </div>
        <div className="mapas-heatmap-totals">
          <strong className="mapas-heatmap-total">{totalGeo.toLocaleString("pt-BR")}</strong>
          <span className="mapas-heatmap-ref">
            de {totalCadu.toLocaleString("pt-BR")} {unidadeLabel} no CADU
          </span>
          {diff > 0 && (
            <span className="mapas-heatmap-cobertura">
              {cobertura}% georreferenciado · {diff.toLocaleString("pt-BR")} fora do mapa
            </span>
          )}
        </div>
      </header>
      <div ref={ref} className="mapas-heatmap-canvas" aria-label={titulo} />
      <div className="mapas-heatmap-legend" aria-hidden>
        <span>Baixa</span>
        <span className="mapas-heatmap-legend-bar" />
        <span>Alta</span>
      </div>
    </article>
  );
}
