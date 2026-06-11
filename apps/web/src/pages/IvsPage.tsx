import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import BarChartPanel, { type BarItem } from "../components/charts/BarChartPanel";
import RadarChartPanel from "../components/charts/RadarChartPanel";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

type Props = {
  token: string;
};

type IvsResumo = {
  familias_elegiveis: number;
  familias_total: number;
  ivs_medio: number | null;
  idx_nc: number | null;
  idx_dpi: number | null;
  idx_dca: number | null;
  idx_tqa: number | null;
  idx_dr: number | null;
  idx_ch: number | null;
  num_cras?: string;
  bairro?: string;
};

type IvsCrasItem = {
  num_cras: string;
  nom_cras: string;
  familias_elegiveis: number;
  ivs_medio: number | null;
  idx_nc: number | null;
  idx_dpi: number | null;
  idx_dca: number | null;
  idx_tqa: number | null;
  idx_dr: number | null;
  idx_ch: number | null;
};

const DIM_LABELS: Record<string, string> = {
  idx_nc: "NC — Necessidade de Cuidados",
  idx_dpi: "DPI — Primeira Infância",
  idx_dca: "DCA — Crianças e Adolescentes",
  idx_tqa: "TQA — Trabalho e Qualificação",
  idx_dr: "DR — Disponibilidade de Recursos",
  idx_ch: "CH — Condições Habitacionais",
};

function pct01(v: number | null | undefined): number {
  if (v == null || Number.isNaN(v)) return 0;
  return Math.round(v * 10000) / 100;
}

function crasRotulo(item: IvsCrasItem): string {
  const num = (item.num_cras || "").trim();
  const nome = (item.nom_cras || "").trim();
  if (num && nome) return `${num} — ${nome}`;
  return nome || num || "Sem referência";
}

