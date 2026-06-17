import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import BarChartPanel, { type BarItem } from "../components/charts/BarChartPanel";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

type Props = {
  token: string;
};

type CrasOption = {
  cras_cod: string;
  cras_nome: string;
  rotulo_ordenado?: string;
};

type GrupoItem = {
  grupo: string;
  familias_distintas: number;
  pct_sobre_eventos?: number;
  pct_sobre_manut_cras?: number;
};

type CrasManut = {
  num_cras: string;
  nom_cras: string;
  familias_com_manutencao: number;
  top_grupos: GrupoItem[];
};

type Comparacao = {
  competencia_anterior: string;
  familias_com_evento: number;
  delta_familias_com_evento: number;
  delta_cancelamentos: number;
  delta_bloqueios: number;
  delta_reversoes: number;
};

type Painel = {
  disponivel: boolean;
  mensagem?: string;
  titulo?: string;
  competencia?: string;
  cras_selecionado?: string | null;
  resumo?: {
    familias_com_evento: number;
    familias_territorializadas: number;
    bloqueios: number;
    cancelamentos: number;
    suspensoes: number;
    reversoes: number;
    situacao_final_cancelar: number;
    situacao_final_bloquear: number;
    familias_folha_pbf: number;
    pct_evento_sobre_folha: number;
  };
  comparacao_anterior?: Comparacao | null;
  por_acao_grupo?: GrupoItem[];
  top_motivos_cancelamento?: Array<{
    cod_motivo: string;
    motivo: string;
    familias_distintas: number;
  }>;
  por_cras?: CrasManut[];
};

function fmtCompetencia(comp: string): string {
  if (comp.length !== 6) return comp;
  const mes = comp.slice(4, 6);
  const ano = comp.slice(0, 4);
  const nomes = [
    "",
    "jan",
    "fev",
    "mar",
    "abr",
    "mai",
    "jun",
    "jul",
    "ago",
    "set",
    "out",
    "nov",
    "dez",
  ];
  const m = parseInt(mes, 10);
  return `${nomes[m] ?? mes}/${ano}`;
}

/** Texto legível para variação em relação ao mês anterior. */
function textoVariacao(cmp: Comparacao | null | undefined, delta: number): string | null {
  if (!cmp) return null;
  const ref = fmtCompetencia(cmp.competencia_anterior);
  if (delta === 0) return `Igual a ${ref}`;
  const qtd = Math.abs(delta).toLocaleString("pt-BR");
  return delta > 0 ? `${qtd} a mais que em ${ref}` : `${qtd} a menos que em ${ref}`;
}

function rotuloCras(c: CrasManut): string {
  const n = (c.num_cras || "").trim();
  const nome = (c.nom_cras || "").trim();
  if (n && nome) return `CRAS ${n} — ${nome}`;
  if (nome) return nome;
  if (n) return `CRAS ${n}`;
  return "—";
}

