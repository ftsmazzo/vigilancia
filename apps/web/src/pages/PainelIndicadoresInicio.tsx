import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import HomeTerritorialMap, { type MapaTerritorial } from "../components/HomeTerritorialMap";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

type Props = {
  token: string;
};

type FaixaItem = {
  rotulo: string;
  titulo: string;
  total: number;
  pct: number;
};

type BairroRankItem = {
  posicao: number;
  bairro: string;
  familias: number;
  pct_do_total: number;
};

type HomePainel = {
  total_familias: number;
  total_pessoas: number;
  familias_pbf: number;
  pessoas_pbf: number;
  ivs_medio: number | null;
  ivs_disponivel: boolean;
  ivs_media_nacional: number;
  por_meses_atualizacao: FaixaItem[];
  por_faixa_renda: FaixaItem[];
  top_bairros: BairroRankItem[];
  mapa: MapaTerritorial;
};

function fmtIndice(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  return v.toLocaleString("pt-BR", { minimumFractionDigits: 3, maximumFractionDigits: 3 });
}

function barPct(pct: number, maxPct: number): string {
  if (!maxPct) return "0%";
  return `${Math.min(100, (pct / maxPct) * 100)}%`;
}

/** Página Início — layout Observatório MDS + mapa territorial por CRAS. */
export default function PainelIndicadoresInicio({ token }: Props) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [painel, setPainel] = useState<HomePainel | null>(null);

  async function loadPainel() {
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_URL}/api/v1/vigilance/home-painel`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = (await response.json().catch(() => ({}))) as HomePainel & { detail?: unknown };
      if (!response.ok) {
        throw new Error(typeof data.detail === "string" ? data.detail : "Falha ao carregar painel inicial.");
      }
      setPainel(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro inesperado.");
      setPainel(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadPainel();
  }, [token]);

  const maxMesesPct = Math.max(...(painel?.por_meses_atualizacao.map((x) => x.pct) ?? [1]), 1);
  const maxRendaPct = Math.max(...(painel?.por_faixa_renda.map((x) => x.pct) ?? [1]), 1);
  const maxBairroPct = Math.max(...(painel?.top_bairros.map((x) => x.pct_do_total) ?? [1]), 1);

  const ivsVal = painel?.ivs_medio ?? null;
  const ivsPctGauge = ivsVal != null ? Math.min(100, ivsVal * 100) : 0;
  const mediaNac = painel?.ivs_media_nacional ?? 0.283;
  const mediaNacPct = Math.min(100, mediaNac * 100);

  return (
    <div className="home-obs-page">
      <header className="home-obs-head fx-card">
        <div>
          <h1>Observatório Social — Ribeirão Preto</h1>
          <p>Cadastro Único, Bolsa Família e territorialização por CRAS (geo × CEP).</p>
        </div>
        <div className="home-obs-actions">
          <button type="button" className="btn btn-secondary" onClick={() => void loadPainel()} disabled={loading}>
            {loading ? "Atualizando…" : "Atualizar"}
          </button>
          <Link to="/ivs" className="btn btn-primary" style={{ textDecoration: "none" }}>
            Painel IVS
          </Link>
          <Link to="/observatorio" className="btn btn-secondary" style={{ textDecoration: "none" }}>
            Observatório CADU
          </Link>
        </div>
      </header>

      {error && <p className="error">{error}</p>}

      {!error && painel && (
        <>
          <section className="home-obs-kpis" aria-label="Indicadores principais">
            <article className="home-obs-kpi fx-card">
              <small>Famílias</small>
              <strong>{painel.total_familias.toLocaleString("pt-BR")}</strong>
            </article>
            <article className="home-obs-kpi fx-card">
              <small>Pessoas</small>
              <strong>{painel.total_pessoas.toLocaleString("pt-BR")}</strong>
            </article>
            <article className="home-obs-kpi fx-card">
              <small>Famílias com PBF</small>
              <strong>{painel.familias_pbf.toLocaleString("pt-BR")}</strong>
            </article>
            <article className="home-obs-kpi fx-card">
              <small>Pessoas com PBF</small>
              <strong>{painel.pessoas_pbf.toLocaleString("pt-BR")}</strong>
            </article>
          </section>

          <section className="home-obs-main">
            <div className="home-obs-left">
              <HomeTerritorialMap mapa={painel.mapa} />

              <article className="home-obs-ivcad fx-card">
                <h2>IVCAD — Índice de Vulnerabilidade das Famílias do Cadastro Único</h2>
                <p className="home-obs-ivcad-desc">
                  Metodologia v1.0.5 (MDS): 40 indicadores em 6 dimensões. Escala 0 a 1 — quanto maior, maior a
                  vulnerabilidade.
                </p>
                {painel.ivs_disponivel && ivsVal != null ? (
                  <div className="home-obs-gauge-wrap">
                    <div className="home-obs-gauge" role="img" aria-label={`IVS médio ${fmtIndice(ivsVal)}`}>
                      <div className="home-obs-gauge-track" />
                      <div
                        className="home-obs-gauge-fill"
                        style={{ width: `${ivsPctGauge}%` }}
                      />
                      <span
                        className="home-obs-gauge-marker home-obs-gauge-marker--nac"
                        style={{ left: `${mediaNacPct}%` }}
                        title="Média nacional"
                      />
                      <strong className="home-obs-gauge-value">{fmtIndice(ivsVal)}</strong>
                    </div>
                    <div className="home-obs-gauge-labels">
                      <span>0</span>
                      <span>Média nacional {fmtIndice(mediaNac)}</span>
                      <span>1</span>
                    </div>
                  </div>
                ) : (
                  <p className="home-obs-ivcad-pending">
                    IVS ainda não calculado.{" "}
                    <Link to="/vigilancia">Gere as visões em Vigilância</Link>.
                  </p>
                )}
              </article>
            </div>

            <div className="home-obs-charts">
              <article className="home-obs-chart fx-card">
                <h2>Famílias por meses após atualização</h2>
                <ul className="home-hbar-list">
                  {painel.por_meses_atualizacao.map((item) => (
                    <li key={item.rotulo} className="home-hbar-row">
                      <span className="home-hbar-label">{item.titulo}</span>
                      <span className="home-hbar-track">
                        <span
                          className="home-hbar-fill home-hbar-fill--meses"
                          style={{ width: barPct(item.pct, maxMesesPct) }}
                        />
                      </span>
                      <span className="home-hbar-val">{item.total.toLocaleString("pt-BR")}</span>
                    </li>
                  ))}
                </ul>
              </article>

              <article className="home-obs-chart fx-card">
                <h2>Famílias por faixa de renda per capita</h2>
                <ul className="home-hbar-list">
                  {painel.por_faixa_renda.map((item) => (
                    <li key={item.rotulo} className="home-hbar-row">
                      <span className="home-hbar-label">{item.titulo}</span>
                      <span className="home-hbar-track">
                        <span
                          className={`home-hbar-fill home-hbar-fill--${item.rotulo}`}
                          style={{ width: barPct(item.pct, maxRendaPct) }}
                        />
                      </span>
                      <span className="home-hbar-val">{item.total.toLocaleString("pt-BR")}</span>
                    </li>
                  ))}
                </ul>
              </article>

              <article className="home-obs-chart fx-card">
                <h2>Top 5 bairros — famílias cadastradas</h2>
                <p className="home-obs-chart-sub">Bairro territorial (geo × CEP)</p>
                {painel.top_bairros.length === 0 ? (
                  <p className="home-obs-chart-empty">Sem bairro na geo. Ingeste tbl_geo e regenere a visão Família.</p>
                ) : (
                  <ul className="home-hbar-list">
                    {painel.top_bairros.map((item) => (
                      <li key={item.bairro} className="home-hbar-row home-hbar-row--bairro">
                        <span className="home-hbar-label" title={item.bairro}>
                          {item.posicao}. {item.bairro.toLocaleUpperCase("pt-BR")}
                        </span>
                        <span className="home-hbar-track">
                          <span
                            className="home-hbar-fill home-hbar-fill--bairro"
                            style={{ width: barPct(item.pct_do_total, maxBairroPct) }}
                          />
                        </span>
                        <span className="home-hbar-val">{item.familias.toLocaleString("pt-BR")}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </article>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
