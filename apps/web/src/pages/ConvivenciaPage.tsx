import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

type Props = {
  token: string;
};

type BarItem = {
  rotulo: string;
  total: number;
  pct: number;
};

const ROTULO_AMIGAVEL: Record<string, string> = {
  vinculado_cadu: "Vinculado ao CADU",
  sem_vinculo_cadu: "Sem vínculo no CADU",
  nao_localizado_cadu: "Não localizado",
  cadu_com_bolsa_familia: "CADU + folha PBF",
  cadu_marcador_pbf: "CADU com marcador PBF",
  cadu_renda_ate_218: "Renda per capita ≤ R$ 218",
  cadu_renda_219_706: "Renda R$ 219–706",
  cadu_renda_acima_706: "Renda acima de R$ 706",
  cadu_sem_indicador_renda: "CADU sem renda informada",
  prioritario: "Prioritário (SISC)",
  regular: "Regular (SISC)",
};

function rotuloAmigavel(chave: string): string {
  return ROTULO_AMIGAVEL[chave] ?? chave.replace(/_/g, " ");
}

type SiscKpis = {
  disponivel: boolean;
  mensagem?: string;
  total_linhas?: number;
  nis_distintos?: number;
  vinculo_cadu?: { vinculados: number; sem_vinculo: number; pct_vinculados: number };
  prioritarios?: number;
  com_bolsa_familia?: number;
  renda_ate_218?: number;
  por_vinculo?: BarItem[];
  por_classificacao_social?: BarItem[];
  por_grupo?: BarItem[];
  por_cras?: BarItem[];
  por_faixa_etaria?: BarItem[];
};

