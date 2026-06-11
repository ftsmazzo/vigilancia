import { useEffect, useState } from "react";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

type Props = {
  token: string;
};

type ManutAcaokpi = {
  acao: string;
  linhas: number;
  pct_linhas: number;
  familias_distintas: number;
  pct_familias: number;
};

type ManutGrupoCras = {
  grupo: string;
  familias_distintas: number;
  pct_sobre_manut_cras: number;
};

type ManutCrasKpi = {
  num_cras: string;
  nom_cras: string;
  familias_com_manutencao: number;
  top_grupos: ManutGrupoCras[];
};

type ManutencoesKpi = {
  competencia: string;
  total_acoes: number;
  familias_distintas: number;
  /** % das famílias com manutenção no mês sobre o total de famílias na folha Bolsa Família */
  pct_familias_manutencao_sobre_bolsa?: number;
  por_acao: ManutAcaokpi[];
  /** Manutenção × CADU com CRAS referenciado; cinco situações por unidade (fixas) */
  por_cras?: ManutCrasKpi[];
};

/** Ordem das colunas da tabela por CRAS (alinhada à API). */
const CRAS_MANUT_COLUNAS = ["Cancelar", "Bloquear", "Suspender", "Encerrar", "Excluir"] as const;

type VigilanciaKpis = {
  total_familias: number;
  total_pessoas: number;
  total_homens: number;
  pct_homens: number;
  total_mulheres: number;
  pct_mulheres: number;
  total_bolsa_familia: number;
  pct_bolsa_familia_cadu: number;
  tac_familias: number;
  tac_pct: number;
  total_pago_bolsa_familia: number;
  media_valor_bolsa_familia: number;
  renda_ate_218_familias: number;
  renda_ate_218_pct: number;
  renda_219_706_familias: number;
  renda_219_706_pct: number;
  renda_acima_706_familias: number;
  renda_acima_706_pct: number;
  total_bpc: number;
  total_bpc_idoso: number;
  pct_bpc_idoso: number;
  total_bpc_deficiente: number;
  pct_bpc_deficiente: number;
  manutencoes?: ManutencoesKpi;
};

const brl = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });

/** Formata competência AAAAMM para exibição MM/AAAA */
function competenciaLabel(comp: string): string {
  const s = (comp || "").trim();
  if (s.length === 6 && /^\d{6}$/.test(s)) {
    const mes = s.slice(4, 6);
    const ano = s.slice(0, 4);
    return `${mes}/${ano}`;
  }
  return s;
}

function pctManutencaoSobreBolsa(m: ManutencoesKpi | undefined, totalBolsa: number): number {
  if (m?.pct_familias_manutencao_sobre_bolsa != null) {
    return m.pct_familias_manutencao_sobre_bolsa;
  }
  if (!totalBolsa) return 0;
  return Math.round(((m?.familias_distintas ?? 0) / totalBolsa) * 10000) / 100;
}

