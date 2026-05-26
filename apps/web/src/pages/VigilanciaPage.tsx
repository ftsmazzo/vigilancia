import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

type Props = {
  token: string;
};

type VigilanciaTab = "familia" | "domicilio" | "pessoas" | "sisc";

type SiscQualificacaoResponse = {
  status: string;
  row_count: number;
  nis_distintos: number;
  elapsed_ms: number;
};

type SiscKpisResumo = {
  disponivel: boolean;
  mensagem?: string;
  total_linhas?: number;
  nis_distintos?: number;
  vinculo_cadu?: { vinculados: number; sem_vinculo: number; pct_vinculados: number };
};

type FamiliaRefreshResponse = {
  status: string;
  view_schema: string;
  view_name: string;
  row_count: number;
  elapsed_ms: number;
  warnings: string[];
  pbf_columns_detected: {
    codigo_familiar: string | null;
    valor: string | null;
    referencia_folha: string | null;
  };
};

type DomicilioRefreshResponse = {
  status: string;
  view_schema: string;
  view_name: string;
  row_count: number;
  elapsed_ms: number;
  warnings: string[];
};

type PessoasRefreshResponse = {
  status: string;
  view_schema: string;
  view_name: string;
  row_count: number;
  elapsed_ms: number;
  warnings: string[];
};