function BarChart({ title, items, maxBars = 10 }: { title: string; items: BarItem[]; maxBars?: number }) {
  const slice = items.slice(0, maxBars);
  const max = Math.max(...slice.map((i) => i.total), 1);
  return (
    <div className="chart-panel fx-card">
      <h3 className="chart-panel-title">{title}</h3>
      {slice.length === 0 ? (
        <p className="ingestao-desc">Sem dados.</p>
      ) : (
        <ul className="chart-bars" aria-label={title}>
          {slice.map((item) => (
            <li key={item.rotulo} className="chart-bar-row">
              <span className="chart-bar-label" title={item.rotulo}>
                {rotuloAmigavel(item.rotulo)}
              </span>
              <div className="chart-bar-track">
                <div
                  className="chart-bar-fill"
                  style={{ width: `${Math.max(4, (item.total / max) * 100)}%` }}
                />
              </div>
              <span className="chart-bar-value">
                {item.total.toLocaleString("pt-BR")}{" "}
                <small>({item.pct.toLocaleString("pt-BR")}%)</small>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function ConvivenciaPage({ token }: Props) {
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [kpis, setKpis] = useState<SiscKpis | null>(null);

  async function loadKpis() {
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`${API_URL}/api/v1/sisc/kpis`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = (await res.json().catch(() => ({}))) as SiscKpis & { detail?: unknown };
      if (!res.ok) {
        throw new Error(typeof data.detail === "string" ? data.detail : "Falha ao carregar indicadores SISC.");
      }
      setKpis(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao consultar SISC.");
      setKpis(null);
    } finally {
      setLoading(false);
    }
  }

  async function refreshQualificacao() {
    setRefreshing(true);
    setStatus("");
    setError("");
    try {
      const res = await fetch(`${API_URL}/api/v1/sisc/qualificacao/refresh`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = (await res.json().catch(() => ({}))) as Record<string, unknown> & { detail?: unknown };
      if (!res.ok) {
        throw new Error(typeof data.detail === "string" ? data.detail : "Falha ao qualificar SISC.");
      }
      setStatus(
        `Qualificação atualizada: ${String(data.row_count ?? 0)} linhas, ${String(data.nis_distintos ?? 0)} NIS distintos (${String(data.elapsed_ms ?? 0)} ms).`
      );
      await loadKpis();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro na qualificação.");
    } finally {
      setRefreshing(false);
    }
  }

  useEffect(() => {
    void loadKpis();
  }, [token]);

  const vinc = kpis?.vinculo_cadu;

  return (
    <section className="kpi-page convivencia-page">
      <div className="kpi-head fx-card">
        <h1>SISC — Serviço de Convivência</h1>
        <p>
          Atendidos vinculados ao Cadastro Único pela chave <strong>NIS</strong>. Ingestão em{" "}
          <Link to="/ingestao">Ingestão RAW</Link>; visões CADU em{" "}
          <Link to="/vigilancia">Vigilância</Link> (Família e Pessoas).
        </p>
        <div className="vig-actions" style={{ flexWrap: "wrap", gap: "0.5rem" }}>
          <button type="button" className="btn btn-secondary" onClick={() => void loadKpis()} disabled={loading}>
            {loading ? "Atualizando…" : "Atualizar indicadores"}
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => void refreshQualificacao()}
            disabled={refreshing || loading}
          >
            {refreshing ? "Qualificando…" : "Qualificar atendidos (NIS × CADU)"}
          </button>
        </div>
      </div>

      {error && <p className="error">{error}</p>}
      {status && <p className="status-ok">{status}</p>}

      {kpis && !kpis.disponivel && (
        <p className="ingestao-desc fx-card" style={{ padding: "1rem" }}>
          {kpis.mensagem}
        </p>
      )}

      {kpis?.disponivel && (
        <>
          <h2 className="kpi-section-title">Panorama</h2>
          <div className="kpi-grid">
            <article className="kpi-card">
              <small>Atendimentos (linhas SISC)</small>
              <strong>{(kpis.total_linhas ?? 0).toLocaleString("pt-BR")}</strong>
              <span>{(kpis.nis_distintos ?? 0).toLocaleString("pt-BR")} NIS distintos</span>
            </article>
            <article className="kpi-card kpi-card--accent">
              <small>Vinculados ao CADU (NIS)</small>
              <strong>{(vinc?.vinculados ?? 0).toLocaleString("pt-BR")}</strong>
              <span>{(vinc?.pct_vinculados ?? 0).toLocaleString("pt-BR")}% do público SISC</span>
            </article>
            <article className="kpi-card">
              <small>Sem vínculo no CADU</small>
              <strong>{(vinc?.sem_vinculo ?? 0).toLocaleString("pt-BR")}</strong>
              <span>NIS não encontrado em vig.mvw_pessoas</span>
            </article>
            <article className="kpi-card">
              <small>Na folha Bolsa Família (família)</small>
              <strong>{(kpis.com_bolsa_familia ?? 0).toLocaleString("pt-BR")}</strong>
              <span>Entre os vinculados ao CADU</span>
            </article>
            <article className="kpi-card">
              <small>Renda per capita ≤ R$ 218</small>
              <strong>{(kpis.renda_ate_218 ?? 0).toLocaleString("pt-BR")}</strong>
              <span>Família no CADU (faixa extrema pobreza)</span>
            </article>
            <article className="kpi-card">
              <small>Situação prioritária (SISC)</small>
              <strong>{(kpis.prioritarios ?? 0).toLocaleString("pt-BR")}</strong>
              <span>Flag no relatório SISC</span>
            </article>
          </div>

          <h2 className="kpi-section-title">Classificação e distribuição</h2>
          <div className="chart-grid">
            <BarChart title="Vínculo com CADU" items={kpis.por_vinculo ?? []} maxBars={5} />
            <BarChart title="Perfil social (família CADU)" items={kpis.por_classificacao_social ?? []} />
            <BarChart title="Faixa etária (SISC)" items={kpis.por_faixa_etaria ?? []} />
            <BarChart title="Grupos / turmas" items={kpis.por_grupo ?? []} />
            <BarChart title="Por CRAS (unidade)" items={kpis.por_cras ?? []} maxBars={8} />
          </div>
        </>
      )}
    </section>
  );
}