/** Painel de KPIs exibido na página Início (dados Cadastro Único). */
export default function PainelIndicadoresInicio({ token }: Props) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [kpis, setKpis] = useState<VigilanciaKpis | null>(null);

  async function loadKpis() {
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_URL}/api/v1/vigilance/kpis`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = (await response.json().catch(() => ({}))) as VigilanciaKpis & { detail?: unknown };
      if (!response.ok) {
        const msg =
          typeof data.detail === "string"
            ? data.detail
            : Array.isArray(data.detail)
              ? JSON.stringify(data.detail)
              : "Falha ao carregar indicadores.";
        throw new Error(msg);
      }
      setKpis(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro inesperado ao consultar indicadores.");
      setKpis(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadKpis();
  }, []);

  return (
    <section className="kpi-page">
      <div className="kpi-head fx-card">
        <h1>Indicadores</h1>
        <p>Cadastro Único (CECAD) e folha Bolsa Família.</p>
        <button type="button" className="btn btn-secondary" onClick={() => void loadKpis()} disabled={loading}>
          {loading ? "Atualizando..." : "Atualizar indicadores"}
        </button>
      </div>

      {error && <p className="error">{error}</p>}

      {!error && kpis && (
        <>
          <h2 className="kpi-section-title">Famílias e Pessoas</h2>
          <div className="kpi-grid" aria-label="Indicadores do Cadastro Único">
            <article className="kpi-card">
              <small>Total de famílias</small>
              <strong>{kpis.total_familias.toLocaleString("pt-BR")}</strong>
              <span>Dados Cadastro Único — Família</span>
            </article>
            <article className="kpi-card">
              <small>Total de pessoas</small>
              <strong>{kpis.total_pessoas.toLocaleString("pt-BR")}</strong>
              <span>Dados Cadastro Único — Pessoa</span>
            </article>
            <article className="kpi-card">
              <small>Total de homens</small>
              <strong>{kpis.total_homens.toLocaleString("pt-BR")}</strong>
              <span>{kpis.pct_homens.toLocaleString("pt-BR")} % (Cadastro Único)</span>
            </article>
            <article className="kpi-card">
              <small>Total de mulheres</small>
              <strong>{kpis.total_mulheres.toLocaleString("pt-BR")}</strong>
              <span>{kpis.pct_mulheres.toLocaleString("pt-BR")} % (Cadastro Único)</span>
            </article>
          </div>

          <h2 className="kpi-section-title">Bolsa Família e TAC</h2>
          <div className="kpi-grid" aria-label="Bolsa Família e TAC">
            <article className="kpi-card">
              <small>Famílias na folha Bolsa Família</small>
              <strong>{kpis.total_bolsa_familia.toLocaleString("pt-BR")}</strong>
              <span>
                {kpis.pct_bolsa_familia_cadu.toLocaleString("pt-BR")} % das famílias no Cadastro Único
              </span>
            </article>
            <article className="kpi-card">
              <small>TAC</small>
              <strong>{kpis.tac_pct.toLocaleString("pt-BR")} %</strong>
              <span>{kpis.tac_familias.toLocaleString("pt-BR")} famílias</span>
            </article>
            <article className="kpi-card">
              <small>Total pago (Bolsa Família)</small>
              <strong>{brl.format(kpis.total_pago_bolsa_familia)}</strong>
              <span>Total na folha</span>
            </article>
            <article className="kpi-card">
              <small>Média por família na folha</small>
              <strong>{brl.format(kpis.media_valor_bolsa_familia)}</strong>
              <span>Média por família beneficiária</span>
            </article>
          </div>

          <h2 className="kpi-section-title">Renda Per Capita</h2>
          <div className="kpi-grid kpi-grid-3" aria-label="Faixas de renda per capita">
            <article className="kpi-card">
              <small>Renda per capita de 0,00 até 218</small>
              <strong>{kpis.renda_ate_218_familias.toLocaleString("pt-BR")}</strong>
              <span>{kpis.renda_ate_218_pct.toLocaleString("pt-BR")} % das famílias do Cadastro Único</span>
            </article>
            <article className="kpi-card">
              <small>Renda per capita de R$ 219 até R$ 810,50</small>
              <strong>{kpis.renda_219_706_familias.toLocaleString("pt-BR")}</strong>
              <span>{kpis.renda_219_706_pct.toLocaleString("pt-BR")} % das famílias do Cadastro Único (TAC ≤ 24 meses)</span>
            </article>
            <article className="kpi-card">
              <small>Renda per capita acima de R$ 810,50</small>
              <strong>{kpis.renda_acima_706_familias.toLocaleString("pt-BR")}</strong>
              <span>{kpis.renda_acima_706_pct.toLocaleString("pt-BR")} % das famílias do Cadastro Único</span>
            </article>
          </div>

          <h2 className="kpi-section-title">BPC (ativos)</h2>
          <div className="kpi-grid kpi-grid-3" aria-label="Indicadores de BPC">
            <article className="kpi-card">
              <small>Total de BPC ativos</small>
              <strong>{kpis.total_bpc.toLocaleString("pt-BR")}</strong>
              <span>Dados da folha BPC</span>
            </article>
            <article className="kpi-card">
              <small>BPC Idoso</small>
              <strong>{kpis.total_bpc_idoso.toLocaleString("pt-BR")}</strong>
              <span>{kpis.pct_bpc_idoso.toLocaleString("pt-BR")} % do total de BPC ativo</span>
            </article>
            <article className="kpi-card">
              <small>BPC Deficiente (inclui RMV)</small>
              <strong>{kpis.total_bpc_deficiente.toLocaleString("pt-BR")}</strong>
              <span>{kpis.pct_bpc_deficiente.toLocaleString("pt-BR")} % do total de BPC ativo</span>
            </article>
          </div>

          <h2 className="kpi-section-title">
            Manutenções SIBEC — competência {competenciaLabel(kpis.manutencoes?.competencia ?? "202603")}
          </h2>

          <h3 className="kpi-subsection-title">Manutenção × folha Bolsa Família</h3>
          <div className="kpi-grid kpi-grid-manut" aria-label="Famílias com manutenção sobre a folha Bolsa Família">
            <article className="kpi-card">
              <small>Famílias com manutenção no mês</small>
              <strong>{(kpis.manutencoes?.familias_distintas ?? 0).toLocaleString("pt-BR")}</strong>
              <span>
                {pctManutencaoSobreBolsa(kpis.manutencoes, kpis.total_bolsa_familia).toLocaleString("pt-BR")} % do total
                de famílias na folha Bolsa Família (
                {kpis.total_bolsa_familia.toLocaleString("pt-BR")} famílias)
              </span>
            </article>
          </div>

          <h3 className="kpi-subsection-title">
            Por tipo de ação — % sobre famílias que tiveram manutenção
          </h3>
          <div className="kpi-grid kpi-grid-manut" aria-label="Famílias por tipo de manutenção">
            {(kpis.manutencoes?.por_acao ?? []).length === 0 ? (
              <p className="kpi-empty-manut">Nenhum registro de manutenção na competência.</p>
            ) : (
              (kpis.manutencoes?.por_acao ?? []).map((item) => (
                <article className="kpi-card" key={item.acao}>
                  <small>{item.acao}</small>
                  <strong>{item.familias_distintas.toLocaleString("pt-BR")}</strong>
                  <span>
                    {item.pct_familias.toLocaleString("pt-BR")} % das famílias com manutenção no mês
                  </span>
                </article>
              ))
            )}
          </div>

          <h3 className="kpi-subsection-title">Por CRAS (referência no CADU)</h3>
          <p className="kpi-hint-manut">
            Linhas: unidades territoriais (CRAS) com código ou nome no Cadastro Único. Colunas: total de famílias com
            manutenção no CRAS e distribuição pelas situações (famílias distintas; % sobre o total da linha). Uma família
            pode aparecer em mais de uma coluna.
          </p>
          {(kpis.manutencoes?.por_cras ?? []).length === 0 ? (
            <p className="kpi-empty-manut">
              Nenhum dado neste recorte (verifique manutenções na competência, vínculo com o CADU e referência de CRAS nas
              famílias).
            </p>
          ) : (
            <div className="kpi-table-wrap" aria-label="Tabela de manutenções por CRAS">
              <table className="kpi-table kpi-table-cras">
                <thead>
                  <tr>
                    <th scope="col" className="kpi-th-cras">
                      CRAS
                    </th>
                    <th scope="col" className="kpi-th-num">
                      Cód.
                    </th>
                    <th scope="col" className="kpi-th-kpi">
                      Famílias
                      <span className="kpi-th-sub">com manutenção</span>
                    </th>
                    {CRAS_MANUT_COLUNAS.map((titulo) => (
                      <th key={titulo} scope="col" className="kpi-th-situacao">
                        {titulo}
                        <span className="kpi-th-sub">fam. · % linha</span>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(kpis.manutencoes?.por_cras ?? []).map((c) => {
                    const porGrupo = Object.fromEntries(
                      (c.top_grupos ?? []).map((g) => [g.grupo, g] as const),
                    );
                    const label =
                      c.nom_cras?.trim() ||
                      (c.num_cras?.trim() ? `CRAS ${c.num_cras}` : "—");
                    return (
                      <tr key={`${c.num_cras}|${c.nom_cras}`}>
                        <th scope="row" className="kpi-td-cras">
                          {label}
                        </th>
                        <td className="kpi-td-num">{c.num_cras?.trim() || "—"}</td>
                        <td className="kpi-td-kpi">
                          <span className="kpi-cell-fam">
                            {c.familias_com_manutencao.toLocaleString("pt-BR")}
                          </span>
                        </td>
                        {CRAS_MANUT_COLUNAS.map((nome) => {
                          const g = porGrupo[nome];
                          const n = g?.familias_distintas ?? 0;
                          const p = g?.pct_sobre_manut_cras ?? 0;
                          return (
                            <td key={nome} className="kpi-td-situacao">
                              <span className="kpi-cell-fam">{n.toLocaleString("pt-BR")}</span>
                              <span className="kpi-cell-pct">{p.toLocaleString("pt-BR")} %</span>
                            </td>
                          );
                        })}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}
