import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { rotuloAmigavel } from "../lib/caduLabels";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

function formatFetchError(e: unknown, context: string): string {
  if (e instanceof TypeError && /fetch/i.test(e.message)) {
    return (
      `Não foi possível contactar a API (${context}). Verifique se o serviço da API está no ar, ` +
      `se VITE_API_URL no build do frontend aponta para a URL pública correta (atual: ${API_URL}) ` +
      `e se CORS_ORIGINS na API inclui o domínio do site. Detalhe: ${e.message}`
    );
  }
  return e instanceof Error ? e.message : `Erro em ${context}.`;
}

async function apiGet(path: string, token: string): Promise<Response> {
  return fetch(`${API_URL}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
}

type Props = {
  token: string;
};

type CrasCatalogItem = {
  cras_cod: string;
  cras_codigo_exibicao: string;
  cras_nome: string;
  cras_numero_ordem?: number | null;
  rotulo_ordenado?: string;
  familias: number;
  pessoas: number;
  homens: number;
  mulheres: number;
  familias_pbf: number;
  familias_renda_ate_218: number;
};

type BarItem = { rotulo: string; total: number; pct: number };

type SiscResumo = {
  atendimentos: number;
  nis_distintos: number;
  vinculados_cadu: number;
  pct_vinculados_cadu?: number;
  prioritarios: number;
  com_deficiencia: number;
  sem_vinculo_cadu?: number;
};

type SiscPainel = {
  disponivel: boolean;
  mensagem?: string;
  modo?: string;
  resumo?: SiscResumo;
  tabela_por_cras?: Array<SiscResumo & { cras_cod: string; cras_nome: string }>;
  por_faixa_etaria?: BarItem[];
  por_grupo?: BarItem[];
};

type CrasPainel = {
  disponivel: boolean;
  painel_versao?: number;
  mensagem?: string;
  cras_selecionado?: string;
  cras_titulo?: string;
  resumo?: {
    familias: number;
    pessoas: number;
    homens: number;
    mulheres: number;
    pct_homens: number;
    pct_mulheres: number;
    familias_pbf: number;
    pct_familias_pbf: number;
    familias_renda_ate_218: number;
    familias_renda_219_706: number;
    familias_tac_24m: number;
    pct_renda_ate_218: number;
    pessoas_com_deficiencia: number;
    pct_pessoas_deficiencia: number;
    pessoas_situacao_rua: number;
    pessoas_atendidas_cras: number;
  };
  tabela_cras?: CrasCatalogItem[];
  por_faixa_idade?: BarItem[];
  por_escolaridade?: BarItem[];
  por_deficiencia?: BarItem[];
  por_raca?: BarItem[];
  por_bairro?: BarItem[];
  por_faixa_renda?: BarItem[];
  sisc?: SiscPainel;
};

function BarChart({
  title,
  subtitle,
  items,
  translate = true,
}: {
  title: string;
  subtitle?: string;
  items: BarItem[];
  translate?: boolean;
}) {
  const slice = items.slice(0, 12);
  const max = Math.max(...slice.map((i) => i.total), 1);
  return (
    <div className="chart-panel fx-card">
      <h3 className="chart-panel-title">{title}</h3>
      {subtitle && <p className="chart-panel-sub">{subtitle}</p>}
      {slice.length === 0 ? (
        <p className="ingestao-desc">Sem dados.</p>
      ) : (
        <ul className="chart-bars">
          {slice.map((item) => (
            <li key={item.rotulo} className="chart-bar-row">
              <span className="chart-bar-label" title={item.rotulo}>
                {translate ? rotuloAmigavel(item.rotulo) : item.rotulo}
              </span>
              <div className="chart-bar-track">
                <div className="chart-bar-fill" style={{ width: `${Math.max(4, (item.total / max) * 100)}%` }} />
              </div>
              <span className="chart-bar-value">
                {item.total.toLocaleString("pt-BR")} <small>({item.pct.toLocaleString("pt-BR")}%)</small>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function CrasPage({ token }: Props) {
  const [catalog, setCatalog] = useState<CrasCatalogItem[]>([]);
  const [crasCod, setCrasCod] = useState("__todos__");
  const [painel, setPainel] = useState<CrasPainel | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const loadCatalog = useCallback(async () => {
    try {
      const res = await apiGet("/api/v1/cras/catalog", token);
      const data = (await res.json().catch(() => ({}))) as { items?: CrasCatalogItem[]; detail?: unknown };
      if (res.status === 404) {
        throw new Error(
          "Rota /api/v1/cras não encontrada. Faça rebuild/restart da API no EasyPanel (commit com painel CRAS).",
        );
      }
      if (!res.ok) {
        throw new Error(typeof data.detail === "string" ? data.detail : `Falha ao listar CRAS (${res.status}).`);
      }
      setCatalog(data.items ?? []);
    } catch (e) {
      throw new Error(formatFetchError(e, "catálogo CRAS"));
    }
  }, [token]);

  const loadPainel = useCallback(
    async (cod: string) => {
      setLoading(true);
      setError("");
      try {
        const q = cod && cod !== "__todos__" ? `?cras_cod=${encodeURIComponent(cod)}` : "?cras_cod=__todos__";
        const res = await apiGet(`/api/v1/cras/painel${q}`, token);
        const data = (await res.json().catch(() => ({}))) as CrasPainel & { detail?: unknown };
        if (!res.ok) {
          throw new Error(typeof data.detail === "string" ? data.detail : `Falha no painel CRAS (${res.status}).`);
        }
        setPainel(data);
      } catch (e) {
        setError(formatFetchError(e, "painel CRAS"));
        setPainel(null);
      } finally {
        setLoading(false);
      }
    },
    [token],
  );

  useEffect(() => {
    void (async () => {
      try {
        await loadCatalog();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Erro ao carregar catálogo.");
      }
    })();
  }, [loadCatalog]);

  useEffect(() => {
    void loadPainel(crasCod);
  }, [crasCod, loadPainel]);

  const r = painel?.resumo;
  const isTodos = crasCod === "__todos__";
  const sisc = painel?.sisc;

  return (
    <section className="kpi-page cras-page">
      <div className="kpi-head fx-card">
        <h1>CADU por CRAS</h1>
        <p>
          Territorialização do Cadastro Único e cruzamento com o SISC (Serviço de Convivência). Campos do dicionário:{" "}
          <code className="inline-code">d.cod_unidade_territorial_fam</code>,{" "}
          <code className="inline-code">p.grau_instrucao</code>,{" "}
          <code className="inline-code">p.cod_deficiencia_memb</code>. Atualize{" "}
          <Link to="/vigilancia">Família</Link> e <Link to="/vigilancia">Pessoas</Link>.
        </p>
        {painel?.painel_versao != null && (
          <p className="convivencia-versao">Painel CRAS v{painel.painel_versao}</p>
        )}

        <label className="cras-select-wrap">
          <span>Unidade (CRAS)</span>
          <select
            className="cras-select"
            value={crasCod}
            onChange={(ev) => setCrasCod(ev.target.value)}
            disabled={loading || catalog.length === 0}
          >
            <option value="__todos__">— Todos os CRAS (visão municipal) —</option>
            {catalog.map((c) => (
              <option key={c.cras_cod} value={c.cras_cod}>
                {(c.rotulo_ordenado ?? c.cras_nome) +
                  (c.cras_codigo_exibicao !== "—" ? ` [${c.cras_codigo_exibicao}]` : "")}
                {" · "}
                {c.familias.toLocaleString("pt-BR")} fam.
              </option>
            ))}
          </select>
        </label>
      </div>

      {error && <p className="error">{error}</p>}
      {loading && <p className="ingestao-desc">Carregando indicadores…</p>}

      {painel?.disponivel && r && (
        <>
          <h2 className="kpi-section-title">{painel.cras_titulo}</h2>

          <h3 className="kpi-section-title" style={{ fontSize: "1rem" }}>
            Cadastro Único — resumo
          </h3>
          <div className="kpi-grid">
            <article className="kpi-card kpi-card--accent">
              <small>Famílias</small>
              <strong>{r.familias.toLocaleString("pt-BR")}</strong>
            </article>
            <article className="kpi-card">
              <small>Pessoas</small>
              <strong>{r.pessoas.toLocaleString("pt-BR")}</strong>
            </article>
            <article className="kpi-card">
              <small>Mulheres / homens</small>
              <strong>
                {r.mulheres.toLocaleString("pt-BR")} / {r.homens.toLocaleString("pt-BR")}
              </strong>
            </article>
            <article className="kpi-card kpi-card--warn">
              <small>Com deficiência (pessoas)</small>
              <strong>{r.pessoas_com_deficiencia.toLocaleString("pt-BR")}</strong>
              <span>{r.pct_pessoas_deficiencia.toLocaleString("pt-BR")}% do público</span>
            </article>
            <article className="kpi-card">
              <small>Folha PBF (famílias)</small>
              <strong>{r.familias_pbf.toLocaleString("pt-BR")}</strong>
              <span>{r.pct_familias_pbf.toLocaleString("pt-BR")}%</span>
            </article>
            <article className="kpi-card">
              <small>Renda ≤ R$ 218</small>
              <strong>{r.familias_renda_ate_218.toLocaleString("pt-BR")}</strong>
              <span>famílias</span>
            </article>
          </div>

          <h3 className="kpi-section-title" style={{ fontSize: "1rem" }}>
            Faixa etária (CADU — todas as pessoas do recorte)
          </h3>
          <div className="chart-grid">
            <BarChart title="Distribuição por idade" items={painel.por_faixa_idade ?? []} />
          </div>

          {!isTodos && (
            <>
              <h3 className="kpi-section-title" style={{ fontSize: "1rem" }}>
                Perfil da unidade (CADU)
              </h3>
              <div className="chart-grid">
                <BarChart title="Escolaridade" subtitle="p.grau_instrucao" items={painel.por_escolaridade ?? []} />
                <BarChart title="Tipo de deficiência" items={painel.por_deficiencia ?? []} />
                <BarChart title="Raça / cor" items={painel.por_raca ?? []} />
                <BarChart title="Bairros (famílias)" items={painel.por_bairro ?? []} translate={false} />
                <BarChart title="Faixa renda familiar" items={painel.por_faixa_renda ?? []} translate={false} />
              </div>
            </>
          )}

          <h3 className="kpi-section-title" style={{ fontSize: "1rem" }}>
            Serviço de Convivência (SISC)
            <Link to="/convivencia" style={{ marginLeft: "0.75rem", fontSize: "0.85rem" }}>
              Painel Convivência →
            </Link>
          </h3>
          {sisc && !sisc.disponivel && (
            <p className="ingestao-desc fx-card" style={{ padding: "1rem" }}>
              {sisc.mensagem}
            </p>
          )}
          {sisc?.disponivel && sisc.modo === "unidade" && sisc.resumo && (
            <>
              <div className="kpi-grid kpi-grid-3">
                <article className="kpi-card">
                  <small>Atendimentos SISC</small>
                  <strong>{sisc.resumo.atendimentos.toLocaleString("pt-BR")}</strong>
                  <span>{sisc.resumo.nis_distintos.toLocaleString("pt-BR")} NIS</span>
                </article>
                <article className="kpi-card kpi-card--accent">
                  <small>Vinculados ao CADU</small>
                  <strong>{sisc.resumo.vinculados_cadu.toLocaleString("pt-BR")}</strong>
                  <span>{(sisc.resumo.pct_vinculados_cadu ?? 0).toLocaleString("pt-BR")}%</span>
                </article>
                <article className="kpi-card">
                  <small>Prioritários / com deficiência</small>
                  <strong>
                    {sisc.resumo.prioritarios.toLocaleString("pt-BR")} /{" "}
                    {sisc.resumo.com_deficiencia.toLocaleString("pt-BR")}
                  </strong>
                </article>
              </div>
              <div className="chart-grid">
                <BarChart
                  title="Faixa etária (relatório SISC)"
                  items={sisc.por_faixa_etaria ?? []}
                  translate={false}
                />
                <BarChart title="Grupos / turmas SISC" items={sisc.por_grupo ?? []} translate={false} />
              </div>
            </>
          )}
          {sisc?.disponivel && sisc.modo === "municipal" && sisc.tabela_por_cras && (
            <div className="cras-table-wrap fx-card">
              <table className="cras-table">
                <thead>
                  <tr>
                    <th>Unidade SISC</th>
                    <th>Atend.</th>
                    <th>Vinc. CADU</th>
                    <th>Priorit.</th>
                    <th>Deficiência</th>
                  </tr>
                </thead>
                <tbody>
                  {sisc.tabela_por_cras.map((row) => (
                    <tr key={row.cras_cod}>
                      <td>{row.cras_nome}</td>
                      <td className="num">{row.atendimentos.toLocaleString("pt-BR")}</td>
                      <td className="num">{row.vinculados_cadu.toLocaleString("pt-BR")}</td>
                      <td className="num">{row.prioritarios.toLocaleString("pt-BR")}</td>
                      <td className="num">{row.com_deficiencia.toLocaleString("pt-BR")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {isTodos && painel.tabela_cras && painel.tabela_cras.length > 0 && (
            <>
              <h2 className="kpi-section-title">Comparativo CADU por unidade</h2>
              <div className="cras-table-wrap fx-card">
                <table className="cras-table">
                  <thead>
                    <tr>
                      <th>Nº</th>
                      <th>Código</th>
                      <th>Nome</th>
                      <th>Famílias</th>
                      <th>Pessoas</th>
                      <th>Mulheres</th>
                      <th>Homens</th>
                      <th>PBF</th>
                      <th>Renda ≤218</th>
                    </tr>
                  </thead>
                  <tbody>
                    {painel.tabela_cras.map((row) => (
                      <tr key={row.cras_cod}>
                        <td className="num">{row.cras_numero_ordem ?? "—"}</td>
                        <td>
                          <button
                            type="button"
                            className="link-button"
                            onClick={() => setCrasCod(row.cras_cod)}
                          >
                            {row.cras_codigo_exibicao}
                          </button>
                        </td>
                        <td>{row.cras_nome}</td>
                        <td className="num">{row.familias.toLocaleString("pt-BR")}</td>
                        <td className="num">{row.pessoas.toLocaleString("pt-BR")}</td>
                        <td className="num">{row.mulheres.toLocaleString("pt-BR")}</td>
                        <td className="num">{row.homens.toLocaleString("pt-BR")}</td>
                        <td className="num">{row.familias_pbf.toLocaleString("pt-BR")}</td>
                        <td className="num">{row.familias_renda_ate_218.toLocaleString("pt-BR")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}
    </section>
  );
}
