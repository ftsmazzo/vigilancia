import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

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

type CrasPainel = {
  disponivel: boolean;
  mensagem?: string;
  cras_selecionado?: string;
  cras_titulo?: string;
  dicionario?: Record<string, string>;
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
  };
  tabela_cras?: CrasCatalogItem[];
  por_bairro?: BarItem[];
  por_faixa_renda?: BarItem[];
};

function BarChart({ title, items }: { title: string; items: BarItem[] }) {
  const slice = items.slice(0, 12);
  const max = Math.max(...slice.map((i) => i.total), 1);
  return (
    <div className="chart-panel fx-card">
      <h3 className="chart-panel-title">{title}</h3>
      {slice.length === 0 ? (
        <p className="ingestao-desc">Sem dados.</p>
      ) : (
        <ul className="chart-bars">
          {slice.map((item) => (
            <li key={item.rotulo} className="chart-bar-row">
              <span className="chart-bar-label" title={item.rotulo}>
                {item.rotulo}
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
    [token]
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

  return (
    <section className="kpi-page cras-page">
      <div className="kpi-head fx-card">
        <h1>CADU por CRAS</h1>
        <p>
          Territorialização do Cadastro Único pela unidade de referência (
          <code className="inline-code">d.cod_unidade_territorial_fam</code> /{" "}
          <code className="inline-code">d.nom_unidade_territorial_fam</code>). Atualize{" "}
          <Link to="/vigilancia">Família</Link> e <Link to="/vigilancia">Pessoas</Link> antes de analisar.
        </p>

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
          <div className="kpi-grid">
            <article className="kpi-card kpi-card--accent">
              <small>Famílias</small>
              <strong>{r.familias.toLocaleString("pt-BR")}</strong>
              <span>No recorte selecionado</span>
            </article>
            <article className="kpi-card">
              <small>Pessoas (membros)</small>
              <strong>{r.pessoas.toLocaleString("pt-BR")}</strong>
              <span>Linhas na visão Pessoas</span>
            </article>
            <article className="kpi-card">
              <small>Mulheres</small>
              <strong>{r.mulheres.toLocaleString("pt-BR")}</strong>
              <span>{r.pct_mulheres.toLocaleString("pt-BR")}% (com sexo informado)</span>
            </article>
            <article className="kpi-card">
              <small>Homens</small>
              <strong>{r.homens.toLocaleString("pt-BR")}</strong>
              <span>{r.pct_homens.toLocaleString("pt-BR")}% (com sexo informado)</span>
            </article>
            <article className="kpi-card">
              <small>Na folha PBF</small>
              <strong>{r.familias_pbf.toLocaleString("pt-BR")}</strong>
              <span>{r.pct_familias_pbf.toLocaleString("pt-BR")}% das famílias</span>
            </article>
            <article className="kpi-card">
              <small>Renda per capita ≤ R$ 218</small>
              <strong>{r.familias_renda_ate_218.toLocaleString("pt-BR")}</strong>
              <span>{r.pct_renda_ate_218.toLocaleString("pt-BR")}% das famílias</span>
            </article>
            <article className="kpi-card">
              <small>Renda R$ 219–706</small>
              <strong>{r.familias_renda_219_706.toLocaleString("pt-BR")}</strong>
              <span>Famílias no CADU</span>
            </article>
            <article className="kpi-card">
              <small>Atualizadas ≤ 24 meses (TAC)</small>
              <strong>{r.familias_tac_24m.toLocaleString("pt-BR")}</strong>
              <span>Famílias com cadastro recente</span>
            </article>
          </div>

          {!isTodos && (
            <div className="chart-grid">
              <BarChart title="Bairros (famílias)" items={painel.por_bairro ?? []} />
              <BarChart title="Faixa de renda (código CADU)" items={painel.por_faixa_renda ?? []} />
            </div>
          )}

          {isTodos && painel.tabela_cras && painel.tabela_cras.length > 0 && (
            <>
              <h2 className="kpi-section-title">Comparativo por unidade</h2>
              <div className="cras-table-wrap fx-card">
                <table className="cras-table">
                  <thead>
                    <tr>
                      <th>Nº</th>
                      <th>Código</th>
                      <th>Nome da unidade</th>
                      <th>Famílias</th>
                      <th>Pessoas</th>
                      <th>Mulheres</th>
                      <th>Homens</th>
                      <th>Folha PBF</th>
                      <th>Renda ≤ 218</th>
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
                            title="Ver detalhe desta unidade"
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
