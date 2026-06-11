import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

export type MapaTerritorial = {
  disponivel: boolean;
  mensagem?: string;
  centro: [number, number];
  bounds?: [[number, number], [number, number]] | null;
  pontos: Array<{ lat: number; lng: number; num_cras: string; familias: number; cor: string }>;
  cras: Array<{
    num_cras: string;
    nom_cras: string;
    lat: number | null;
    lng: number | null;
    familias: number;
    cor: string;
  }>;
  familias_com_geo?: number;
  familias_sem_geo?: number;
};

type Props = {
  mapa: MapaTerritorial;
};

export default function HomeTerritorialMap({ mapa }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);

  useEffect(() => {
    if (!ref.current || !mapa.disponivel) return undefined;

    if (mapRef.current) {
      mapRef.current.remove();
      mapRef.current = null;
    }

    const map = L.map(ref.current, { scrollWheelZoom: true });
    mapRef.current = map;

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      maxZoom: 18,
    }).addTo(map);

    for (const c of mapa.cras) {
      if (c.lat == null || c.lng == null) continue;
      const radius = Math.min(5000, 900 + Math.sqrt(c.familias) * 40);
      L.circle([c.lat, c.lng], {
        radius,
        color: c.cor,
        fillColor: c.cor,
        fillOpacity: 0.14,
        weight: 2,
        opacity: 0.6,
      })
        .bindTooltip(
          `<strong>${c.nom_cras}</strong><br/>${c.familias.toLocaleString("pt-BR")} famílias`,
          { sticky: true },
        )
        .addTo(map);
    }

    for (const p of mapa.pontos) {
      const r = Math.min(9, 2.5 + Math.sqrt(p.familias) * 0.35);
      L.circleMarker([p.lat, p.lng], {
        radius: r,
        color: p.cor,
        fillColor: p.cor,
        fillOpacity: 0.7,
        weight: 1,
      }).addTo(map);
    }

    if (mapa.bounds && mapa.bounds.length === 2) {
      map.fitBounds(mapa.bounds as L.LatLngBoundsExpression, { padding: [20, 20] });
    } else {
      map.setView(mapa.centro as L.LatLngExpression, 12);
    }

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, [mapa]);

  if (!mapa.disponivel) {
    return (
      <div className="home-map home-map--empty fx-card">
        <p className="home-map-empty-msg">{mapa.mensagem}</p>
        {(mapa.familias_sem_geo ?? 0) > 0 && (
          <small className="home-map-empty-hint">
            {mapa.familias_sem_geo?.toLocaleString("pt-BR")} famílias ainda sem match CEP × geo.
          </small>
        )}
      </div>
    );
  }

  return (
    <div className="home-map-panel fx-card">
      <div className="home-map-head">
        <h2>Território por CRAS</h2>
        <small>
          {mapa.familias_com_geo?.toLocaleString("pt-BR")} famílias georreferenciadas · círculos = área
          aproximada do CRAS · pontos = agregação por CEP/coordenada
        </small>
      </div>
      <div ref={ref} className="home-map" aria-label="Mapa de Ribeirão Preto por CRAS" />
      <ul className="home-map-legend" aria-label="Legenda CRAS">
        {mapa.cras.map((c) => (
          <li key={c.num_cras}>
            <span className="home-map-swatch" style={{ background: c.cor }} aria-hidden />
            <span>{c.num_cras}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
