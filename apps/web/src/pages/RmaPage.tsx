import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import BarChartPanel, { type BarItem } from "../components/charts/BarChartPanel";
import LineChartPanel, { type LineChartPoint } from "../components/charts/LineChartPanel";
import {
  apiGetJson,
  buildPainelFromResumo,
  buildSerieFromResumo,
  competenciasFromResumo,
  monthRangeStart,
  type PainelRma,
  type ResumoRow,
  type TipoEquip,
} from "../lib/rmaClient";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

type Props = {
  token: string;
};

type Equipamento = {
  id_equipamento: string;
  tipo_equipamento: string;
  nome_oficial: string;
  cras_num_territorial: number | null;
  creas_num_territorial: number | null;
};

type ComparativoItem = {
  cras_num_territorial: number;
  nome_oficial: string;
  cras_familias_paif: number | null;
  cras_atend_individual: number | null;
  cras_visitas_domiciliares: number | null;
  familias_cadu_territorio: number;
  razao_atendimentos_por_familia_cadu: number | null;
};

function fmtCompetencia(comp: string): string {
  if (comp.length >= 7 && comp[4] === "-") {
    const [ano, mes] = comp.slice(0, 7).split("-");
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
  return comp;
}

function rotuloEquipamento(e: Equipamento): string {
  if (e.tipo_equipamento === "CRAS" && e.cras_num_territorial != null) {
    return `CRAS ${e.cras_num_territorial} — ${e.nome_oficial}`;
  }
  if (e.tipo_equipamento === "CREAS" && e.creas_num_territorial != null) {
    return `CREAS ${e.creas_num_territorial} — ${e.nome_oficial}`;
  }
  return e.nome_oficial;
}

async function fetchResumo(
  token: string,
  tipo: TipoEquip,
  idEquipamento: string | null,
  range: { desde: string; ate: string },
): Promise<ResumoRow[]> {
  const params = new URLSearchParams({
    tipo_equipamento: tipo,
    desde: range.desde,
    ate: range.ate,
  });
  if (idEquipamento) params.set("id_equipamento", idEquipamento);
  const data = await apiGetJson<{ items: ResumoRow[] }>(
    `${API_URL}/api/v1/rma/resumo?${params}`,
    token,
  );
  return data.items ?? [];
}

export default function RmaPage({ token }: Props) {
  const [aba, setAba] = useState<"producao" | "comparativo">("producao");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [competencias, setCompetencias] = useState<string[]>([]);
  const [competencia, setCompetencia] = useState("");
  const [tipo, setTipo] = useState<TipoEquip>("CRAS");
  const [idEquipamento, setIdEquipamento] = useState("__todos__");
  const [equipamentos, setEquipamentos] = useState<Equipamento[]>([]);
  const [painel, setPainel] = useState<PainelRma | null>(null);
  const [serie, setSerie] = useState<Array<{ competencia: string; valor: number }>>([]);
  const [comparativo, setComparativo] = useState<ComparativoItem[]>([]);

  useEffect(() => {
    apiGetJson<{ items: Equipamento[] }>(`${API_URL}/api/v1/rma/equipamentos`, token)
      .then((data) => setEquipamentos(data.items ?? []))
      .catch(() => setEquipamentos([]));
  }, [token]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await apiGetJson<{ items: string[] }>(
          `${API_URL}/api/v1/rma/competencias`,
          token,
        );
        if (cancelled) return;
        const items = data.items ?? [];
        if (items.length > 0) {
          setCompetencias(items);
          setCompetencia((prev) => prev || items[0]);
          return;
        }
      } catch {
        /* fallback abaixo */
      }

      try {
        const ate = new Date().toISOString().slice(0, 10);
        const desde = monthRangeStart(ate, 48);
        const rows = await fetchResumo(token, "CRAS", null, { desde, ate });
        if (cancelled) return;
        const items = competenciasFromResumo(rows);
        setCompetencias(items);
        if (items.length > 0) setCompetencia((prev) => prev || items[0]);
      } catch {
        if (!cancelled) setCompetencias([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  const equipamentosFiltrados = useMemo(
    () => equipamentos.filter((e) => e.tipo_equipamento === tipo),
    [equipamentos, tipo],
  );

  const loadProducao = useCallback(async () => {
    if (!competencia) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    const id = idEquipamento !== "__todos__" ? idEquipamento : null;
    const params = new URLSearchParams({ competencia, tipo_equipamento: tipo });
    if (id) params.set("id_equipamento", id);

    try {
      const painelData = await apiGetJson<PainelRma>(
        `${API_URL}/api/v1/rma/painel?${params}`,
        token,
      );
      setPainel(painelData);

      const serieParams = new URLSearchParams({ tipo_equipamento: tipo, meses: "24" });
      if (id) serieParams.set("id_equipamento", id);
      try {
        const serieData = await apiGetJson<{ items: Array<{ competencia: string; valor: number }> }>(
          `${API_URL}/api/v1/rma/serie?${serieParams}`,
          token,
        );
        setSerie(serieData.items ?? []);
      } catch {
        const desde = monthRangeStart(competencia, 24);
        const serieRows = await fetchResumo(token, tipo, id, { desde, ate: competencia });
        setSerie(buildSerieFromResumo(serieRows, tipo));
      }
    } catch {
      try {
        const monthRows = await fetchResumo(token, tipo, id, {
          desde: competencia,
          ate: competencia,
        });
        setPainel(buildPainelFromResumo(monthRows, competencia, tipo, id));
        const desde = monthRangeStart(competencia, 24);
        const serieRows = await fetchResumo(token, tipo, id, { desde, ate: competencia });
        setSerie(buildSerieFromResumo(serieRows, tipo));
      } catch (e) {
        setError(e instanceof Error ? e.message : "Erro inesperado.");
        setPainel(null);
        setSerie([]);
      }
    } finally {
      setLoading(false);
    }
  }, [token, competencia, tipo, idEquipamento]);

  const loadComparativo = useCallback(async () => {
    if (!competencia) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({ competencia });
      const data = await apiGetJson<{ items: ComparativoItem[] }>(
        `${API_URL}/api/v1/rma/comparativo/cras-demanda?${params}`,
        token,
      );
      setComparativo(data.items ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro inesperado.");
      setComparativo([]);
    } finally {
      setLoading(false);
    }
  }, [token, competencia]);

  useEffect(() => {
    if (aba === "producao") void loadProducao();
    else void loadComparativo();
  }, [aba, loadProducao, loadComparativo]);

  const serieLinha: LineChartPoint[] = useMemo(
    () =>
      serie.map((s) => ({
        rotulo: fmtCompetencia(s.competencia),
        valor: Number(s.valor) || 0,
      })),
    [serie],
  );

  const rankingBarras: BarItem[] = useMemo(
    () =>
      (painel?.ranking ?? []).map((r) => ({
        rotulo: r.rotulo,
        total: r.total,
        pct: r.pct,
      })),
    [painel],
  );

  const comparativoBarras: BarItem[] = useMemo(() => {
    const total = comparativo.reduce((acc, c) => acc + (c.cras_atend_individual ?? 0), 0);
    return comparativo
      .filter((c) => (c.cras_atend_individual ?? 0) > 0)
      .map((c) => ({
        rotulo: `CRAS ${c.cras_num_territorial}`,
        total: c.cras_atend_individual ?? 0,
        pct: total > 0 ? Math.round((1000 * (c.cras_atend_individual ?? 0)) / total) / 10 : 0,
      }));
  }, [comparativo]);

  const tituloSerie =
    tipo === "CRAS"
      ? "Evolução — atendimentos individuais"
      : tipo === "CREAS"
        ? "Evolução — atendimentos individuais (CREAS)"
        : "Evolução — atendimentos no mês (Centro POP)";

  return (
    <div className="ivs-page sibec-page rma-page">
      <header className="ivs-hero fx-card">
        <div>
          <h1>Produção SUAS (RMA)</h1>
          <p className="ivs-hero-sub">
            Relatório Mensal de Atendimento — produção operacional por CRAS, CREAS e Centro POP, com ids oficiais SUAS.
          </p>
        </div>
        <div className="ivs-hero-actions">
          <Link to="/ingestao" className="btn btn-primary" style={{ textDecoration: "none" }}>
            Ingestão RMA
          </Link>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => void (aba === "producao" ? loadProducao() : loadComparativo())}
            disabled={loading}
          >
            {loading ? "Carregando…" : "Recarregar"}
          </button>
        </div>
      </header>

      <div className="rma-tabs fx-card" role="tablist" aria-label="Seções RMA">
        <button
          type="button"
          role="tab"
          className={`rma-tab${aba === "producao" ? " active" : ""}`}
          aria-selected={aba === "producao"}
          onClick={() => setAba("producao")}
        >
          Produção mensal
        </button>
        <button
          type="button"
          role="tab"
          className={`rma-tab${aba === "comparativo" ? " active" : ""}`}
          aria-selected={aba === "comparativo"}
          onClick={() => setAba("comparativo")}
        >
          Carga × demanda (CRAS)
        </button>
      </div>

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
          {aba === "producao" && (
            <>
              <label>
                <span>Tipo de unidade</span>
                <select
                  className="cras-select"
                  value={tipo}
                  onChange={(e) => {
                    setTipo(e.target.value as TipoEquip);
                    setIdEquipamento("__todos__");
                  }}
                  disabled={loading}
                >
                  <option value="CRAS">CRAS</option>
                  <option value="CREAS">CREAS</option>
                  <option value="CENTRO_POP">Centro POP</option>
                </select>
              </label>
              <label>
                <span>Equipamento</span>
                <select
                  className="cras-select"
                  value={idEquipamento}
                  onChange={(e) => setIdEquipamento(e.target.value)}
                  disabled={loading}
                >
                  <option value="__todos__">
                    {tipo === "CRAS" ? "Todos os CRAS" : tipo === "CREAS" ? "Todos os CREAS" : "Centro POP"}
                  </option>
                  {equipamentosFiltrados.map((e) => (
                    <option key={e.id_equipamento} value={e.id_equipamento}>
                      {rotuloEquipamento(e)}
                    </option>
                  ))}
                </select>
              </label>
            </>
          )}
          <button
            type="button"
            className="btn btn-secondary caract-filtros-clear"
            onClick={() => {
              if (competencias.length > 0) setCompetencia(competencias[0]);
              setTipo("CRAS");
              setIdEquipamento("__todos__");
            }}
          >
            Limpar filtros
          </button>
        </div>
        {aba === "producao" && painel?.titulo_recorte && (
          <p className="caract-recorte-label">
            Exibindo: <strong>{painel.titulo_recorte}</strong>
            {competencia && (
              <>
                {" "}
                · <strong>{fmtCompetencia(competencia)}</strong>
              </>
            )}
          </p>
        )}
      </section>

      {!competencia && !loading && (
        <section className="fx-card" style={{ marginTop: "1rem", padding: "1.25rem" }}>
          <p>Nenhuma competência disponível. Gere a visão RMA na Ingestão antes de consultar este painel.</p>
        </section>
      )}

      {loading && <p className="caract-loading">Carregando…</p>}
      {error && <p className="error">{error}</p>}

      {!loading && aba === "producao" && painel && !painel.disponivel && (
        <section className="fx-card" style={{ marginTop: "1rem", padding: "1.25rem" }}>
          <p>{painel.mensagem}</p>
          <p style={{ marginTop: "0.75rem" }}>
            <Link to="/ingestao">Abrir Ingestão</Link> para carregar os CSVs e gerar a visão RMA.
          </p>
        </section>
      )}

      {!loading && aba === "producao" && painel?.disponivel && (
        <>
          <div className="kpi-grid" style={{ marginTop: "1rem" }}>
            {(painel.metricas ?? []).map((m) => (
              <article key={m.chave} className="kpi-card">
                <small>{m.rotulo}</small>
                <strong>{(painel.resumo?.[m.chave] ?? 0).toLocaleString("pt-BR")}</strong>
                <span>competência {fmtCompetencia(competencia)}</span>
              </article>
            ))}
          </div>

          {serie.length > 1 && (
            <div className="sibec-charts-row" style={{ marginTop: "1.25rem" }}>
              <LineChartPanel title={tituloSerie} items={serieLinha} color="#10b981" />
            </div>
          )}

          {rankingBarras.length > 0 && idEquipamento === "__todos__" && (
            <div className="obs-charts-grid" style={{ marginTop: "1.25rem" }}>
              <BarChartPanel
                title="Ranking por unidade"
                subtitle="Indicador principal do tipo selecionado"
                items={rankingBarras}
                accent="cool"
              />
            </div>
          )}
        </>
      )}

      {!loading && aba === "comparativo" && !error && (
        <>
          <p className="ingestao-desc" style={{ marginTop: "1rem" }}>
            Produção RMA (atendimentos individuais) comparada ao estoque de famílias no CADU por território CRAS — base
            para análise de carga de trabalho.
          </p>

          {comparativo.length === 0 ? (
            <section className="fx-card" style={{ marginTop: "1rem", padding: "1.25rem" }}>
              <p>Sem dados para esta competência. Verifique se a visão familiar (CADU) e o RMA estão atualizados.</p>
            </section>
          ) : (
            <>
              {comparativoBarras.length > 0 && (
                <div className="obs-charts-grid" style={{ marginTop: "1.25rem" }}>
                  <BarChartPanel
                    title="Atendimentos individuais por CRAS"
                    items={comparativoBarras}
                    accent="spectrum"
                  />
                </div>
              )}

              <section className="fx-card" style={{ marginTop: "1.25rem", padding: "1rem 1.25rem" }}>
                <h2 className="obs-section-title">Tabela comparativa</h2>
                <div className="cras-table-wrap">
                  <table className="cras-table sibec-cras-table">
                    <thead>
                      <tr>
                        <th>CRAS</th>
                        <th className="num">Famílias PAIF</th>
                        <th className="num">Atend. individuais</th>
                        <th className="num">Visitas dom.</th>
                        <th className="num">Famílias CADU</th>
                        <th className="num">Atend./família CADU</th>
                      </tr>
                    </thead>
                    <tbody>
                      {comparativo.map((row) => (
                        <tr key={row.cras_num_territorial}>
                          <td>
                            CRAS {row.cras_num_territorial}
                            <br />
                            <small>{row.nome_oficial}</small>
                          </td>
                          <td className="num">{(row.cras_familias_paif ?? 0).toLocaleString("pt-BR")}</td>
                          <td className="num">{(row.cras_atend_individual ?? 0).toLocaleString("pt-BR")}</td>
                          <td className="num">{(row.cras_visitas_domiciliares ?? 0).toLocaleString("pt-BR")}</td>
                          <td className="num">{row.familias_cadu_territorio.toLocaleString("pt-BR")}</td>
                          <td className="num">
                            {row.razao_atendimentos_por_familia_cadu != null
                              ? row.razao_atendimentos_por_familia_cadu.toLocaleString("pt-BR", {
                                  minimumFractionDigits: 2,
                                  maximumFractionDigits: 2,
                                })
                              : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            </>
          )}
        </>
      )}
    </div>
  );
}
