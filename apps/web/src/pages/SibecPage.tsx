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

type Painel = {
  disponivel: boolean;
  mensagem?: string;
  titulo?: string;
  fonte?: string;
  grao?: string;
  competencia?: string;
  cras_selecionado?: string | null;
  resumo?: {
    familias_com_evento: number;
    familias_territorializadas: number;
    familias_vinculo_cadu: number;
    bloqueios: number;
    cancelamentos: number;
    suspensoes: number;
    reversoes: number;
    exclusoes: number;
    desbloqueios: number;
    situacao_final_cancelar: number;
    situacao_final_bloquear: number;
    familias_folha_pbf: number;
    pct_evento_sobre_folha: number;
  };
  comparacao_anterior?: {
    competencia_anterior: string;
    familias_com_evento: number;
    delta_familias_com_evento: number;
    delta_cancelamentos: number;
    delta_bloqueios: number;
    delta_reversoes: number;
  } | null;
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

function fmtDelta(n: number): string {
  if (n === 0) return "0";
  return n > 0 ? `+${n.toLocaleString("pt-BR")}` : n.toLocaleString("pt-BR");
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
        throw new Error(typeof data.detail === "string" ? data.detail : "Falha ao carregar painel SIBEC.");
      }
      if (!data.disponivel) {
        setPainel(data);
        return;
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
    if (crasCod === "__todos__") return "Município";
    if (crasCod === "__sem_cras__") return "Sem CRAS territorial";
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
            Vigilância de <strong>eventos de risco</strong> (bloqueio, cancelamento, reversão) distinta da folha de
            pagamento. Grão: <strong>1 família por competência</strong> (nível família no SIBEC), territorializada via
            geo × CEP.
          </p>
        </div>
        <div className="ivs-hero-actions">
          <Link to="/ingestao" className="btn btn-secondary" style={{ textDecoration: "none" }}>
            Ingestão
          </Link>
          <Link to="/vigilancia" className="btn btn-primary" style={{ textDecoration: "none" }}>
            Gerar visão SIBEC
          </Link>
        </div>
      </header>

      <section className="fx-card obs-filters" style={{ marginTop: "1rem" }}>
        <div className="obs-filter-row">
          <label>
            Competência
            <select
              value={competencia}
              onChange={(e) => setCompetencia(e.target.value)}
              disabled={competencias.length === 0}
            >
              {competencias.length === 0 && <option value="">—</option>}
              {competencias.map((c) => (
                <option key={c} value={c}>
                  {fmtCompetencia(c)} ({c})
                </option>
              ))}
            </select>
          </label>
          <label>
            CRAS
            <select value={crasCod} onChange={(e) => setCrasCod(e.target.value)}>
              <option value="__todos__">Todo o município</option>
              <option value="__sem_cras__">Sem referência territorial</option>
              {catalog.map((c) => (
                <option key={c.cras_cod} value={c.cras_cod}>
                  {c.rotulo_ordenado || c.cras_nome}
                </option>
              ))}
            </select>
          </label>
        </div>
        <p className="obs-filter-hint">
          Recorte: <strong>{tituloRecorte}</strong>
          {painel?.grao && <> · {painel.grao}</>}
        </p>
      </section>

      {loading && <p className="obs-loading">Carregando painel SIBEC…</p>}
      {error && <p className="error">{error}</p>}

      {!loading && painel && !painel.disponivel && (
        <section className="fx-card" style={{ marginTop: "1rem", padding: "1.25rem" }}>
          <p>{painel.mensagem}</p>
          <p className="ingestao-desc" style={{ marginTop: "0.75rem" }}>
            Fluxo: ingestão dos analíticos de manutenção → aba <strong>SIBEC</strong> em{" "}
            <Link to="/vigilancia">Vigilância</Link> → gerar{" "}
            <code className="inline-code">vig.mvw_sibec_manut_familia_mes</code>.
          </p>
        </section>
      )}

      {!loading && painel?.disponivel && resumo && (
        <>
          <div className="kpi-grid" style={{ marginTop: "1rem" }}>
            <article className="kpi-card kpi-card--accent">
              <small>Famílias com evento</small>
              <strong>{resumo.familias_com_evento.toLocaleString("pt-BR")}</strong>
              <span>
                {resumo.pct_evento_sobre_folha.toLocaleString("pt-BR")}% da folha PBF (
                {resumo.familias_folha_pbf.toLocaleString("pt-BR")} fam.)
              </span>
            </article>
            <article className="kpi-card">
              <small>Bloqueios no mês</small>
              <strong>{resumo.bloqueios.toLocaleString("pt-BR")}</strong>
              {cmp && <span>Δ vs {fmtCompetencia(cmp.competencia_anterior)}: {fmtDelta(cmp.delta_bloqueios)}</span>}
            </article>
            <article className="kpi-card">
              <small>Cancelamentos no mês</small>
              <strong>{resumo.cancelamentos.toLocaleString("pt-BR")}</strong>
              {cmp && <span>Δ: {fmtDelta(cmp.delta_cancelamentos)}</span>}
            </article>
            <article className="kpi-card">
              <small>Reversões no mês</small>
              <strong>{resumo.reversoes.toLocaleString("pt-BR")}</strong>
              {cmp && <span>Δ: {fmtDelta(cmp.delta_reversoes)}</span>}
            </article>
            <article className="kpi-card">
              <small>Territorializadas</small>
              <strong>{resumo.familias_territorializadas.toLocaleString("pt-BR")}</strong>
              <span>Com CRAS via geo</span>
            </article>
            <article className="kpi-card">
              <small>Situação final (última ação)</small>
              <strong>
                {resumo.situacao_final_bloquear.toLocaleString("pt-BR")} bloq. /{" "}
                {resumo.situacao_final_cancelar.toLocaleString("pt-BR")} canc.
              </strong>
              <span>Suspensões: {resumo.suspensoes.toLocaleString("pt-BR")}</span>
            </article>
          </div>

          {cmp && (
            <p className="obs-filter-hint" style={{ marginTop: "0.5rem" }}>
              Comparado a {fmtCompetencia(cmp.competencia_anterior)}:{" "}
              {fmtDelta(cmp.delta_familias_com_evento)} famílias com evento.
            </p>
          )}

          <div className="obs-charts-grid" style={{ marginTop: "1.25rem" }}>
            <BarChartPanel
              title="Famílias por tipo de ação (situação final)"
              subtitle="Contagem distinta por família — não soma linhas brutas do SIBEC"
              items={barAcoes}
              emptyMessage="Sem eventos nesta competência."
            />
          </div>

          {(painel.top_motivos_cancelamento?.length ?? 0) > 0 && (
            <section className="fx-card" style={{ marginTop: "1.25rem", padding: "1rem 1.25rem" }}>
              <h2 className="obs-section-title">Principais motivos de cancelamento</h2>
              <div className="cras-table-wrap">
                <table className="cras-table">
                  <thead>
                    <tr>
                      <th>Cód.</th>
                      <th>Motivo</th>
                      <th>Famílias</th>
                    </tr>
                  </thead>
                  <tbody>
                    {painel.top_motivos_cancelamento!.map((m) => (
                      <tr key={`${m.cod_motivo}-${m.motivo.slice(0, 40)}`}>
                        <td>{m.cod_motivo || "—"}</td>
                        <td>{m.motivo}</td>
                        <td>{m.familias_distintas.toLocaleString("pt-BR")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {(painel.por_cras?.length ?? 0) > 0 && crasCod === "__todos__" && (
            <section className="fx-card" style={{ marginTop: "1.25rem", padding: "1rem 1.25rem" }}>
              <h2 className="obs-section-title">Por CRAS (município)</h2>
              <div className="cras-table-wrap">
                <table className="cras-table">
                  <thead>
                    <tr>
                      <th>CRAS</th>
                      <th>Total</th>
                      <th>Cancelar</th>
                      <th>Bloquear</th>
                      <th>Suspender</th>
                      <th>Encerrar</th>
                      <th>Excluir</th>
                    </tr>
                  </thead>
                  <tbody>
                    {painel.por_cras!.map((c) => {
                      const byGrupo = Object.fromEntries(
                        c.top_grupos.map((g) => [g.grupo, g.familias_distintas]),
                      );
                      const label = c.nom_cras || c.num_cras || "—";
                      return (
                        <tr key={`${c.num_cras}-${c.nom_cras}`}>
                          <td>{label}</td>
                          <td>{c.familias_com_manutencao.toLocaleString("pt-BR")}</td>
                          <td>{(byGrupo.Cancelar ?? 0).toLocaleString("pt-BR")}</td>
                          <td>{(byGrupo.Bloquear ?? 0).toLocaleString("pt-BR")}</td>
                          <td>{(byGrupo.Suspender ?? 0).toLocaleString("pt-BR")}</td>
                          <td>{(byGrupo.Encerrar ?? 0).toLocaleString("pt-BR")}</td>
                          <td>{(byGrupo.Excluir ?? 0).toLocaleString("pt-BR")}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          <p className="obs-fonte" style={{ marginTop: "1rem" }}>
            Fonte: {painel.fonte} · Competência {fmtCompetencia(painel.competencia ?? "")}
          </p>
        </>
      )}
    </div>
  );
}
