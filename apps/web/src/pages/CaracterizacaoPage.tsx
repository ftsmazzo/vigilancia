import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import BarChartPanel, { type BarItem } from "../components/charts/BarChartPanel";
import DonutChart from "../components/charts/DonutChart";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

type Props = {
  token: string;
};

type CrasOption = {
  cras_cod: string;
  cras_nome: string;
  cras_codigo_exibicao?: string;
  rotulo_ordenado?: string;
  familias: number;
};

type Painel = {
  disponivel: boolean;
  mensagem?: string;
  titulo?: string;
  fonte?: string;
  cras_selecionado?: string;
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

export default function CaracterizacaoPage({ token }: Props) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [crasCod, setCrasCod] = useState("__todos__");
  const [catalog, setCatalog] = useState<CrasOption[]>([]);
  const [painel, setPainel] = useState<Painel | null>(null);

  useEffect(() => {
    fetch(`${API_URL}/api/v1/cras/catalog`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(async (res) => {
        if (!res.ok) throw new Error();
        const data = (await res.json()) as { items: CrasOption[] };
        setCatalog(data.items || []);
      })
      .catch(() => setCatalog([]));
  }, [token]);

  useEffect(() => {
    setLoading(true);
    setError("");
    const q = crasCod && crasCod !== "__todos__" ? `?cras_cod=${encodeURIComponent(crasCod)}` : "";
    fetch(`${API_URL}/api/v1/caracterizacao/painel${q}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(async (res) => {
        const data = (await res.json()) as Painel & { detail?: string };
        if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Falha ao carregar.");
        setPainel(data);
      })
      .catch((e) => {
        setError(e instanceof Error ? e.message : "Erro ao carregar caracterização.");
        setPainel(null);
      })
      .finally(() => setLoading(false));
  }, [token, crasCod]);

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

  return (
    <section className="kpi-page caracterizacao-page">
      <header className="caract-hero fx-card">
        <div className="caract-hero-text">
          <h1>Caracterização sociodemográfica</h1>
          <p className="caract-lead">
            Perfil do público no <strong>Cadastro Único</strong> — fonte verdade do município. Raça, sexo,
            escolaridade, deficiência e faixa etária com a mesma classificação dos painéis CRAS e Convivência.
          </p>
          <p className="caract-meta">
            {painel?.fonte}
            {painel?.titulo && <> · <span className="fx-accent-word">{painel.titulo}</span></>}
          </p>
          <p className="caract-link">
            <Link to="/municipio">Cadastro textual do município</Link>
            {" · "}
            <Link to="/cras">Painel por CRAS</Link>
          </p>
        </div>

        <label className="cras-select-wrap caract-filter">
          <span>Recorte territorial (CRAS no CADU)</span>
          <select
            className="cras-select"
            value={crasCod}
            onChange={(e) => setCrasCod(e.target.value)}
            disabled={loading}
          >
            <option value="__todos__">Município inteiro</option>
            <option value="__sem_cras__">Sem CRAS informado</option>
            {catalog.map((c) => (
              <option key={c.cras_cod} value={c.cras_cod}>
                {(c.rotulo_ordenado ?? c.cras_nome) +
                  (c.cras_codigo_exibicao && c.cras_codigo_exibicao !== "—"
                    ? ` [${c.cras_codigo_exibicao}]`
                    : "")}
                {" · "}
                {c.familias.toLocaleString("pt-BR")} fam.
              </option>
            ))}
          </select>
        </label>
      </header>

      {error && <p className="error caracterizacao-erro">{error}</p>}

      {loading && <p className="caract-loading">Carregando perfil do CADU…</p>}

      {!loading && painel && !painel.disponivel && (
        <p className="convivencia-alerta convivencia-alerta--aviso">
          {painel.mensagem || "Gere as visões Família e Pessoas em Vigilância."}
        </p>
      )}

      {!loading && r && painel?.disponivel && (
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
              subtitle="Distribuição entre masculino e feminino (CADU)"
              items={sexoSlices}
              centerLabel="pessoas"
              centerValue={r.pessoas.toLocaleString("pt-BR")}
            />
            <DonutChart
              title="Deficiência"
              subtitle="Com ou sem deficiência declarada"
              items={painel.por_deficiencia_binario ?? []}
            />
          </div>

          {painel.ranking_bairros && (
            <>
              <h2 className="kpi-section-title caract-section-title">Ranking por bairro (GEO)</h2>
              {!painel.ranking_bairros.disponivel ? (
                <p className="convivencia-alerta convivencia-alerta--aviso">
                  {painel.ranking_bairros.mensagem}
                </p>
              ) : (
                <div className="caract-ranking-wrap fx-card">
                  <p className="caract-ranking-desc">
                    Top 10 bairros com mais famílias no Cadastro Único. O bairro vem da base{" "}
                    <strong>geo</strong> quando o CEP da família existe em{" "}
                    <code className="inline-code">tbl_geo</code>; caso contrário, usa-se o bairro
                    informado no CADU.
                  </p>
                  <p className="fx-card-sub caract-ranking-meta">
                    {painel.ranking_bairros.fonte_bairro} · {painel.ranking_bairros.fonte_pbf}
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
                          <th>Origem bairro</th>
                        </tr>
                      </thead>
                      <tbody>
                        {painel.ranking_bairros.items.map((row) => {
                          const maxFam =
                            painel.ranking_bairros!.items[0]?.familias || 1;
                          const geoPct =
                            row.familias > 0
                              ? Math.round((100 * row.familias_bairro_geo) / row.familias)
                              : 0;
                          return (
                            <tr key={row.bairro}>
                              <td className="num">{row.posicao}</td>
                              <td className="caract-ranking-bairro">{row.bairro}</td>
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
                                  {geoPct >= 80 ? "GEO" : `${geoPct}% geo`}
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

          <h2 className="kpi-section-title caract-section-title">Renda familiar per capita</h2>
          <div className="chart-grid caract-charts caract-charts--renda">
            <BarChartPanel
              title="Faixas de renda per capita"
              subtitle="Por família (vig.mvw_familia.renda_per_capita) — contagem em número de famílias"
              items={painel.por_renda_per_capita ?? []}
              maxBars={8}
              accent="warm"
            />
          </div>

          <h2 className="kpi-section-title caract-section-title">Composição detalhada</h2>
          <div className="chart-grid caract-charts">
            <BarChartPanel
              title="Raça / cor"
              subtitle="Autodeclaração no Cadastro Único"
              items={painel.por_raca ?? []}
              accent="cool"
            />
            <BarChartPanel
              title="Escolaridade"
              subtitle="Grau de instrução"
              items={painel.por_escolaridade ?? []}
              accent="warm"
            />
            <BarChartPanel
              title="Tipo de deficiência"
              subtitle="Classificação por tipo (pode haver múltiplos indicadores)"
              items={painel.por_deficiencia ?? []}
            />
            <BarChartPanel
              title="Faixa etária"
              subtitle="Idade em anos completos"
              items={painel.por_faixa_idade ?? []}
              accent="cool"
            />
          </div>
        </>
      )}
    </section>
  );
}
