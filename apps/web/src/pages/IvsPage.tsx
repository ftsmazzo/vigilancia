import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import TerritorialFilterSelects, { appendTerritorialParams } from "../components/TerritorialFilterSelects";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

type Props = {
  token: string;
};

type IndicadorPainel = {
  codigo: string;
  titulo: string;
  pct_familias: number | null;
};

type DimensaoPainel = {
  sigla: string;
  nome: string;
  idx: number | null;
  pct_acima_media: number | null;
  indicadores: IndicadorPainel[];
};

type IvsPainel = {
  recorte: { num_cras: string | null; num_creas: string | null; bairro: string | null };
  universo: {
    familias_elegiveis: number;
    familias_cadu: number;
    pct_sobre_cadu: number | null;
  };
  ivs_medio: number | null;
  dimensoes: DimensaoPainel[];
  dimensao_detalhe?: DimensaoPainel;
  versao_metodologica: string;
};

type DimSigla = "NC" | "DPI" | "DCA" | "TQA" | "DR" | "CH" | null;

const DIM_ORDEM: Array<Exclude<DimSigla, null>> = ["NC", "DPI", "DCA", "TQA", "DR", "CH"];

/** Índice 0–1 como no Observatório (ex.: 0,283). */
function fmtIndice(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  return v.toLocaleString("pt-BR", { minimumFractionDigits: 3, maximumFractionDigits: 3 });
}

function fmtPct(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  return `${v.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`;
}

function barWidthIndice(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "0%";
  return `${Math.min(100, Math.max(0, v * 100))}%`;
}

function barWidthPct(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "0%";
  return `${Math.min(100, Math.max(0, v))}%`;
}

