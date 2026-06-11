import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import HeatmapTerritorialMap, { type HeatmapPayload } from "../components/HeatmapTerritorialMap";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

type Props = {
  token: string;
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
  totais: {
    criancas: number;
    idosos: number;
    pessoas: number;
    bairros: number;
  };
  recorte: { cras_cod: string | null; bairro: string | null };
};

const emptyMapa: MapasPainel = {
  disponivel: false,
  mensagem: "Carregando…",
  centro: [-21.1775, -47.8103],
  pontos: [],
  totais: { criancas: 0, idosos: 0, pessoas: 0, bairros: 0 },
  recorte: { cras_cod: null, bairro: null },
};

export default function MapasPage({ token }: Props) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [painel, setPainel] = useState<MapasPainel>(emptyMapa);
  const [catalog, setCatalog] = useState<CrasOption[]>([]);
  const [bairrosOptions, setBairrosOptions] = useState<BairroOption[]>([]);
  const [loadingBairros, setLoadingBairros] = useState(false);
  const [crasCod, setCrasCod] = useState("__todos__");
  const [bairroFiltro, setBairroFiltro] = useState("");

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
  }, [token]);

  useEffect(() => {
    setBairroFiltro("");
    if (!crasCod || crasCod === "__todos__" || crasCod === "__sem_cras__") {
      setBairrosOptions([]);
      return;
    }
    setLoadingBairros(true);
    fetch(`${API_URL}/api/v1/cras/bairros?num_cras=${encodeURIComponent(crasCod)}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(async (res) => {
        if (!res.ok) throw new Error();
        const data = (await res.json()) as { items: BairroOption[] };
        setBairrosOptions(data.items ?? []);
      })
      .catch(() => setBairrosOptions([]))
      .finally(() => setLoadingBairros(false));
  }, [token, crasCod]);

  const loadPainel = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams();
      if (crasCod && crasCod !== "__todos__") params.set("cras_cod", crasCod);
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
      setPainel(emptyMapa);
    } finally {
      setLoading(false);
    }
  }, [token, crasCod, bairroFiltro]);

  useEffect(() => {
    void loadPainel();
  }, [loadPainel]);

  const recorteLabel =
    painel.recorte.bairro != null
      ? painel.recorte.bairro
      : painel.recorte.cras_cod != null
        ? `CRAS ${painel.recorte.cras_cod}`
        : "Município inteiro";

  return (
    <div className="mapas-page">
      <header className="mapas-hero fx-card">
        <div>
          <h1>Mapas territoriais</h1>
          <p className="mapas-hero-sub">
            Mapas de calor por bairro — concentração de crianças (0–11 anos) e idosos (60 anos ou mais) no
            território georreferenciado.
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
            <span>CRAS</span>
            <select value={crasCod} onChange={(e) => setCrasCod(e.target.value)}>
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
            <span>Bairro</span>
            <select
              value={bairroFiltro}
              onChange={(e) => setBairroFiltro(e.target.value)}
              disabled={crasCod === "__todos__" || crasCod === "__sem_cras__" || loadingBairros}
            >
              <option value="">
                {crasCod === "__todos__" || crasCod === "__sem_cras__"
                  ? "Selecione um CRAS"
                  : loadingBairros
                    ? "Carregando…"
                    : "Todos os bairros do CRAS"}
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
          {!loading && painel.disponivel && (
            <>
              {" · "}
              {painel.totais.bairros.toLocaleString("pt-BR")} bairros ·{" "}
              {painel.totais.pessoas.toLocaleString("pt-BR")} pessoas
            </>
          )}
        </p>
      </section>

      {error && <p className="error-msg">{error}</p>}
      {loading && !painel.disponivel && !error && <p className="loading-msg">Carregando mapas…</p>}

      <div className="mapas-grid">
        <HeatmapTerritorialMap
          mapa={painel}
          metric="criancas"
          titulo="Crianças (0–11 anos)"
          subtitulo="Intensidade por bairro no recorte selecionado"
          totalMetrica={painel.totais.criancas}
        />
        <HeatmapTerritorialMap
          mapa={painel}
          metric="idosos"
          titulo="Idosos (60 anos ou mais)"
          subtitulo="Intensidade por bairro no recorte selecionado"
          totalMetrica={painel.totais.idosos}
        />
      </div>
    </div>
  );
}
