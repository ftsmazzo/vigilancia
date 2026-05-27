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