export default function IvsPage({ token }: Props) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [painel, setPainel] = useState<IvsPainel | null>(null);
  const [crasCod, setCrasCod] = useState("__todos__");
  const [creasCod, setCreasCod] = useState("__todos__");
  const [bairroFiltro, setBairroFiltro] = useState("");
  const [dimAtiva, setDimAtiva] = useState<DimSigla>(null);

  const loadPainel = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams();
      appendTerritorialParams(params, crasCod, creasCod, bairroFiltro, { ivsMode: true });
      if (dimAtiva) params.set("dimensao", dimAtiva);
      const qs = params.toString();
      const response = await fetch(`${API_URL}/api/v1/vigilance/ivs/painel${qs ? `?${qs}` : ""}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = (await response.json().catch(() => ({}))) as IvsPainel & { detail?: unknown };
      if (!response.ok) {
        const msg =
          typeof data.detail === "string"
            ? data.detail
            : "IVS ainda não calculado. Gere as visões em Vigilância → IVS.";
        throw new Error(msg);
      }
      setPainel(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro inesperado.");
      setPainel(null);
    } finally {
      setLoading(false);
    }
  }, [token, crasCod, creasCod, bairroFiltro, dimAtiva]);

  useEffect(() => {
    void loadPainel();
  }, [loadPainel]);

  const dimDetalhe = useMemo(() => {
    if (!painel) return null;
    if (dimAtiva && painel.dimensao_detalhe?.sigla === dimAtiva) return painel.dimensao_detalhe;
    if (dimAtiva) return painel.dimensoes.find((d) => d.sigla === dimAtiva) ?? null;
    return null;
  }, [painel, dimAtiva]);

  const tituloRecorte = useMemo(() => {
    if (crasCod === "__todos__" && creasCod === "__todos__" && !bairroFiltro.trim()) return "Município";
    const parts: string[] = [];
    if (creasCod !== "__todos__") parts.push(creasCod === "__sem_creas__" ? "Sem CREAS" : `CREAS ${creasCod}`);
    if (crasCod !== "__todos__") parts.push(crasCod === "__sem_cras__" ? "Sem CRAS" : `CRAS ${crasCod}`);
    if (bairroFiltro.trim()) parts.push(bairroFiltro.trim().toLocaleUpperCase("pt-BR"));
    return parts.length > 0 ? parts.join(" · ") : "Município";
  }, [crasCod, creasCod, bairroFiltro]);

  return (
    <div className="ivs-page">
      <header className="ivs-hero fx-card">
        <div>
          <h1>IVS — Índice de Vulnerabilidade Social</h1>
          <p className="ivs-hero-sub">
            Metodologia IVCAD v1.0.5 (MDS IN084). Escala <strong>0 a 1</strong> — quanto maior, maior a
            vulnerabilidade. Layout alinhado ao Observatório MDS.
          </p>
        </div>
        <div className="ivs-hero-actions">
          <Link to="/vigilancia" className="btn btn-primary" style={{ textDecoration: "none" }}>
            Atualizar cálculo
          </Link>
          <button type="button" className="btn btn-secondary" onClick={() => void loadPainel()} disabled={loading}>
            {loading ? "Carregando…" : "Recarregar"}
          </button>
        </div>
      </header>

      <section className="ivs-filtros fx-card">
        <TerritorialFilterSelects
          token={token}
          crasCod={crasCod}
          creasCod={creasCod}
          bairroFiltro={bairroFiltro}
          onCrasChange={(v) => {
            setCrasCod(v);
            setBairroFiltro("");
          }}
          onCreasChange={(v) => {
            setCreasCod(v);
            setBairroFiltro("");
          }}
          onBairroChange={setBairroFiltro}
          className="ivs-filtros-grid"
        />
        <button
          type="button"
          className="btn btn-secondary"
          onClick={() => {
            setCrasCod("__todos__");
            setCreasCod("__todos__");
            setBairroFiltro("");
            setDimAtiva(null);
          }}
        >
          Limpar filtros
        </button>
        <p className="ivs-recorte-label">
          Exibindo: <strong>{tituloRecorte}</strong>
        </p>
      </section>

      {error && <p className="error">{error}</p>}

      {!error && painel && (
        <>
          <section className="ivs-universo fx-card" aria-label="Universo elegível">
            <div className="ivs-universo-item">
              <small>Famílias analisadas (universo IVS)</small>
              <strong>{painel.universo.familias_elegiveis.toLocaleString("pt-BR")}</strong>
            </div>
            <div className="ivs-universo-item">
              <small>Famílias no CADU (recorte)</small>
              <strong>{painel.universo.familias_cadu.toLocaleString("pt-BR")}</strong>
            </div>
            <div className="ivs-universo-item">
              <small>Participação no CADU</small>
              <strong>{fmtPct(painel.universo.pct_sobre_cadu)}</strong>
              <span>
                PBF (folha ou marcador CADU) ou TAC ≤ 24 meses com renda ≤ R$ 810,50
              </span>
            </div>
          </section>

          <nav className="ivs-dim-nav" aria-label="Dimensões do IVS">
            <button
              type="button"
              className={`ivs-dim-pill ${dimAtiva === null ? "active" : ""}`}
              onClick={() => setDimAtiva(null)}
            >
              Visão geral
            </button>
            {DIM_ORDEM.map((sigla) => (
              <button
                key={sigla}
                type="button"
                className={`ivs-dim-pill ${dimAtiva === sigla ? "active" : ""}`}
                onClick={() => setDimAtiva(sigla)}
              >
                {sigla}
              </button>
            ))}
          </nav>

          {dimAtiva === null ? (
            <section className="ivs-overview">
              <article className="ivs-dim-table fx-card">
                <div className="ivs-dim-table-head">
                  <div className="ivs-gauge-inline" aria-label={`IVS médio ${fmtIndice(painel.ivs_medio)}`}>
                    <small>IVS geral</small>
                    <strong className="ivs-gauge-value">{fmtIndice(painel.ivs_medio)}</strong>
                    <span>Média das 6 dimensões</span>
                  </div>
                  <div className="ivs-dim-table-intro">
                    <h2>Dimensões de vulnerabilidade</h2>
                    <p className="ivs-dim-table-sub">
                      Índice médio por dimensão (0–1) e % de famílias acima da média da dimensão no recorte.
                    </p>
                  </div>
                </div>
                <ul className="ivs-dim-list">
                  {painel.dimensoes.map((d) => (
                    <li key={d.sigla}>
                      <button type="button" className="ivs-dim-row" onClick={() => setDimAtiva(d.sigla as DimSigla)}>
                        <span className="ivs-dim-row-label">
                          <strong>{d.sigla}</strong>
                          <span>{d.nome}</span>
                        </span>
                        <span className="ivs-dim-row-bar-wrap">
                          <span className="ivs-dim-row-bar" style={{ width: barWidthIndice(d.idx) }} />
                        </span>
                        <span className="ivs-dim-row-idx">{fmtIndice(d.idx)}</span>
                        <span className="ivs-dim-row-pct">{fmtPct(d.pct_acima_media)} acima da média</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </article>
            </section>
          ) : (
            dimDetalhe && (
              <section className="ivs-dim-detalhe">
                <article className="ivs-dim-head fx-card">
                  <div>
                    <small>Dimensão {dimDetalhe.sigla}</small>
                    <h2>{dimDetalhe.nome}</h2>
                  </div>
                  <div className="ivs-dim-head-stats">
                    <div>
                      <small>Índice IVS-{dimDetalhe.sigla}</small>
                      <strong>{fmtIndice(dimDetalhe.idx)}</strong>
                    </div>
                    <div>
                      <small>Famílias acima da média</small>
                      <strong>{fmtPct(dimDetalhe.pct_acima_media)}</strong>
                    </div>
                  </div>
                  <div className="ivs-dim-head-bar">
                    <div className="ivs-dim-head-bar-fill" style={{ width: barWidthIndice(dimDetalhe.idx) }} />
                  </div>
                </article>

                <article className="ivs-indicadores fx-card">
                  <h3>Indicadores — % de famílias vulneráveis</h3>
                  <p className="ivs-indicadores-sub">
                    Proporção de famílias no universo elegível com cada condição de vulnerabilidade (= 1).
                  </p>
                  <ul className="ivs-ind-list">
                    {dimDetalhe.indicadores.map((ind) => (
                      <li key={ind.codigo} className="ivs-ind-row">
                        <span className="ivs-ind-code">{ind.codigo}</span>
                        <span className="ivs-ind-titulo">{ind.titulo}</span>
                        <span className="ivs-ind-bar-wrap">
                          <span className="ivs-ind-bar" style={{ width: barWidthPct(ind.pct_familias) }} />
                        </span>
                        <span className="ivs-ind-pct">{fmtPct(ind.pct_familias)}</span>
                      </li>
                    ))}
                  </ul>
                </article>
              </section>
            )
          )}
        </>
      )}
    </div>
  );
}
