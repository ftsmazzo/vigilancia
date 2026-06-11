import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

export type HeatmapPonto = {
  bairro: string;
  num_cras: string;
  lat: number;
  lng: number;
  pessoas: number;
  criancas: number;
  idosos: number;
};

export type HeatmapPayload = {
  disponivel: boolean;
  mensagem?: string;
  centro: [number, number];
  bounds?: [[number, number], [number, number]] | null;
  pontos: HeatmapPonto[];
};

type Metric = "criancas" | "idosos";

type Props = {
  mapa: HeatmapPayload;
  metric: Metric;
  titulo: string;
  subtitulo: string;
  totalMetrica: number;
};

function metricValue(p: HeatmapPonto, metric: Metric): number {
  return metric === "criancas" ? p.criancas : p.idosos;
}

/** Azul (baixo) → amarelo → vermelho (alto). */
function heatColor(ratio: number): string {
  const t = Math.min(1, Math.max(0, ratio));
  const hue = 220 - t * 220;
  const light = 38 + t * 12;
  return `hsl(${hue}, 82%, ${light}%)`;
}

export default function HeatmapTerritorialMap({
  mapa,
  metric,
  titulo,
  subtitulo,
  totalMetrica,
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
      const color = heatColor(ratio);
      const glowRadius = 350 + Math.sqrt(ratio) * 2200;
      const markerR = 5 + Math.sqrt(ratio) * 14;

      L.circle([p.lat, p.lng], {
        radius: glowRadius,
        color,
        fillColor: color,
        fillOpacity: 0.12 + ratio * 0.22,
        weight: 0,
      }).addTo(map);

      L.circleMarker([p.lat, p.lng], {
        radius: markerR,
        color: color,
        fillColor: color,
        fillOpacity: 0.75,
        weight: 1,
        opacity: 0.9,
      })
        .bindTooltip(
          `<strong>${p.bairro}</strong><br/>` +
            `${val.toLocaleString("pt-BR")} ${metric === "criancas" ? "crianças (0–11)" : "idosos (60+)"}<br/>` +
            `${p.pessoas.toLocaleString("pt-BR")} pessoas no bairro` +
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
        <strong className="mapas-heatmap-total">{totalMetrica.toLocaleString("pt-BR")}</strong>
      </header>
      <div ref={ref} className="mapas-heatmap-canvas" aria-label={titulo} />
      <div className="mapas-heatmap-legend" aria-hidden>
        <span>Menor</span>
        <span className="mapas-heatmap-legend-bar" />
        <span>Maior</span>
      </div>
    </article>
  );
}