export default function IvsPage({ token }: Props) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [resumo, setResumo] = useState<IvsResumo | null>(null);
  const [porCras, setPorCras] = useState<IvsCrasItem[]>([]);
  const [crasFiltro, setCrasFiltro] = useState("");
  const [bairroFiltro, setBairroFiltro] = useState("");

  const loadPorCras = useCallback(async () => {
    const response = await fetch(`${API_URL}/api/v1/vigilance/ivs/por-cras`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const data = (await response.json().catch(() => ({}))) as {
      items?: IvsCrasItem[];
      detail?: unknown;
    };
    if (!response.ok) return;
    setPorCras(data.items ?? []);
  }, [token]);

  const loadResumo = useCallback(
    async (cras?: string, bairro?: string) => {
      setLoading(true);
      setError("");
      try {
        const params = new URLSearchParams();
        if (cras) params.set("num_cras", cras);
        if (bairro?.trim()) params.set("bairro", bairro.trim());
        const qs = params.toString();
        const response = await fetch(
          `${API_URL}/api/v1/vigilance/ivs/resumo${qs ? `?${qs}` : ""}`,
          { headers: { Authorization: `Bearer ${token}` } },
        );
        const data = (await response.json().catch(() => ({}))) as IvsResumo & { detail?: unknown };
        if (!response.ok) {
          const msg =
            typeof data.detail === "string"
              ? data.detail
              : "Falha ao carregar resumo IVS.";
          throw new Error(msg);
        }
        setResumo(data);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Erro inesperado.");
        setResumo(null);
      } finally {
        setLoading(false);
      }
    },
    [token],
  );

  useEffect(() => {
    void loadResumo();
    void loadPorCras();
  }, [loadResumo, loadPorCras]);

  const radarData = useMemo(() => {
    if (!resumo) return [];
    return [
      { name: "NC", ivs: pct01(resumo.idx_nc) },
      { name: "DPI", ivs: pct01(resumo.idx_dpi) },
      { name: "DCA", ivs: pct01(resumo.idx_dca) },
      { name: "TQA", ivs: pct01(resumo.idx_tqa) },
      { name: "DR", ivs: pct01(resumo.idx_dr) },
      { name: "CH", ivs: pct01(resumo.idx_ch) },
    ];
  }, [resumo]);

  const barrasCras: BarItem[] = useMemo(
    () =>
      porCras
        .filter((c) => (c.familias_elegiveis ?? 0) > 0)
        .map((c) => ({
          rotulo: crasRotulo(c),
          total: c.familias_elegiveis,
          pct: pct01(c.ivs_medio),
        }))
        .sort((a, b) => b.pct - a.pct),
    [porCras],
  );

  const pctElegivel =
    resumo && resumo.familias_total
      ? Math.round((resumo.familias_elegiveis / resumo.familias_total) * 10000) / 100
      : 0;

  return (
    <div className="kpi-page">
      <div className="kpi-head fx-card">
        <h1>IVS — Índice de Vulnerabilidade Social</h1>
        <p>
          Metodologia IVCAD v1.0.5 (MDS IN084). Grain família; escala 0–1 (maior = mais vulnerável).
          Fonte: <code className="inline-code">core.mvw_ivs_familia</code>.
        </p>
        <div className="vig-actions" style={{ flexWrap: "wrap", gap: "0.5rem", marginTop: "0.75rem" }}>
          <Link to="/vigilancia" className="btn btn-primary" style={{ textDecoration: "none" }}>
            Calcular / atualizar IVS
          </Link>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => void loadResumo(crasFiltro || undefined, bairroFiltro)}
            disabled={loading}
          >
            {loading ? "Carregando…" : "Atualizar painel"}
          </button>
        </div>
      </div>

      <div className="fx-card" style={{ padding: "1rem", marginBottom: "1rem" }}>
        <h2 className="kpi-section-title" style={{ marginTop: 0 }}>
          Recorte territorial
        </h2>
        <div className="vig-actions" style={{ flexWrap: "wrap", gap: "0.75rem", alignItems: "flex-end" }}>
          <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem", minWidth: "220px" }}>
            <span style={{ fontSize: "0.85rem", color: "var(--fx-muted)" }}>CRAS de referência</span>
            <select
              value={crasFiltro}
              onChange={(e) => setCrasFiltro(e.target.value)}
              style={{ padding: "0.45rem 0.6rem", borderRadius: "8px" }}
            >
              <option value="">Município (todas)</option>
              {porCras.map((c) => (
                <option key={`${c.num_cras}-${c.nom_cras}`} value={c.num_cras || ""}>
                  {crasRotulo(c)}
                </option>
              ))}
            </select>
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem", minWidth: "200px" }}>
            <span style={{ fontSize: "0.85rem", color: "var(--fx-muted)" }}>Bairro (parcial)</span>
            <input
              type="text"
              value={bairroFiltro}
              onChange={(e) => setBairroFiltro(e.target.value)}
              placeholder="Ex.: Centro"
              style={{ padding: "0.45rem 0.6rem", borderRadius: "8px" }}
            />
          </label>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => void loadResumo(crasFiltro || undefined, bairroFiltro)}
            disabled={loading}
          >
            Aplicar filtro
          </button>
          {(crasFiltro || bairroFiltro.trim()) && (
            <button
              type="button"
              className="link-button"
              onClick={() => {
                setCrasFiltro("");
                setBairroFiltro("");
                void loadResumo();
              }}
            >
              Limpar filtros
            </button>
          )}
        </div>
      </div>

      {error && <p className="error">{error}</p>}

      {!error && resumo && (
        <>
          <div className="kpi-grid" aria-label="Resumo IVS">
            <article className="kpi-card kpi-card--accent">
              <small>IVS médio</small>
              <strong>{pct01(resumo.ivs_medio).toLocaleString("pt-BR")}%</strong>
              <span>Universo elegível (IN084 v1.0.5)</span>
            </article>
            <article className="kpi-card">
              <small>Famílias elegíveis</small>
              <strong>{resumo.familias_elegiveis.toLocaleString("pt-BR")}</strong>
              <span>
                {pctElegivel.toLocaleString("pt-BR")}% sobre {resumo.familias_total.toLocaleString("pt-BR")} no CADU
              </span>
            </article>
            {(Object.keys(DIM_LABELS) as Array<keyof typeof DIM_LABELS>).map((key) => (
              <article key={key} className="kpi-card">
                <small>{DIM_LABELS[key].split(" — ")[0]}</small>
                <strong>{pct01(resumo[key] as number | null).toLocaleString("pt-BR")}%</strong>
                <span>{DIM_LABELS[key].split(" — ")[1] ?? key}</span>
              </article>
            ))}
          </div>

          <div className="chart-grid" style={{ display: "grid", gap: "1rem", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))" }}>
            <RadarChartPanel
              title="Dimensões do IVS"
              subtitle="Médias no recorte (0–100%, maior = mais vulnerável)"
              data={radarData}
              dataKey="ivs"
              fill="rgba(245, 158, 11, 0.35)"
              stroke="#f59e0b"
            />
            <BarChartPanel
              title="IVS médio por CRAS"
              subtitle="Famílias elegíveis; barra = índice médio (%)"
              items={barrasCras}
              maxBars={14}
              accent="warm"
            />
          </div>
        </>
      )}
    </div>
  );
}
