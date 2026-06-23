import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import BarChartPanel, { type BarItem } from "../components/charts/BarChartPanel";
import DonutChart from "../components/charts/DonutChart";
import TerritorialFilterSelects, { appendTerritorialParams } from "../components/TerritorialFilterSelects";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

type Props = {
  token: string;
};


type Painel = {
  disponivel: boolean;
  mensagem?: string;
  titulo?: string;
  fonte?: string;
  cras_selecionado?: string;
  bairro_selecionado?: string | null;
  resumo?: {
    familias: number;
    pessoas: number;
    homens: number;
    mulheres: number;
    pct_homens: number;
    pct_mulheres: number;
    nao_informado_sexo: number;
  };
  por_sexo?: BarItem[];
  por_deficiencia_binario?: BarItem[];
  por_raca?: BarItem[];
  por_escolaridade?: BarItem[];
  por_deficiencia?: BarItem[];
  por_faixa_idade?: BarItem[];
  por_renda_per_capita?: BarItem[];
  ranking_bairros?: {
    disponivel: boolean;
    mensagem?: string;
    fonte_bairro?: string;
    fonte_pbf?: string;
    items: RankingBairroItem[];
  };
};

type RankingBairroItem = {
  posicao: number;
  bairro: string;
  familias: number;
  familias_pbf: number;
  pct_pbf: number;
  pct_do_total: number;
  familias_bairro_geo: number;
  familias_bairro_cadu: number;
};

function fmtBairro(nome: string): string {
  return nome.toLocaleUpperCase("pt-BR");
}

