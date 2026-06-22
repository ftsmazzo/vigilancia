import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import HeatmapTerritorialMap, {
  type HeatmapPayload,
  type HeatmapTotais,
} from "../components/HeatmapTerritorialMap";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";
const FILTER_DEBOUNCE_MS = 350;

type Props = {
  token: string;
};

type CreasOption = {
  creas_cod: string;
  creas_nome: string;
  rotulo_ordenado?: string;
};

type CrasOption = {
  cras_cod: string;
  cras_nome: string;
  rotulo_ordenado?: string;
};

type BairroOption = {
  bairro: string;
  familias: number;
};

type MapasPainel = HeatmapPayload & {
  totais_geo: HeatmapTotais;
  totais_cadu: HeatmapTotais;
  recorte: { cras_cod: string | null; creas_cod: string | null; bairro: string | null };
};

const emptyTotais: HeatmapTotais = {
  criancas: 0,
  idosos: 0,
  familias_pbf: 0,
  adultos_sem_medio: 0,
  pessoas: 0,
  familias: 0,
  bairros: 0,
};

const emptyMapa: MapasPainel = {
  disponivel: false,
  mensagem: "Carregando…",
  centro: [-21.1775, -47.8103],
  pontos: [],
  totais_geo: emptyTotais,
  totais_cadu: emptyTotais,
  recorte: { cras_cod: null, creas_cod: null, bairro: null },
};

