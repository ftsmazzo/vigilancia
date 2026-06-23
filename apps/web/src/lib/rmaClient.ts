export type TipoEquip = "CRAS" | "CREAS" | "CENTRO_POP";

export type ResumoRow = {
  competencia: string;
  id_equipamento: string;
  tipo_equipamento: TipoEquip;
  nome_oficial: string;
  cras_num_territorial: number | null;
  creas_num_territorial: number | null;
  cras_familias_paif: number | null;
  cras_novas_familias_paif: number | null;
  cras_atend_individual: number | null;
  cras_visitas_domiciliares: number | null;
  creas_casos_paefi: number | null;
  creas_novos_casos_paefi: number | null;
  creas_atend_individual: number | null;
  creas_visitas_domiciliares: number | null;
  pop_pessoas_situacao_rua: number | null;
  pop_atendimentos_mes: number | null;
  pop_abordagens_pessoas: number | null;
  pop_total_abordagens: number | null;
};

export type MetricaDef = { chave: string; rotulo: string };

export type PainelRma = {
  disponivel: boolean;
  mensagem?: string;
  titulo_recorte?: string;
  resumo?: Record<string, number>;
  metricas?: MetricaDef[];
  ranking?: Array<{ rotulo: string; total: number; pct: number }>;
};

const METRICAS: Record<TipoEquip, MetricaDef[]> = {
  CRAS: [
    { chave: "cras_familias_paif", rotulo: "Famílias em acompanhamento PAIF" },
    { chave: "cras_novas_familias_paif", rotulo: "Novas famílias PAIF" },
    { chave: "cras_atend_individual", rotulo: "Atendimentos individuais" },
    { chave: "cras_visitas_domiciliares", rotulo: "Visitas domiciliares" },
  ],
  CREAS: [
    { chave: "creas_casos_paefi", rotulo: "Casos em acompanhamento PAEFI" },
    { chave: "creas_novos_casos_paefi", rotulo: "Novos casos PAEFI" },
    { chave: "creas_atend_individual", rotulo: "Atendimentos individuais" },
    { chave: "creas_visitas_domiciliares", rotulo: "Visitas domiciliares" },
  ],
  CENTRO_POP: [
    { chave: "pop_pessoas_situacao_rua", rotulo: "Pessoas em situação de rua" },
    { chave: "pop_atendimentos_mes", rotulo: "Atendimentos no mês" },
    { chave: "pop_abordagens_pessoas", rotulo: "Pessoas abordadas" },
    { chave: "pop_total_abordagens", rotulo: "Total de abordagens" },
  ],
};

const RANKING_FIELD: Record<TipoEquip, keyof ResumoRow> = {
  CRAS: "cras_atend_individual",
  CREAS: "creas_atend_individual",
  CENTRO_POP: "pop_atendimentos_mes",
};

export function compStr(value: string | Date): string {
  if (value instanceof Date) return value.toISOString().slice(0, 10);
  return String(value).slice(0, 10);
}

/** Primeiro dia do mês, N meses antes de competencia (inclusive). */
export function monthRangeStart(competencia: string, meses: number): string {
  const base = compStr(competencia);
  const [y, m] = base.slice(0, 7).split("-").map((v) => parseInt(v, 10));
  const d = new Date(Date.UTC(y, m - 1, 1));
  d.setUTCMonth(d.getUTCMonth() - (meses - 1));
  return d.toISOString().slice(0, 10);
}

function num(value: unknown): number {
  if (value == null) return 0;
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function pct(part: number, whole: number): number {
  if (whole <= 0) return 0;
  return Math.round((1000 * part) / whole) / 10;
}

export function rotuloEquipamentoRow(row: ResumoRow): string {
  const nome = row.nome_oficial || row.id_equipamento;
  if (row.tipo_equipamento === "CRAS" && row.cras_num_territorial != null) {
    return `CRAS ${row.cras_num_territorial} — ${nome}`;
  }
  if (row.tipo_equipamento === "CREAS" && row.creas_num_territorial != null) {
    return `CREAS ${row.creas_num_territorial} — ${nome}`;
  }
  return nome;
}

export function competenciasFromResumo(rows: ResumoRow[]): string[] {
  const set = new Set(rows.map((r) => compStr(r.competencia)));
  return [...set].sort((a, b) => b.localeCompare(a));
}

export function buildPainelFromResumo(
  rows: ResumoRow[],
  competencia: string,
  tipo: TipoEquip,
  idEquipamento: string | null,
): PainelRma {
  const comp = compStr(competencia);
  const monthRows = rows.filter((r) => compStr(r.competencia) === comp);

  if (rows.length === 0) {
    return {
      disponivel: false,
      mensagem: "Nenhum registro na visão RMA. Gere a visão na Ingestão → RMA SUAS.",
    };
  }
  if (monthRows.length === 0) {
    return {
      disponivel: false,
      mensagem: `Sem produção RMA para ${comp.slice(0, 7)} neste recorte.`,
    };
  }

  const metricas = METRICAS[tipo];
  const resumo: Record<string, number> = {};
  for (const m of metricas) {
    resumo[m.chave] = monthRows.reduce((acc, r) => acc + num(r[m.chave as keyof ResumoRow]), 0);
  }

  const rankingField = RANKING_FIELD[tipo];
  const rankingRaw = [...monthRows].sort((a, b) => num(b[rankingField]) - num(a[rankingField]));
  const totalRanking = rankingRaw.reduce((acc, r) => acc + num(r[rankingField]), 0);
  const ranking = rankingRaw
    .filter((r) => num(r[rankingField]) > 0)
    .map((r) => ({
      rotulo: rotuloEquipamentoRow(r),
      total: num(r[rankingField]),
      pct: pct(num(r[rankingField]), totalRanking),
    }));

  const titulo =
    idEquipamento && monthRows.length === 1
      ? rotuloEquipamentoRow(monthRows[0])
      : { CRAS: "Todos os CRAS", CREAS: "Todos os CREAS", CENTRO_POP: "Centro POP" }[tipo];

  return {
    disponivel: true,
    titulo_recorte: titulo,
    resumo,
    metricas,
    ranking,
  };
}

export function buildSerieFromResumo(
  rows: ResumoRow[],
  tipo: TipoEquip,
  meses = 24,
): Array<{ competencia: string; valor: number }> {
  const rankingField = RANKING_FIELD[tipo];
  const comps = competenciasFromResumo(rows).slice(0, meses).reverse();
  const porMes = new Map<string, number>();

  for (const row of rows) {
    const comp = compStr(row.competencia);
    porMes.set(comp, (porMes.get(comp) ?? 0) + num(row[rankingField]));
  }

  return comps.map((comp) => ({ competencia: comp, valor: porMes.get(comp) ?? 0 }));
}

export async function apiGetJson<T>(url: string, token: string, timeoutMs = 90_000): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let res: Response;
  try {
    res = await fetch(url, {
      headers: { Authorization: `Bearer ${token}` },
      signal: controller.signal,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new Error(
        "A consulta demorou demais e foi interrompida. O histórico RMA é grande — tente recarregar; se persistir, redeploy da API com a versão mais recente.",
      );
    }
    throw new Error(
      "Falha de rede ao consultar a API. Se as outras páginas funcionam, a consulta RMA provavelmente excedeu o tempo limite do proxy.",
    );
  } finally {
    clearTimeout(timer);
  }
  const data = (await res.json().catch(() => ({}))) as T & { detail?: unknown };
  if (!res.ok) {
    const detail = (data as { detail?: unknown }).detail;
    throw new Error(typeof detail === "string" ? detail : `Erro ${res.status} na API.`);
  }
  return data;
}