export default function CaracterizacaoPage({ token }: Props) {
  const [painelLoading, setPainelLoading] = useState(true);
  const [error, setError] = useState("");
  const [crasCod, setCrasCod] = useState("__todos__");
  const [creasCod, setCreasCod] = useState("__todos__");
  const [bairroFiltro, setBairroFiltro] = useState("");
  const [painel, setPainel] = useState<Painel | null>(null);

  useEffect(() => {
    setPainelLoading(true);
    setError("");
    const ctrl = new AbortController();
    const params = new URLSearchParams();
    appendTerritorialParams(params, crasCod, creasCod, bairroFiltro);
    const qs = params.toString();
    fetch(`${API_URL}/api/v1/caracterizacao/painel${qs ? `?${qs}` : ""}`, {
      headers: { Authorization: `Bearer ${token}` },
      signal: ctrl.signal,
    })
      .then(async (res) => {
        const data = (await res.json()) as Painel & { detail?: string };
        if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Falha ao carregar.");
        setPainel(data);
      })
      .catch((e) => {
        if (ctrl.signal.aborted) return;
        setError(e instanceof Error ? e.message : "Erro ao carregar caracterização.");
        setPainel(null);
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setPainelLoading(false);
      });
    return () => ctrl.abort();
  }, [token, crasCod, creasCod, bairroFiltro]);

  const r = painel?.resumo;
  const sexoSlices =
    painel?.por_sexo && painel.por_sexo.length > 0
      ? painel.por_sexo
      : r
        ? [
            { rotulo: "masculino", total: r.homens, pct: r.pct_homens },
            { rotulo: "feminino", total: r.mulheres, pct: r.pct_mulheres },
          ].filter((x) => x.total > 0)
        : [];

  const tituloRecorte = useMemo(() => {
    if (painel?.titulo) return painel.titulo;
    if (crasCod === "__todos__" && creasCod === "__todos__" && !bairroFiltro.trim()) {
      return "Município inteiro";
    }
    return "Recorte territorial";
  }, [painel?.titulo, crasCod, creasCod, bairroFiltro]);

  return (
    <section className="kpi-page caracterizacao-page">
      <header className="caract-hero fx-card">
        <div className="caract-hero-text">
          <h1>Caracterização sociodemográfica</h1>
          <p className="caract-lead">
            Perfil do público no <strong>Cadastro Único</strong> — raça, sexo, escolaridade, deficiência,
            faixa etária e renda per capita com recorte territorial por CRAS, CREAS e bairro (geo × CEP).
          </p>
          <p className="caract-meta">{painel?.fonte}</p>
          <p className="caract-link">
            <Link to="/ivs">Índice de vulnerabilidade (IVS)</Link>
          </p>
        </div>
      </header>

      <section className="caract-filtros fx-card">
        <div className="territorial-filtros-toolbar">
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
          />
          <button
            type="button"
            className="btn btn-secondary territorial-filtros-clear"
            onClick={() => {
              setCrasCod("__todos__");
              setCreasCod("__todos__");
              setBairroFiltro("");
            }}
          >
            Limpar filtros
          </button>
        </div>
        <p className="caract-recorte-label">
          Exibindo: <strong>{tituloRecorte}</strong>
        </p>
      </section>

      {error && <p className="error caracterizacao-erro">{error}</p>}

      {painelLoading && !painel && <p className="caract-loading">Carregando perfil do CADU…</p>}
      {painelLoading && painel && <p className="caract-loading caract-loading--inline">Atualizando recorte…</p>}

      {!painelLoading && painel && !painel.disponivel && (
        <p className="convivencia-alerta convivencia-alerta--aviso">
          {painel.mensagem || "Gere as visões Família e Pessoas em Vigilância."}
        </p>
      )}

      {painel && painel.disponivel && r && (
        <>
          <div className="caract-kpi-strip" aria-label="Resumo">
            <article className="kpi-card caract-kpi">
              <small>Pessoas</small>
              <strong>{r.pessoas.toLocaleString("pt-BR")}</strong>
            </article>
            <article className="kpi-card caract-kpi">
              <small>Famílias</small>
              <strong>{r.familias.toLocaleString("pt-BR")}</strong>
            </article>
            <article className="kpi-card caract-kpi">
              <small>Homens</small>
              <strong>{r.homens.toLocaleString("pt-BR")}</strong>
              <span>{r.pct_homens.toLocaleString("pt-BR")}%</span>
            </article>
            <article className="kpi-card caract-kpi">
              <small>Mulheres</small>
              <strong>{r.mulheres.toLocaleString("pt-BR")}</strong>
              <span>{r.pct_mulheres.toLocaleString("pt-BR")}%</span>
            </article>
          </div>

          <div className="caract-donut-row chart-grid">
            <DonutChart
              title="Sexo"
              subtitle="Distribuição entre masculino e feminino"
              items={sexoSlices}
              centerLabel="pessoas"
              centerValue={r.pessoas.toLocaleString("pt-BR")}
              uppercaseLabels
            />
            <DonutChart
              title="Deficiência"
              subtitle="Com ou sem deficiência declarada"
              items={painel.por_deficiencia_binario ?? []}
              uppercaseLabels
            />
          </div>

          <h2 className="kpi-section-title caract-section-title">Renda familiar per capita</h2>
          <div className="chart-grid caract-charts caract-charts--renda">
            <BarChartPanel
              title="Faixas de renda per capita"
              subtitle="Contagem de famílias por faixa (vig.mvw_familia.renda_per_capita)"
              items={painel.por_renda_per_capita ?? []}
              maxBars={8}
              accent="spectrum"
              uppercaseLabels
            />
          </div>

          <h2 className="kpi-section-title caract-section-title">Composição detalhada</h2>
          <div className="chart-grid caract-charts">
            <BarChartPanel
              title="Raça / cor"
              subtitle="Autodeclaração no Cadastro Único"
              items={painel.por_raca ?? []}
              accent="cool"
              uppercaseLabels
            />
            <BarChartPanel
              title="Escolaridade"
              subtitle="Grau de instrução"
              items={painel.por_escolaridade ?? []}
              accent="warm"
              uppercaseLabels
            />
            <BarChartPanel
              title="Tipo de deficiência"
              subtitle="Classificação por tipo"
              items={painel.por_deficiencia ?? []}
              accent="spectrum"
              uppercaseLabels
            />
            <BarChartPanel
              title="Faixa etária"
              subtitle="Idade em anos completos"
              items={painel.por_faixa_idade ?? []}
              accent="cool"
              uppercaseLabels
            />
          </div>

          {painel.ranking_bairros && !bairroFiltro.trim() && (
            <>
              <h2 className="kpi-section-title caract-section-title">Ranking por bairro (GEO)</h2>
              {!painel.ranking_bairros.disponivel ? (
                <p className="convivencia-alerta convivencia-alerta--aviso">
                  {painel.ranking_bairros.mensagem}
                </p>
              ) : (
                <div className="caract-ranking-wrap fx-card">
                  <p className="caract-ranking-desc">
                    Top 10 bairros com mais famílias no recorte. Bairro territorial via geo × CEP;
                    fallback para bairro informado no CADU.
                  </p>
                  <div className="cras-table-wrap">
                    <table className="cras-table caract-ranking-table">
                      <thead>
                        <tr>
                          <th>#</th>
                          <th>Bairro</th>
                          <th className="num">Famílias</th>
                          <th>Participação</th>
                          <th className="num">Com PBF</th>
                          <th className="num">% PBF</th>
                          <th>Origem</th>
                        </tr>
                      </thead>
                      <tbody>
                        {painel.ranking_bairros.items.map((row) => {
                          const maxFam = painel.ranking_bairros!.items[0]?.familias || 1;
                          const geoPct =
                            row.familias > 0
                              ? Math.round((100 * row.familias_bairro_geo) / row.familias)
                              : 0;
                          return (
                            <tr key={row.bairro}>
                              <td className="num">{row.posicao}</td>
                              <td className="caract-ranking-bairro">{fmtBairro(row.bairro)}</td>
                              <td className="num">{row.familias.toLocaleString("pt-BR")}</td>
                              <td>
                                <div className="caract-mini-bar">
                                  <div
                                    className="caract-mini-bar-fill caract-mini-bar-fill--fam"
                                    style={{
                                      width: `${Math.max(6, (row.familias / maxFam) * 100)}%`,
                                    }}
                                  />
                                </div>
                                <small>{row.pct_do_total.toLocaleString("pt-BR")}%</small>
                              </td>
                              <td className="num">{row.familias_pbf.toLocaleString("pt-BR")}</td>
                              <td>
                                <div className="caract-pbf-pill">
                                  <span
                                    className="caract-pbf-pill-fill"
                                    style={{ width: `${Math.min(100, row.pct_pbf)}%` }}
                                  />
                                  <span className="caract-pbf-pill-text">
                                    {row.pct_pbf.toLocaleString("pt-BR")}%
                                  </span>
                                </div>
                              </td>
                              <td>
                                <span
                                  className={
                                    geoPct >= 80
                                      ? "caract-tag caract-tag--geo"
                                      : "caract-tag caract-tag--mix"
                                  }
                                >
                                  {geoPct >= 80 ? "GEO" : `${geoPct}% GEO`}
                                </span>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
