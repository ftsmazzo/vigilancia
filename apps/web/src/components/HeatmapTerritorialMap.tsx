import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "leaflet.heat";

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
  pessoas: number;
  criancas: number;
  idosos: number;
  adultos_sem_medio: number;
  na_folha_pbf: number;
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
  destacarRecorte?: boolean;
};

const HEAT_GRADIENT: Record<number, string> = {
  0.0: "rgba(255,255,255,0)",
  0.12: "rgba(255,237,160,0.35)",
  0.35: "rgba(254,178,76,0.55)",
  0.58: "rgba(253,141,60,0.72)",
  0.78: "rgba(240,59,32,0.85)",
  1.0: "rgba(189,0,38,0.95)",
};

function metricValue(p: HeatmapPonto, metric: HeatmapMetric): number {
  if (metric === "familias_pbf") return p.na_folha_pbf;
  return p[metric];
}

/** Envoltória convexa (monotone chain) para contorno orgânico do recorte. */
function convexHullLatLng(points: Array<{ lat: number; lng: number }>): [number, number][] {
  if (points.length < 3) {
    return points.map((p) => [p.lat, p.lng]);
  }

  const sorted = [...points].sort((a, b) => (a.lng === b.lng ? a.lat - b.lat : a.lng - b.lng));

  const cross = (o: { lat: number; lng: number }, a: { lat: number; lng: number }, b: { lat: number; lng: number }) =>
    (a.lng - o.lng) * (b.lat - o.lat) - (a.lat - o.lat) * (b.lng - o.lng);

  const lower: typeof sorted = [];
  for (const p of sorted) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) {
      lower.pop();
    }
    lower.push(p);
  }

  const upper: typeof sorted = [];
  for (let i = sorted.length - 1; i >= 0; i -= 1) {
    const p = sorted[i];
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) {
      upper.pop();
    }
    upper.push(p);
  }

  upper.pop();
  lower.pop();
  return [...lower, ...upper].map((p) => [p.lat, p.lng]);
}

function heatIntensity(weight: number, maxWeight: number): number {
  if (weight <= 0 || maxWeight <= 0) return 0;
  return Math.pow(weight / maxWeight, 0.65);
}

export default function HeatmapTerritorialMap({
  mapa,
  metric,
  titulo,
  subtitulo,
  totalGeo,
  totalCadu,
  unidadeLabel,
  destacarRecorte = false,
}: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);

  useEffect(() => {
    if (!ref.current || !mapa.disponivel) return undefined;

    if (mapRef.current) {
      mapRef.current.remove();
      mapRef.current = null;
    }

    const weights = mapa.pontos.map((p) => metricValue(p, metric)).filter((w) => w > 0);
    const maxWeight = Math.max(1, ...weights);

    const heatPoints: Array<[number, number, number]> = mapa.pontos
      .map((p) => {
        const w = metricValue(p, metric);
        if (w <= 0) return null;
        return [p.lat, p.lng, heatIntensity(w, maxWeight)] as [number, number, number];
      })
      .filter((p): p is [number, number, number] => p !== null);

    const map = L.map(ref.current, { scrollWheelZoom: true });
    mapRef.current = map;

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      maxZoom: 18,
    }).addTo(map);

    if (destacarRecorte && mapa.pontos.length >= 3) {
      const hull = convexHullLatLng(mapa.pontos);
      if (hull.length >= 3) {
        L.polygon(hull, {
          color: "rgba(240, 160, 96, 0.55)",
          weight: 1.5,
          fillColor: "rgba(240, 160, 96, 0.08)",
          fillOpacity: 1,
          dashArray: "6 8",
        }).addTo(map);
      }
    }

    if (heatPoints.length > 0) {
      L.heatLayer(heatPoints, {
        radius: 28,
        blur: 22,
        maxZoom: 17,
        max: 1,
        minOpacity: 0.28,
        gradient: HEAT_GRADIENT,
      }).addTo(map);
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
  }, [mapa, metric, destacarRecorte]);

  const diff = totalCadu - totalGeo;
  const cobertura = totalCadu > 0 ? Math.round((1000 * totalGeo) / totalCadu) / 10 : 100;

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
