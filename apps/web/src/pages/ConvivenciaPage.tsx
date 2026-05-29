import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";
/** Se esta versão não aparecer no rodapé da página, o frontend em produção está desatualizado (rebuild + Ctrl+F5). */
const PAINEL_UI_VERSAO = 2;

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
  masculino: "Masculino",
  feminino: "Feminino",
  nao_informado: "Não informado",
  branca: "Branca",
  preta: "Preta",
  amarela: "Amarela",
  parda: "Parda",
  indigena: "Indígena",
  outro_codigo: "Outro código",
  analfabeto: "Analfabeto",
  fundamental_incompleto: "Fundamental incompleto",
  fundamental_completo: "Fundamental completo",
  medio_incompleto: "Médio incompleto",
  medio_completo: "Médio completo",
  superior_incompleto: "Superior incompleto",
  superior_completo: "Superior completo",
  crianca_0_11: "0–11 anos",
  adolescente_12_17: "12–17 anos",
  adulto_18_59: "18–59 anos",
  idoso_60_mais: "60 anos ou mais",
  idade_nao_informada: "Idade não informada",
  sem_deficiencia: "Sem deficiência",
  deficiencia_fisica: "Deficiência física",
  deficiencia_visual: "Deficiência visual",
  deficiencia_auditiva: "Deficiência auditiva",
  deficiencia_mental_cognitiva: "Deficiência mental / cognitiva",
  deficiencia_multipla: "Deficiência múltipla",
  com_deficiencia_sem_tipo: "Com deficiência (tipo não detalhado)",
  intergeracional_sim: "Intergeracional (sim)",
  intergeracional_nao: "Intergeracional (não)",
  intergeracional_nao_informado: "Intergeracional (não informado)",
  frequenta_escola_sim: "Frequenta escola",
  frequenta_escola_nao: "Não frequenta escola",
  frequenta_escola_nao_informado: "Frequenta escola (não informado)",
};

function rotuloAmigavel(chave: string): string {
  return ROTULO_AMIGAVEL[chave] ?? chave.replace(/_/g, " ");
}

type SiscKpis = {
  disponivel: boolean;
  painel_versao_api?: number;
  painel_versao_ui_esperada?: number;
  painel_versao_dados?: number;
  precisa_requalificar?: boolean;
  aviso_layout?: string;
  mensagem?: string;
  total_linhas?: number;
  nis_distintos?: number;
  vinculo_cadu?: { vinculados: number; sem_vinculo: number; pct_vinculados: number };
  prioritarios?: number;
  com_bolsa_familia?: number;
  renda_ate_218?: number;
  mulheres?: number;
  homens?: number;
  pct_mulheres?: number;
  pct_homens?: number;
  com_deficiencia?: number;
  situacao_rua?: number;
  idosos_60?: number;
  por_vinculo?: BarItem[];
  por_classificacao_social?: BarItem[];
  por_grupo?: BarItem[];
  por_cras?: BarItem[];
  por_faixa_etaria?: BarItem[];
  por_sexo?: BarItem[];
  por_raca?: BarItem[];
  por_escolaridade?: BarItem[];
  por_faixa_idade_cadu?: BarItem[];
  por_deficiencia?: BarItem[];
  por_atendimento?: BarItem[];
  por_intergeracional?: BarItem[];
  por_frequenta_escola?: BarItem[];
};

