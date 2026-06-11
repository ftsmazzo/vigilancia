import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import DonutChart from "../components/charts/DonutChart";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

type Props = {
  token: string;
};

type FaixaItem = {
  rotulo: string;
  titulo: string;
  total: number;
  pct: number;
};

type ObservatorioPainel = {
  total_familias: number;
  total_pessoas: number;
  total_bairros: number;
  total_cras: number;
  total_creas: number;
  creas_placeholder: boolean;
  por_cadastro_domicilio: FaixaItem[];
  por_cadastro_atualizado: FaixaItem[];
  por_meses_atualizacao: FaixaItem[];
  por_renda_per_capita: FaixaItem[];
  por_renda_per_capita_pos_pbf: FaixaItem[];
  por_renda_familiar: FaixaItem[];
};

function barPct(pct: number, maxPct: number): string {
  if (!maxPct) return "0%";
  return `${Math.min(100, (pct / maxPct) * 100)}%`;
}

function HBarList({
  items,
  fillPrefix,
}: {
  items: FaixaItem[];
  fillPrefix: string;
}) {
  const maxPct = Math.max(...items.map((x) => x.pct), 1);
  return (
    <ul className="home-hbar-list obs-mds-hbar">
      {items.map((item) => (
        <li key={item.rotulo} className="home-hbar-row">
          <span className="home-hbar-label">{item.titulo}</span>
          <span className="home-hbar-track">
            <span
              className={`home-hbar-fill ${fillPrefix}${item.rotulo}`}
              style={{ width: barPct(item.pct, maxPct) }}
            />
          </span>
          <span className="home-hbar-val">{item.total.toLocaleString("pt-BR")}</span>
        </li>
      ))}
    </ul>
  );
}

/** Segunda página — layout Observatório MDS (identificação, atualização e renda). */
export default function PainelObservatorioMds({ token }: Props) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [painel, setPainel] = useState<ObservatorioPainel | null>(null);

  async function loadPainel() {
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_URL}/api/v1/vigilance/observatorio-painel`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = (await response.json().catch(() => ({}))) as ObservatorioPainel & { detail?: unknown };
      if (!response.ok) {
        throw new Error(typeof data.detail === "string" ? data.detail : "Falha ao carregar painel.");
      }
      setPainel(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro inesperado.");
      setPainel(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadPainel();
  }, [token]);

  const domicilioSlices = (painel?.por_cadastro_domicilio ?? []).filter((x) => x.total > 0);
  const atualizadoSlices = (painel?.por_cadastro_atualizado ?? []).filter((x) => x.total > 0);

  return (
    <div className="home-obs-page obs-mds-page">
      <header className="home-obs-head fx-card">
        <div>
          <h1>Observatório — Identificação e renda</h1>
          <p>
            Espelho do painel MDS: cadastro em domicílio, atualização cadastral e distribuição de renda
            (pré e pós Bolsa Família).
          </p>
        </div>
        <div className="home-obs-actions">
          <button type="button" className="btn btn-secondary" onClick={() => void loadPainel()} disabled={loading}>
            {loading ? "Atualizando…" : "Atualizar"}
          </button>
          <Link to="/" className="btn btn-primary" style={{ textDecoration: "none" }}>
            Painel territorial
          </Link>
        </div>
      </header>

      {error && <p className="error">{error}</p>}

      {!error && painel && (
        <>
          <section className="home-obs-kpis obs-mds-kpis" aria-label="Indicadores principais">
            <article className="home-obs-kpi fx-card">
              <small>Famílias</small>
              <strong>{painel.total_familias.toLocaleString("pt-BR")}</strong>
            </article>
            <article className="home-obs-kpi fx-card">
              <small>Pessoas</small>
              <strong>{painel.total_pessoas.toLocaleString("pt-BR")}</strong>
            </article>
            <article className="home-obs-kpi fx-card">
              <small>Bairros</small>
              <strong>{painel.total_bairros.toLocaleString("pt-BR")}</strong>
            </article>
            <article className="home-obs-kpi fx-card">
              <small>CRAS</small>
              <strong>{painel.total_cras.toLocaleString("pt-BR")}</strong>
            </article>
            <article className="home-obs-kpi fx-card" title={painel.creas_placeholder ? "Valor provisório" : undefined}>
              <small>CREAS</small>
              <strong>{painel.total_creas.toLocaleString("pt-BR")}</strong>
              {painel.creas_placeholder && <span className="obs-mds-placeholder-tag">provisório</span>}
            </article>
          </section>

          <section className="obs-mds-row obs-mds-row--3">
            <DonutChart
              title="Famílias por cadastro em domicílio"
              items={domicilioSlices}
              centerLabel="famílias"
              centerValue={painel.total_familias.toLocaleString("pt-BR")}
            />
            <DonutChart
              title="Famílias por cadastro atualizado"
              subtitle="Atualização cadastral em até 24 meses"
              items={atualizadoSlices}
              centerLabel="famílias"
              centerValue={painel.total_familias.toLocaleString("pt-BR")}
            />
            <article className="home-obs-chart fx-card">
              <h2>Famílias por número de meses após atualização</h2>
              <HBarList items={painel.por_meses_atualizacao} fillPrefix="obs-mds-meses--" />
            </article>
          </section>

          <section className="obs-mds-row obs-mds-row--3">
            <article className="home-obs-chart fx-card">
              <h2>Famílias por faixa de renda per capita</h2>
              <HBarList items={painel.por_renda_per_capita} fillPrefix="obs-mds-renda-pc--" />
              <p className="obs-mds-footnote">Observação: Sem considerar o benefício do PBF.</p>
            </article>
            <article className="home-obs-chart fx-card">
              <h2>Famílias por faixa de renda per capita pós PBF</h2>
              <HBarList items={painel.por_renda_per_capita_pos_pbf} fillPrefix="obs-mds-renda-pc--" />
              <p className="obs-mds-footnote">Observação: Considera o benefício do PBF.</p>
            </article>
            <article className="home-obs-chart fx-card">
              <h2>Famílias por faixa de renda familiar</h2>
              <HBarList items={painel.por_renda_familiar} fillPrefix="obs-mds-renda-fam--" />
            </article>
          </section>
        </>
      )}
    </div>
  );
}