export default function MapasPage({ token }: Props) {
  const [initialLoading, setInitialLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [painel, setPainel] = useState<MapasPainel>(emptyMapa);
  const [catalog, setCatalog] = useState<CrasOption[]>([]);
  const [creasCatalog, setCreasCatalog] = useState<CreasOption[]>([]);
  const [bairrosOptions, setBairrosOptions] = useState<BairroOption[]>([]);
  const [loadingBairros, setLoadingBairros] = useState(true);
  const [crasCod, setCrasCod] = useState("__todos__");
  const [creasCod, setCreasCod] = useState("__todos__");
  const [bairroFiltro, setBairroFiltro] = useState("");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    fetch(`${API_URL}/api/v1/cras/catalog`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(async (res) => {
        if (!res.ok) return;
        const data = (await res.json()) as { items: CrasOption[] };
        setCatalog(data.items ?? []);
      })
      .catch(() => setCatalog([]));

    fetch(`${API_URL}/api/v1/creas/catalog`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(async (res) => {
        if (!res.ok) return;
        const data = (await res.json()) as { items: CreasOption[] };
        setCreasCatalog(data.items ?? []);
      })
      .catch(() => setCreasCatalog([]));
  }, [token]);

  useEffect(() => {
    setLoadingBairros(true);
    fetch(`${API_URL}/api/v1/vigilance/mapas-bairros`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(async (res) => {
        if (!res.ok) throw new Error();
        const data = (await res.json()) as { items: BairroOption[] };
        setBairrosOptions(data.items ?? []);
      })
      .catch(() => setBairrosOptions([]))
      .finally(() => setLoadingBairros(false));
  }, [token]);

  const loadPainel = useCallback(async () => {
    setRefreshing(true);
    setError("");
    try {
      const params = new URLSearchParams();
      if (crasCod && crasCod !== "__todos__") params.set("cras_cod", crasCod);
      if (creasCod && creasCod !== "__todos__") params.set("creas_cod", creasCod);
      if (bairroFiltro.trim()) params.set("bairro", bairroFiltro.trim());
      const qs = params.toString();
      const response = await fetch(`${API_URL}/api/v1/vigilance/mapas-heatmap${qs ? `?${qs}` : ""}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = (await response.json().catch(() => ({}))) as MapasPainel & { detail?: unknown };
      if (!response.ok) {
        throw new Error(typeof data.detail === "string" ? data.detail : "Falha ao carregar mapas.");
      }
      setPainel(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao carregar mapas.");
      if (initialLoading) setPainel(emptyMapa);
    } finally {
      setRefreshing(false);
      setInitialLoading(false);
    }
  }, [token, crasCod, creasCod, bairroFiltro, initialLoading]);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      void loadPainel();
    }, FILTER_DEBOUNCE_MS);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [loadPainel]);

  const recorteParts: string[] = [];
  if (painel.recorte.bairro) recorteParts.push(painel.recorte.bairro);
  if (painel.recorte.creas_cod) recorteParts.push(`CREAS ${painel.recorte.creas_cod}`);
  if (painel.recorte.cras_cod) recorteParts.push(`CRAS ${painel.recorte.cras_cod}`);
  const recorteLabel = recorteParts.length > 0 ? recorteParts.join(" · ") : "Município inteiro";

  const geo = painel.totais_geo ?? emptyTotais;
  const cadu = painel.totais_cadu ?? emptyTotais;
  const destacarRecorte =
    (crasCod !== "__todos__" && crasCod !== "") ||
    (creasCod !== "__todos__" && creasCod !== "") ||
    bairroFiltro.trim().length > 0;

  function handleCrasChange(value: string) {
    setCrasCod(value);
    if (value !== "__todos__") {
      setBairroFiltro("");
    }
  }

  function handleCreasChange(value: string) {
    setCreasCod(value);
    if (value !== "__todos__") {
      setBairroFiltro("");
    }
  }

  function handleBairroChange(value: string) {
    setBairroFiltro(value);
    if (value.trim()) {
      setCrasCod("__todos__");
    }
  }

  return (
    <div className="mapas-page">
      <header className="mapas-hero fx-card">
        <div>
          <h1>Mapas territoriais</h1>
          <p className="mapas-hero-sub">
            Filtros de CRAS, CREAS e bairro — bairro municipal ou recorte por unidade territorial.
          </p>
        </div>
        <div className="mapas-hero-actions">
          <Link to="/caracterizacao" className="btn btn-secondary" style={{ textDecoration: "none" }}>
            Caracterização
          </Link>
        </div>
      </header>

      <section className="mapas-filtros fx-card">
        <div className="mapas-filtros-grid">
          <label>
            <span>CRAS territorial</span>
            <select className="cras-select" value={crasCod} onChange={(e) => handleCrasChange(e.target.value)}>
              <option value="__todos__">Todos os CRAS</option>
              <option value="__sem_cras__">Sem referência territorial</option>
              {catalog.map((c) => (
                <option key={c.cras_cod} value={c.cras_cod}>
                  {c.rotulo_ordenado ?? c.cras_nome}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>CREAS territorial</span>
            <select className="cras-select" value={creasCod} onChange={(e) => handleCreasChange(e.target.value)}>
              <option value="__todos__">Todos os CREAS</option>
              <option value="__sem_creas__">Sem referência CREAS</option>
              {creasCatalog.map((c) => (
                <option key={c.creas_cod} value={c.creas_cod}>
                  {c.rotulo_ordenado ?? c.creas_nome}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Bairro</span>
            <select
              className="cras-select"
              value={bairroFiltro}
              onChange={(e) => handleBairroChange(e.target.value)}
              disabled={loadingBairros}
            >
              <option value="">
                {loadingBairros ? "Carregando bairros…" : "Todos os bairros"}
              </option>
              {bairrosOptions.map((b) => (
                <option key={b.bairro} value={b.bairro}>
                  {b.bairro} ({b.familias.toLocaleString("pt-BR")} fam.)
                </option>
              ))}
            </select>
          </label>
        </div>
        <p className="mapas-recorte-label">
          Recorte: <strong>{recorteLabel}</strong>
          {refreshing && <span className="mapas-refresh-hint"> · Atualizando…</span>}
          {!initialLoading && painel.disponivel && !refreshing && (
            <>
              {" · "}
              {(geo.bairros ?? 0).toLocaleString("pt-BR")} bairros ·{" "}
              {geo.pessoas.toLocaleString("pt-BR")} pessoas no mapa
            </>
          )}
        </p>
      </section>

      {error && <p className="error-msg">{error}</p>}
      {initialLoading && !painel.disponivel && !error && (
        <p className="loading-msg">Carregando mapas…</p>
      )}

      {!initialLoading && (
        <div className={`mapas-grid${refreshing ? " mapas-grid--refreshing" : ""}`}>
          <HeatmapTerritorialMap
            mapa={painel}
            metric="criancas"
            titulo="Crianças (0–11 anos)"
            subtitulo="Densidade por coordenada familiar (0–11 anos)"
            totalGeo={geo.criancas}
            totalCadu={cadu.criancas}
            unidadeLabel="crianças"
            destacarRecorte={destacarRecorte}
          />
          <HeatmapTerritorialMap
            mapa={painel}
            metric="idosos"
            titulo="Idosos (60 anos ou mais)"
            subtitulo="Densidade por coordenada familiar (60+ anos)"
            totalGeo={geo.idosos}
            totalCadu={cadu.idosos}
            unidadeLabel="idosos"
            destacarRecorte={destacarRecorte}
          />
          <HeatmapTerritorialMap
            mapa={painel}
            metric="familias_pbf"
            titulo="Famílias com Bolsa Família"
            subtitulo="Famílias na folha PBF (marc_pbf) por coordenada"
            totalGeo={geo.familias_pbf}
            totalCadu={cadu.familias_pbf}
            unidadeLabel="famílias PBF"
            destacarRecorte={destacarRecorte}
          />
          <HeatmapTerritorialMap
            mapa={painel}
            metric="adultos_sem_medio"
            titulo="18–59 anos sem ensino médio completo"
            subtitulo="Pessoas adultas sem grau 5 ou superior no CADU"
            totalGeo={geo.adultos_sem_medio}
            totalCadu={cadu.adultos_sem_medio}
            unidadeLabel="pessoas"
            destacarRecorte={destacarRecorte}
          />
        </div>
      )}
    </div>
  );
}