import BarChartPanel from "../components/charts/BarChartPanel";

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
        `Qualificação atualizada: ${String(data.row_count ?? 0)} linhas, ${String(data.nis_distintos ?? 0)} NIS distintos (${String(data.elapsed_ms ?? 0)} ms). Requalifique após cada atualização das visões Pessoas/Família.`
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
  const apiOk = (kpis?.painel_versao_api ?? 0) >= PAINEL_UI_VERSAO;
  const dadosOk = (kpis?.painel_versao_dados ?? 0) >= PAINEL_UI_VERSAO;
  const painelRico = dadosOk && Array.isArray(kpis?.por_sexo) && (kpis.por_sexo?.length ?? 0) > 0;

  return (
    <section className="kpi-page convivencia-page">
      <div className="kpi-head fx-card">
        <h1>SISC — Serviço de Convivência</h1>
        <p className="convivencia-versao" aria-live="polite">
          Interface v{PAINEL_UI_VERSAO}
          {kpis?.painel_versao_api != null && (
            <>
              {" "}
              · API v{kpis.painel_versao_api}
              {kpis.painel_versao_dados != null && <> · dados qualificados v{kpis.painel_versao_dados}</>}
            </>
          )}
        </p>
        <p>
          Painel enriquecido com dados do Cadastro Único (sexo, raça, escolaridade, deficiência, renda, situação de
          rua). Chave de vínculo: <strong>NIS</strong>. Ingestão em <Link to="/ingestao">Ingestão RAW</Link>; visões em{" "}
          <Link to="/vigilancia">Vigilância</Link>.
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

      {kpis && kpis.disponivel && !apiOk && (
        <div className="convivencia-alerta convivencia-alerta--erro fx-card">
          <strong>API desatualizada.</strong> O servidor ainda não tem o painel rico (v{PAINEL_UI_VERSAO}). Faça{" "}
          <strong>rebuild/restart do serviço da API</strong> no EasyPanel e tente de novo.
        </div>
      )}

      {kpis && kpis.disponivel && apiOk && (kpis.precisa_requalificar || !dadosOk) && (
        <div className="convivencia-alerta convivencia-alerta--aviso fx-card">
          <strong>Qualificação antiga no banco.</strong>{" "}
          {kpis.aviso_layout ??
            "Clique no botão azul «Qualificar atendidos (NIS × CADU)» nesta mesma página. Só gerar Pessoas/Família em Vigilância não atualiza sexo, raça, escolaridade nem deficiência."}
        </div>
      )}

      {kpis && !kpis.disponivel && (
        <p className="ingestao-desc fx-card" style={{ padding: "1rem" }}>
          {kpis.mensagem}
        </p>
      )}

      {kpis?.disponivel && (
        <>
          {!painelRico && apiOk && dadosOk && (
            <p className="ingestao-desc fx-card" style={{ padding: "1rem" }}>
              Qualificação v{dadosOk ? kpis.painel_versao_dados : "?"} ativa, mas os gráficos demográficos ainda estão
              vazios (pode ser falta de vínculo NIS com o CADU). Confira os cards de vínculo abaixo.
            </p>
          )}

          <h2 className="kpi-section-title">Panorama geral</h2>
          <div className="kpi-grid">
            <article className="kpi-card">
              <small>Atendimentos (linhas SISC)</small>
              <strong>{(kpis.total_linhas ?? 0).toLocaleString("pt-BR")}</strong>
              <span>{(kpis.nis_distintos ?? 0).toLocaleString("pt-BR")} NIS distintos</span>
            </article>
            <article className="kpi-card kpi-card--accent">
              <small>Vinculados ao CADU</small>
              <strong>{(vinc?.vinculados ?? 0).toLocaleString("pt-BR")}</strong>
              <span>{(vinc?.pct_vinculados ?? 0).toLocaleString("pt-BR")}% do público SISC</span>
            </article>
            <article className="kpi-card">
              <small>Sem vínculo (NIS)</small>
              <strong>{(vinc?.sem_vinculo ?? 0).toLocaleString("pt-BR")}</strong>
              <span>Não encontrados em Pessoas</span>
            </article>
            <article className="kpi-card">
              <small>Prioritários (SISC)</small>
              <strong>{(kpis.prioritarios ?? 0).toLocaleString("pt-BR")}</strong>
              <span>Situação prioritária no relatório</span>
            </article>
            <article className="kpi-card">
              <small>Folha Bolsa Família</small>
              <strong>{(kpis.com_bolsa_familia ?? 0).toLocaleString("pt-BR")}</strong>
              <span>Família na folha PBF</span>
            </article>
            <article className="kpi-card">
              <small>Renda per capita ≤ R$ 218</small>
              <strong>{(kpis.renda_ate_218 ?? 0).toLocaleString("pt-BR")}</strong>
              <span>Extrema pobreza (CADU)</span>
            </article>
          </div>

          {dadosOk && (
            <>
          <h2 className="kpi-section-title">Perfil demográfico (vinculados ao CADU)</h2>
          <div className="kpi-grid kpi-grid-3">
            <article className="kpi-card">
              <small>Mulheres</small>
              <strong>{(kpis.mulheres ?? 0).toLocaleString("pt-BR")}</strong>
              <span>{(kpis.pct_mulheres ?? 0).toLocaleString("pt-BR")}% entre com sexo informado</span>
            </article>
            <article className="kpi-card">
              <small>Homens</small>
              <strong>{(kpis.homens ?? 0).toLocaleString("pt-BR")}</strong>
              <span>{(kpis.pct_homens ?? 0).toLocaleString("pt-BR")}% entre com sexo informado</span>
            </article>
            <article className="kpi-card">
              <small>60 anos ou mais (CADU)</small>
              <strong>{(kpis.idosos_60 ?? 0).toLocaleString("pt-BR")}</strong>
              <span>Idade calculada na visão Pessoas</span>
            </article>
            <article className="kpi-card kpi-card--warn">
              <small>Com deficiência (CADU)</small>
              <strong>{(kpis.com_deficiencia ?? 0).toLocaleString("pt-BR")}</strong>
              <span>Marcadores ou tipos de deficiência</span>
            </article>
            <article className="kpi-card kpi-card--warn">
              <small>Situação de rua (CADU)</small>
              <strong>{(kpis.situacao_rua ?? 0).toLocaleString("pt-BR")}</strong>
              <span>Marcador de situação de rua</span>
            </article>
          </div>

          <div className="chart-grid">
            <BarChartPanel
              title="Sexo"
              subtitle="Somente vinculados ao CADU"
              items={kpis.por_sexo ?? []}
              maxBars={6}
            />
            <BarChartPanel title="Raça / cor" subtitle="Códigos CadÚnico" items={kpis.por_raca ?? []} />
            <BarChartPanel title="Escolaridade" subtitle="Grau de instrução (CADU)" items={kpis.por_escolaridade ?? []} />
            <BarChartPanel title="Faixa etária (idade CADU)" items={kpis.por_faixa_idade_cadu ?? []} />
            <BarChartPanel title="Frequenta escola" items={kpis.por_frequenta_escola ?? []} maxBars={5} />
          </div>

          <h2 className="kpi-section-title">Deficiência e vulnerabilidades</h2>
          <div className="chart-grid">
            <BarChartPanel title="Tipo de deficiência" subtitle="Vinculados ao CADU" items={kpis.por_deficiencia ?? []} />
            <BarChartPanel title="Perfil social (família)" items={kpis.por_classificacao_social ?? []} />
            <BarChartPanel title="Vínculo com CADU" items={kpis.por_vinculo ?? []} maxBars={5} />
          </div>
            </>
          )}

          <h2 className="kpi-section-title">Serviço de convivência (SISC)</h2>
          <div className="chart-grid">
            <BarChartPanel title="Faixa etária (relatório SISC)" items={kpis.por_faixa_etaria ?? []} />
            <BarChartPanel title="Atendimento prioritário" items={kpis.por_atendimento ?? []} maxBars={5} />
            <BarChartPanel title="Intergeracional" items={kpis.por_intergeracional ?? []} maxBars={5} />
            <BarChartPanel title="Grupos / turmas" items={kpis.por_grupo ?? []} />
            <BarChartPanel title="Por CRAS" items={kpis.por_cras ?? []} maxBars={8} />
          </div>
        </>
      )}
    </section>
  );
}