export default function VigilanciaPage({ token }: Props) {
  const [tab, setTab] = useState<VigilanciaTab>("familia");
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState("");
  const [familiaResult, setFamiliaResult] = useState<FamiliaRefreshResponse | null>(null);
  const [domicilioResult, setDomicilioResult] = useState<DomicilioRefreshResponse | null>(null);
  const [pessoasResult, setPessoasResult] = useState<PessoasRefreshResponse | null>(null);
  const [siscResult, setSiscResult] = useState<SiscQualificacaoResponse | null>(null);
  const [siscKpis, setSiscKpis] = useState<SiscKpisResumo | null>(null);
  const [siscStatus, setSiscStatus] = useState("");
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  function startProgressAnimation() {
    setProgress(8);
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(() => {
      setProgress((p) => {
        if (p >= 92) return p;
        return p + Math.max(1, Math.round((92 - p) * 0.07));
      });
    }, 320);
  }

  function stopProgressAnimation(final: number) {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    setProgress(final);
  }

  async function refreshFamilia() {
    setError("");
    setFamiliaResult(null);
    setBusy(true);
    startProgressAnimation();
    try {
      const response = await fetch(`${API_URL}/api/v1/vigilance/materialized-views/familia/refresh`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = (await response.json().catch(() => ({}))) as FamiliaRefreshResponse & { detail?: unknown };
      if (!response.ok) {
        const msg =
          typeof data.detail === "string"
            ? data.detail
            : Array.isArray(data.detail)
              ? JSON.stringify(data.detail)
              : "Falha ao gerar a visão Família.";
        throw new Error(msg);
      }
      stopProgressAnimation(100);
      setFamiliaResult(data);
    } catch (e) {
      stopProgressAnimation(0);
      setError(e instanceof Error ? e.message : "Erro inesperado.");
    } finally {
      setBusy(false);
    }
  }

  async function refreshPessoas() {
    setError("");
    setPessoasResult(null);
    setBusy(true);
    startProgressAnimation();
    try {
      const response = await fetch(`${API_URL}/api/v1/vigilance/materialized-views/pessoas/refresh`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = (await response.json().catch(() => ({}))) as PessoasRefreshResponse & { detail?: unknown };
      if (!response.ok) {
        const msg =
          typeof data.detail === "string"
            ? data.detail
            : Array.isArray(data.detail)
              ? JSON.stringify(data.detail)
              : "Falha ao gerar a visão Pessoas.";
        throw new Error(msg);
      }
      stopProgressAnimation(100);
      setPessoasResult(data);
    } catch (e) {
      stopProgressAnimation(0);
      setError(e instanceof Error ? e.message : "Erro inesperado.");
    } finally {
      setBusy(false);
    }
  }

  async function loadSiscKpis() {
    try {
      const response = await fetch(`${API_URL}/api/v1/sisc/kpis`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = (await response.json().catch(() => ({}))) as SiscKpisResumo & { detail?: unknown };
      if (response.ok) setSiscKpis(data);
    } catch {
      /* resumo opcional */
    }
  }

  useEffect(() => {
    if (tab === "sisc") void loadSiscKpis();
  }, [tab, token]);

  async function refreshSiscQualificacao() {
    setError("");
    setSiscResult(null);
    setSiscStatus("");
    setBusy(true);
    startProgressAnimation();
    try {
      const response = await fetch(`${API_URL}/api/v1/sisc/qualificacao/refresh`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = (await response.json().catch(() => ({}))) as SiscQualificacaoResponse & { detail?: unknown };
      if (!response.ok) {
        const msg =
          typeof data.detail === "string"
            ? data.detail
            : Array.isArray(data.detail)
              ? JSON.stringify(data.detail)
              : "Falha ao qualificar SISC × CADU.";
        throw new Error(msg);
      }
      stopProgressAnimation(100);
      setSiscResult(data);
      setSiscStatus(
        `Qualificação vig.mvw_sisc_qualificado: ${data.row_count.toLocaleString("pt-BR")} linhas, ${data.nis_distintos.toLocaleString("pt-BR")} NIS distintos.`,
      );
      await loadSiscKpis();
    } catch (e) {
      stopProgressAnimation(0);
      setError(e instanceof Error ? e.message : "Erro inesperado.");
    } finally {
      setBusy(false);
    }
  }

  async function refreshDomicilio() {
    setError("");
    setDomicilioResult(null);
    setBusy(true);
    startProgressAnimation();
    try {
      const response = await fetch(`${API_URL}/api/v1/vigilance/materialized-views/familia-domicilio/refresh`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = (await response.json().catch(() => ({}))) as DomicilioRefreshResponse & { detail?: unknown };
      if (!response.ok) {
        const msg =
          typeof data.detail === "string"
            ? data.detail
            : Array.isArray(data.detail)
              ? JSON.stringify(data.detail)
              : "Falha ao gerar a visão Domicílio.";
        throw new Error(msg);
      }
      stopProgressAnimation(100);
      setDomicilioResult(data);
    } catch (e) {
      stopProgressAnimation(0);
      setError(e instanceof Error ? e.message : "Erro inesperado.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="ingestao-page">
      <aside className="ingestao-sidebar" aria-label="Visões analíticas">
        <div className="ingestao-sidebar-head">
          <h2>Dados vigilância</h2>
          <p className="ingestao-sidebar-sub">Views materializadas para análise</p>
        </div>
        <nav className="ingestao-nav">
          <button
            type="button"
            className={`ingestao-nav-item ${tab === "familia" ? "active" : ""}`}
            onClick={() => {
              setError("");
              setTab("familia");
            }}
          >
            <span className="ingestao-nav-label">Família</span>
            <span className="ingestao-nav-hint">CADU + folha Bolsa Família</span>
          </button>
          <button
            type="button"
            className={`ingestao-nav-item ${tab === "domicilio" ? "active" : ""}`}
            onClick={() => {
              setError("");
              setTab("domicilio");
            }}
          >
            <span className="ingestao-nav-label">Domicílio</span>
            <span className="ingestao-nav-hint">Moradia, riscos e GPTE (CADU)</span>
          </button>
          <button
            type="button"
            className={`ingestao-nav-item ${tab === "pessoas" ? "active" : ""}`}
            onClick={() => {
              setError("");
              setTab("pessoas");
            }}
          >
            <span className="ingestao-nav-label">Pessoas</span>
            <span className="ingestao-nav-hint">Membros, NIS, escolaridade (CADU)</span>
          </button>
          <button
            type="button"
            className={`ingestao-nav-item ${tab === "sisc" ? "active" : ""}`}
            onClick={() => {
              setError("");
              setTab("sisc");
            }}
          >
            <span className="ingestao-nav-label">SISC Convivência</span>
            <span className="ingestao-nav-hint">Atendidos × CADU (NIS)</span>
          </button>
        </nav>
        <Link to="/" className="ingestao-back">
          ← Voltar ao painel
        </Link>
      </aside>

      <div className="ingestao-main-stack">
        <main className="ingestao-content">
          {tab === "familia" && (
            <section className="ingestao-panel">
              <h1>Visão materializada — Família</h1>
              <p className="ingestao-desc">
                Uma linha por código familiar (sem nomes de pessoas). A folha de pagamento só traz famílias que
                recebem benefício; o valor vem da coluna <strong>vlrtotal</strong> (soma por família). Use a ingestão
                com <strong>competência AAAAMM</strong>: a visão usa o mês mais recente gravado em{" "}
                <code className="inline-code">competencia</code> na RAW. <strong>marc_pbf</strong> é <em>true</em> se a
                família aparece nesse recorte. O indicador do CADU fica em <strong>marc_pbf_cadu</strong>. Tabela:{" "}
                <strong>vig.mvw_familia</strong>.
              </p>

              <div className="vig-actions">
                <button type="button" onClick={() => void refreshFamilia()} disabled={busy}>
                  {busy ? "Gerando visão…" : "Gerar / atualizar visão Família"}
                </button>
              </div>

              <div className="progress-wrap" aria-live="polite">
                <div className="progress-track">
                  <div className="progress-fill" style={{ width: `${progress}%` }} />
                </div>
                <small>
                  {busy
                    ? "Recriando materialized view no PostgreSQL…"
                    : progress === 100
                      ? "Concluído."
                      : "Aguardando comando."}
                </small>
              </div>

              {error && <p className="error">{error}</p>}

              {familiaResult && (
                <div className="vig-result">
                  <p className="status-ok" style={{ marginTop: "0.75rem" }}>
                    Visão <code className="inline-code">vig.{familiaResult.view_name}</code> atualizada:{" "}
                    <strong>{familiaResult.row_count.toLocaleString("pt-BR")}</strong> famílias em{" "}
                    {(familiaResult.elapsed_ms / 1000).toLocaleString("pt-BR", {
                      minimumFractionDigits: 1,
                      maximumFractionDigits: 1,
                    })}
                    s.
                  </p>
                  {familiaResult.warnings.length > 0 && (
                    <ul className="vig-warnings">
                      {familiaResult.warnings.map((w) => (
                        <li key={w}>{w}</li>
                      ))}
                    </ul>
                  )}
                  <p className="ingestao-desc" style={{ marginBottom: 0 }}>
                    Colunas detectadas na folha PBF: código{" "}
                    <code className="inline-code">{familiaResult.pbf_columns_detected.codigo_familiar ?? "—"}</code>,
                    valor <code className="inline-code">{familiaResult.pbf_columns_detected.valor ?? "—"}</code>,
                    referência{" "}
                    <code className="inline-code">{familiaResult.pbf_columns_detected.referencia_folha ?? "—"}</code>.
                  </p>
                </div>
              )}
            </section>
          )}

          {tab === "domicilio" && (
            <section className="ingestao-panel">
              <h1>Visão materializada — Domicílio</h1>
              <p className="ingestao-desc">
                Uma linha por <strong>codigo_familiar</strong>, só a partir do <code className="inline-code">
                  raw.cecad__cadu
                </code>
                : situação do domicílio, materiais, saneamento, indígena/quilombola, CRAS, riscos (violência de direitos,
                insegurança alimentar) e GPTE. <strong>total_pessoas</strong> é a contagem de CPFs distintos (11
                dígitos) entre as linhas da mesma família. Tabela: <strong>vig.mvw_familia_domicilio</strong>. Atualize
                quando recarregar o CADU.
              </p>

              <div className="vig-actions">
                <button type="button" onClick={() => void refreshDomicilio()} disabled={busy}>
                  {busy ? "Gerando visão…" : "Gerar / atualizar visão Domicílio"}
                </button>
              </div>

              <div className="progress-wrap" aria-live="polite">
                <div className="progress-track">
                  <div className="progress-fill" style={{ width: `${progress}%` }} />
                </div>
                <small>
                  {busy
                    ? "Recriando materialized view no PostgreSQL…"
                    : progress === 100
                      ? "Concluído."
                      : "Aguardando comando."}
                </small>
              </div>

              {error && <p className="error">{error}</p>}

              {domicilioResult && (
                <div className="vig-result">
                  <p className="status-ok" style={{ marginTop: "0.75rem" }}>
                    Visão <code className="inline-code">vig.{domicilioResult.view_name}</code> atualizada:{" "}
                    <strong>{domicilioResult.row_count.toLocaleString("pt-BR")}</strong> famílias em{" "}
                    {(domicilioResult.elapsed_ms / 1000).toLocaleString("pt-BR", {
                      minimumFractionDigits: 1,
                      maximumFractionDigits: 1,
                    })}
                    s.
                  </p>
                  {domicilioResult.warnings.length > 0 && (
                    <ul className="vig-warnings">
                      {domicilioResult.warnings.map((w) => (
                        <li key={w}>{w}</li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </section>
          )}

          {tab === "pessoas" && (
            <section className="ingestao-panel">
              <h1>Visão materializada — Pessoas</h1>
              <p className="ingestao-desc">
                <strong>Todas as linhas</strong> de <code className="inline-code">raw.cecad__cadu</code> (uma por membro
                no arquivo “tudo”), com nomes de campos simplificados e sanitização. O <strong>CPF</strong> (
                <code className="inline-code">num_cpf</code>) é normalizado só com dígitos e preenchido com zeros à
                esquerda até 11 posições quando a exportação cortou zeros. O <strong>NIS</strong> (
                <code className="inline-code">num_nis</code>) é normalizado com 11 dígitos — chave para cruzar com o{" "}
                <Link to="/vigilancia" onClick={() => setTab("sisc")}>
                  SISC Convivência
                </Link>
                . <strong>idade</strong> é calculada em anos completos a partir de{" "}
                <code className="inline-code">data_nascimento</code>. Tabela: <strong>vig.mvw_pessoas</strong>.
              </p>

              <div className="vig-actions">
                <button type="button" onClick={() => void refreshPessoas()} disabled={busy}>
                  {busy ? "Gerando visão…" : "Gerar / atualizar visão Pessoas"}
                </button>
              </div>

              <div className="progress-wrap" aria-live="polite">
                <div className="progress-track">
                  <div className="progress-fill" style={{ width: `${progress}%` }} />
                </div>
                <small>
                  {busy
                    ? "Recriando materialized view no PostgreSQL…"
                    : progress === 100
                      ? "Concluído."
                      : "Aguardando comando."}
                </small>
              </div>

              {error && <p className="error">{error}</p>}

              {pessoasResult && (
                <div className="vig-result">
                  <p className="status-ok" style={{ marginTop: "0.75rem" }}>
                    Visão <code className="inline-code">vig.{pessoasResult.view_name}</code> atualizada:{" "}
                    <strong>{pessoasResult.row_count.toLocaleString("pt-BR")}</strong> registros em{" "}
                    {(pessoasResult.elapsed_ms / 1000).toLocaleString("pt-BR", {
                      minimumFractionDigits: 1,
                      maximumFractionDigits: 1,
                    })}
                    s.
                  </p>
                  {pessoasResult.warnings.length > 0 && (
                    <ul className="vig-warnings">
                      {pessoasResult.warnings.map((w) => (
                        <li key={w}>{w}</li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </section>
          )}

          {tab === "sisc" && (
            <section className="ingestao-panel">
              <h1>SISC — qualificação × CADU (NIS)</h1>
              <p className="ingestao-desc">
                Depois de ingerir o <code className="inline-code">SISC.csv</code> em{" "}
                <Link to="/ingestao">Ingestão</Link>, gere as visões <strong>Pessoas</strong> e{" "}
                <strong>Família</strong> (abas ao lado) e então clique abaixo para montar{" "}
                <code className="inline-code">vig.mvw_sisc_qualificado</code> e liberar os indicadores em tela.
              </p>

              <ol className="vig-steps" style={{ margin: "0 0 1rem", paddingLeft: "1.25rem", color: "var(--fx-muted)" }}>
                <li>Ingestão RAW → aba SISC Convivência</li>
                <li>
                  Aba <button type="button" className="link-button" onClick={() => setTab("pessoas")}>Pessoas</button> →
                  Gerar / atualizar visão
                </li>
                <li>
                  Aba <button type="button" className="link-button" onClick={() => setTab("familia")}>Família</button> →
                  Gerar / atualizar visão
                </li>
                <li>Botão abaixo → qualificar e ver resumo (gráficos completos em Convivência)</li>
              </ol>

              <div className="vig-actions" style={{ flexWrap: "wrap", gap: "0.5rem" }}>
                <button type="button" className="btn btn-primary" onClick={() => void refreshSiscQualificacao()} disabled={busy}>
                  {busy ? "Qualificando…" : "Qualificar atendidos SISC × CADU"}
                </button>
                <Link to="/convivencia" className="btn btn-secondary" style={{ textDecoration: "none" }}>
                  Abrir painel Convivência (gráficos)
                </Link>
              </div>

              <div className="progress-wrap" aria-live="polite">
                <div className="progress-track">
                  <div className="progress-fill" style={{ width: `${progress}%` }} />
                </div>
                <small>
                  {busy
                    ? "Cruzando NIS com mvw_pessoas e mvw_familia…"
                    : progress === 100
                      ? "Concluído."
                      : "Aguardando comando."}
                </small>
              </div>

              {error && <p className="error">{error}</p>}
              {siscStatus && <p className="status-ok">{siscStatus}</p>}

              {siscResult && (
                <div className="vig-result">
                  <p className="ingestao-desc" style={{ marginBottom: 0 }}>
                    Tempo: {(siscResult.elapsed_ms / 1000).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} s.
                    Tabela <code className="inline-code">vig.mvw_sisc_qualificado</code> pronta para consulta e KPIs.
                  </p>
                </div>
              )}

              {siscKpis?.disponivel && (
                <div className="kpi-grid" style={{ marginTop: "1.25rem" }}>
                  <article className="kpi-card">
                    <small>Atendimentos SISC</small>
                    <strong>{(siscKpis.total_linhas ?? 0).toLocaleString("pt-BR")}</strong>
                    <span>{(siscKpis.nis_distintos ?? 0).toLocaleString("pt-BR")} NIS distintos</span>
                  </article>
                  <article className="kpi-card kpi-card--accent">
                    <small>Vinculados ao CADU</small>
                    <strong>{(siscKpis.vinculo_cadu?.vinculados ?? 0).toLocaleString("pt-BR")}</strong>
                    <span>{(siscKpis.vinculo_cadu?.pct_vinculados ?? 0).toLocaleString("pt-BR")}%</span>
                  </article>
                  <article className="kpi-card">
                    <small>Sem vínculo (NIS)</small>
                    <strong>{(siscKpis.vinculo_cadu?.sem_vinculo ?? 0).toLocaleString("pt-BR")}</strong>
                    <span>Não encontrados em Pessoas</span>
                  </article>
                </div>
              )}

              {siscKpis && !siscKpis.disponivel && (
                <p className="ingestao-desc" style={{ marginTop: "1rem" }}>
                  {siscKpis.mensagem ?? "Ainda não há qualificação. Use o botão acima."}
                </p>
              )}
            </section>
          )}
        </main>
      </div>
    </div>
  );
}