export default function SibecPage({ token }: Props) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [competencias, setCompetencias] = useState<string[]>([]);
  const [competencia, setCompetencia] = useState("");
  const [crasCod, setCrasCod] = useState("__todos__");
  const [catalog, setCatalog] = useState<CrasOption[]>([]);
  const [painel, setPainel] = useState<Painel | null>(null);

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
    fetch(`${API_URL}/api/v1/vigilance/sibec/competencias`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(async (res) => {
        if (!res.ok) return;
        const data = (await res.json()) as { items: string[] };
        const items = data.items ?? [];
        setCompetencias(items);
        if (items.length > 0) setCompetencia((prev) => prev || items[0]);
      })
      .catch(() => setCompetencias([]));
  }, [token]);

  const loadPainel = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams();
      if (competencia) params.set("competencia", competencia);
      if (crasCod && crasCod !== "__todos__") params.set("cras_cod", crasCod);
      const qs = params.toString();
      const response = await fetch(`${API_URL}/api/v1/vigilance/sibec/painel${qs ? `?${qs}` : ""}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = (await response.json().catch(() => ({}))) as Painel & { detail?: unknown };
      if (!response.ok) {
        throw new Error(typeof data.detail === "string" ? data.detail : "Não foi possível carregar o painel.");
      }
      setPainel(data);
      if (data.competencia && !competencia) setCompetencia(data.competencia);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro inesperado.");
      setPainel(null);
    } finally {
      setLoading(false);
    }
  }, [token, competencia, crasCod]);

  useEffect(() => {
    void loadPainel();
  }, [loadPainel]);

  const barAcoes: BarItem[] = useMemo(
    () =>
      (painel?.por_acao_grupo ?? []).map((g) => ({
        rotulo: g.grupo,
        total: g.familias_distintas,
        pct: g.pct_sobre_eventos ?? 0,
      })),
    [painel],
  );

  const tituloRecorte = useMemo(() => {
    if (crasCod === "__todos__") return "Município inteiro";
    if (crasCod === "__sem_cras__") return "Sem CRAS de referência";
    const c = catalog.find((x) => x.cras_cod === crasCod);
    return c?.rotulo_ordenado || c?.cras_nome || crasCod;
  }, [crasCod, catalog]);

  const resumo = painel?.resumo;
  const cmp = painel?.comparacao_anterior;

  return (
    <div className="ivs-page sibec-page">
      <header className="ivs-hero fx-card">
        <div>
          <h1>SIBEC — Manutenções PBF</h1>
          <p className="ivs-hero-sub">
            Acompanhamento de bloqueios, cancelamentos e reversões no Bolsa Família, por competência e território.
          </p>
        </div>
        <div className="ivs-hero-actions">
          <Link to="/vigilancia" className="btn btn-primary" style={{ textDecoration: "none" }}>
            Atualizar dados
          </Link>
          <button type="button" className="btn btn-secondary" onClick={() => void loadPainel()} disabled={loading}>
            {loading ? "Carregando…" : "Recarregar"}
          </button>
        </div>
      </header>

      <section className="caract-filtros fx-card">
        <div className="caract-filtros-grid">
          <label>
            <span>Competência</span>
            <select
              className="cras-select"
              value={competencia}
              onChange={(e) => setCompetencia(e.target.value)}
              disabled={competencias.length === 0 || loading}
            >
              {competencias.length === 0 && <option value="">—</option>}
              {competencias.map((c) => (
                <option key={c} value={c}>
                  {fmtCompetencia(c)}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>CRAS</span>
            <select
              className="cras-select"
              value={crasCod}
              onChange={(e) => setCrasCod(e.target.value)}
              disabled={loading}
            >
              <option value="__todos__">Município inteiro</option>
              <option value="__sem_cras__">Sem CRAS de referência</option>
              {catalog.map((c) => (
                <option key={c.cras_cod} value={c.cras_cod}>
                  {c.rotulo_ordenado || c.cras_nome}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="btn btn-secondary caract-filtros-clear"
            onClick={() => {
              setCrasCod("__todos__");
              if (competencias.length > 0) setCompetencia(competencias[0]);
            }}
          >
            Limpar filtros
          </button>
        </div>
        <p className="caract-recorte-label">
          Exibindo: <strong>{tituloRecorte}</strong>
          {competencia && (
            <>
              {" "}
              · <strong>{fmtCompetencia(competencia)}</strong>
            </>
          )}
        </p>
      </section>

      {loading && <p className="caract-loading">Carregando…</p>}
      {error && <p className="error">{error}</p>}

      {!loading && painel && !painel.disponivel && (
        <section className="fx-card" style={{ marginTop: "1rem", padding: "1.25rem" }}>
          <p>{painel.mensagem}</p>
          <p style={{ marginTop: "0.75rem" }}>
            <Link to="/vigilancia">Abrir Vigilância</Link> para atualizar os dados.
          </p>
        </section>
      )}

      {!loading && painel?.disponivel && resumo && (
        <>
          <div className="kpi-grid" style={{ marginTop: "1rem" }}>
            <article className="kpi-card kpi-card--accent">
              <small>Famílias com manutenção</small>
              <strong>{resumo.familias_com_evento.toLocaleString("pt-BR")}</strong>
              <span>
                {resumo.pct_evento_sobre_folha.toLocaleString("pt-BR")}% das {resumo.familias_folha_pbf.toLocaleString("pt-BR")}{" "}
                famílias na folha PBF
              </span>
              {cmp && (
                <span className="kpi-variacao">{textoVariacao(cmp, cmp.delta_familias_com_evento)}</span>
              )}
            </article>
            <article className="kpi-card">
              <small>Bloqueios</small>
              <strong>{resumo.bloqueios.toLocaleString("pt-BR")}</strong>
              {cmp && (
                <span className="kpi-variacao">{textoVariacao(cmp, cmp.delta_bloqueios)}</span>
              )}
            </article>
            <article className="kpi-card">
              <small>Cancelamentos</small>
              <strong>{resumo.cancelamentos.toLocaleString("pt-BR")}</strong>
              {cmp && (
                <span className="kpi-variacao">{textoVariacao(cmp, cmp.delta_cancelamentos)}</span>
              )}
            </article>
            <article className="kpi-card">
              <small>Reversões</small>
              <strong>{resumo.reversoes.toLocaleString("pt-BR")}</strong>
              {cmp && (
                <span className="kpi-variacao">{textoVariacao(cmp, cmp.delta_reversoes)}</span>
              )}
            </article>
            <article className="kpi-card">
              <small>No território de referência</small>
              <strong>{resumo.familias_territorializadas.toLocaleString("pt-BR")}</strong>
              <span>famílias com CRAS identificado</span>
            </article>
            <article className="kpi-card">
              <small>Última situação no mês</small>
              <strong>
                {resumo.situacao_final_bloquear.toLocaleString("pt-BR")} bloqueadas ·{" "}
                {resumo.situacao_final_cancelar.toLocaleString("pt-BR")} canceladas
              </strong>
              <span>{resumo.suspensoes.toLocaleString("pt-BR")} suspensas</span>
            </article>
          </div>

          <div className="obs-charts-grid" style={{ marginTop: "1.25rem" }}>
            <BarChartPanel
              title="Por tipo de ação"
              items={barAcoes}
              emptyMessage="Sem registros nesta competência."
            />
          </div>

          {(painel.top_motivos_cancelamento?.length ?? 0) > 0 && (
            <section className="fx-card" style={{ marginTop: "1.25rem", padding: "1rem 1.25rem" }}>
              <h2 className="obs-section-title">Principais motivos de cancelamento</h2>
              <div className="cras-table-wrap">
                <table className="cras-table">
                  <thead>
                    <tr>
                      <th>Motivo</th>
                      <th className="num">Famílias</th>
                    </tr>
                  </thead>
                  <tbody>
                    {painel.top_motivos_cancelamento!.map((m) => (
                      <tr key={`${m.cod_motivo}-${m.motivo.slice(0, 40)}`}>
                        <td>{m.motivo}</td>
                        <td className="num">{m.familias_distintas.toLocaleString("pt-BR")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {(painel.por_cras?.length ?? 0) > 0 && crasCod === "__todos__" && (
            <section className="fx-card" style={{ marginTop: "1.25rem", padding: "1rem 1.25rem" }}>
              <h2 className="obs-section-title">Por CRAS</h2>
              <div className="cras-table-wrap">
                <table className="cras-table">
                  <thead>
                    <tr>
                      <th>CRAS</th>
                      <th className="num">Total</th>
                      <th className="num">Cancelar</th>
                      <th className="num">Bloquear</th>
                      <th className="num">Suspender</th>
                      <th className="num">Encerrar</th>
                      <th className="num">Excluir</th>
                    </tr>
                  </thead>
                  <tbody>
                    {painel.por_cras!.map((c) => {
                      const byGrupo = Object.fromEntries(
                        c.top_grupos.map((g) => [g.grupo, g.familias_distintas]),
                      );
                      return (
                        <tr key={`${c.num_cras}-${c.nom_cras}`}>
                          <td>{rotuloCras(c)}</td>
                          <td className="num">{c.familias_com_manutencao.toLocaleString("pt-BR")}</td>
                          <td className="num">{(byGrupo.Cancelar ?? 0).toLocaleString("pt-BR")}</td>
                          <td className="num">{(byGrupo.Bloquear ?? 0).toLocaleString("pt-BR")}</td>
                          <td className="num">{(byGrupo.Suspender ?? 0).toLocaleString("pt-BR")}</td>
                          <td className="num">{(byGrupo.Encerrar ?? 0).toLocaleString("pt-BR")}</td>
                          <td className="num">{(byGrupo.Excluir ?? 0).toLocaleString("pt-BR")}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
}
