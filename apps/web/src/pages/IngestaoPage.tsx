import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

type TabId = "cadu" | "pbf" | "bpc" | "sibec" | "sisc" | "geo";

type UploadResult = { ok: boolean; data: Record<string, unknown>; errorText?: string };

function formatIngestionError(data: Record<string, unknown>): string {
  const detail = data.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => JSON.stringify(item)).join(" ");
  }
  return "Falha na ingestão. Confirme formato, dados e sessão.";
}

function runIngestionUpload(
  formData: FormData,
  token: string,
  onProgress: (pct: number) => void
): Promise<UploadResult> {
  return new Promise((resolve) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_URL}/api/v1/ingestion/import`);
    xhr.setRequestHeader("Authorization", `Bearer ${token}`);

    xhr.upload.onprogress = (ev) => {
      if (!ev.lengthComputable) return;
      onProgress(Math.round((ev.loaded / ev.total) * 100));
    };

    xhr.onload = () => {
      try {
        const data = xhr.responseText ? JSON.parse(xhr.responseText) : {};
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve({ ok: true, data });
        } else {
          resolve({ ok: false, data, errorText: formatIngestionError(data) });
        }
      } catch {
        resolve({ ok: false, data: {}, errorText: "Falha ao interpretar resposta do servidor." });
      }
    };

    xhr.onerror = () => {
      resolve({ ok: false, data: {}, errorText: "Erro de rede durante a ingestão." });
    };

    xhr.send(formData);
  });
}

type Props = {
  token: string;
};

type IngestionRunRow = {
  id: number;
  source: string;
  dataset: string;
  target_table: string;
  strategy: string;
  file_name: string;
  status: string;
  row_count: number;
  created_by_email: string;
  created_at: string;
  finished_at: string | null;
  error_message: string | null;
};

function formatRunDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

/** Rótulo amigável por tabela alvo (sem expor nomes RAW ao usuário). */
const TARGET_LABELS: Record<string, string> = {
  cecad__cadu: "CADU — Cadastro Único",
  sibec__programa_bolsa_familia: "Programa Bolsa Família",
  bpc__beneficio_prestacao_continuada: "BPC — Prestação Continuada",
  sibec__manutencoes: "SIBEC — Manutenções mensais",
  geo__tbl_geo: "Geo — logradouros (Ribeirão / CEP)",
  sisc__sisc: "SISC — Serviço de Convivência",
};

function humanBaseTitle(run: IngestionRunRow): string {
  return TARGET_LABELS[run.target_table] ?? prettySnakeCase(run.dataset);
}

function prettySnakeCase(s: string): string {
  return s
    .split(/_/g)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(" ");
}

function formatSourceLabel(source: string): string {
  const map: Record<string, string> = {
    cecad: "CECAD",
    sibec: "SIBEC",
    bpc: "BPC",
    sisc: "SISC",
    geo: "Geo",
  };
  return map[source.toLowerCase()] ?? source.toUpperCase();
}

function formatStrategyLabel(strategy: string): string {
  if (strategy === "replace") return "Substituição total";
  if (strategy === "append") return "Acrescentar dados";
  return strategy;
}

function formatStatusLabel(status: string): string {
  if (status === "success") return "Concluído";
  if (status === "failed" || status === "error") return "Falhou";
  if (status === "running" || status === "pending") return "Em andamento";
  return status;
}

function runStatusClass(status: string): string {
  if (status === "success") return "run-card-status--ok";
  if (status === "failed" || status === "error") return "run-card-status--bad";
  return "run-card-status--neutral";
}

/** Uma linha por tabela RAW: mantém só a execução mais recente de cada `target_table`. */
function latestRunPerBase(runs: IngestionRunRow[]): IngestionRunRow[] {
  const sorted = [...runs].sort((a, b) => {
    const ta = new Date(a.finished_at ?? a.created_at).getTime();
    const tb = new Date(b.finished_at ?? b.created_at).getTime();
    return tb - ta;
  });
  const seen = new Set<string>();
  const out: IngestionRunRow[] = [];
  for (const run of sorted) {
    const key = run.target_table;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(run);
  }
  return out.sort((a, b) => a.target_table.localeCompare(b.target_table, "pt-BR"));
}

export default function IngestaoPage({ token }: Props) {
  const [tab, setTab] = useState<TabId>("cadu");
  const [runs, setRuns] = useState<IngestionRunRow[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);
  const [runsError, setRunsError] = useState("");

  const loadRuns = useCallback(async () => {
    setRunsLoading(true);
    setRunsError("");
    try {
      const response = await fetch(`${API_URL}/api/v1/ingestion/runs`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) {
        throw new Error("Falha ao listar execuções");
      }
      const data = (await response.json()) as IngestionRunRow[];
      setRuns(data);
    } catch {
      setRunsError("Não foi possível carregar o histórico de ingestões.");
      setRuns([]);
    } finally {
      setRunsLoading(false);
    }
  }, [token]);

  useEffect(() => {
    loadRuns();
  }, [loadRuns]);

  const runsByBase = useMemo(() => latestRunPerBase(runs), [runs]);

  // CADU
  const [caduFile, setCaduFile] = useState<File | null>(null);
  const [caduStrategy, setCaduStrategy] = useState("replace");
  const [caduStatus, setCaduStatus] = useState("");
  const [caduProgress, setCaduProgress] = useState(0);
  const [caduUploading, setCaduUploading] = useState(false);

  // Bolsa Família
  const [pbfFile, setPbfFile] = useState<File | null>(null);
  const [pbfStrategy, setPbfStrategy] = useState("append");
  const [pbfCompetencia, setPbfCompetencia] = useState("");
  const [pbfOverwrite, setPbfOverwrite] = useState(false);
  const [pbfStatus, setPbfStatus] = useState("");
  const [pbfProgress, setPbfProgress] = useState(0);
  const [pbfUploading, setPbfUploading] = useState(false);

  // BPC
  const [bpcFile, setBpcFile] = useState<File | null>(null);
  const [bpcStrategy, setBpcStrategy] = useState("append");
  const [bpcCsvDelimiter, setBpcCsvDelimiter] = useState(",");
  const [bpcCompetencia, setBpcCompetencia] = useState("");
  const [bpcOverwrite, setBpcOverwrite] = useState(false);
  const [bpcStatus, setBpcStatus] = useState("");
  const [bpcProgress, setBpcProgress] = useState(0);
  const [bpcUploading, setBpcUploading] = useState(false);

  // SIBEC manutenções
  const [sibecFile, setSibecFile] = useState<File | null>(null);
  const [sibecStrategy, setSibecStrategy] = useState("append");
  const [sibecCompetencia, setSibecCompetencia] = useState("");
  const [sibecOverwrite, setSibecOverwrite] = useState(false);
  const [sibecStatus, setSibecStatus] = useState("");
  const [sibecProgress, setSibecProgress] = useState(0);
  const [sibecUploading, setSibecUploading] = useState(false);

  // SISC — Serviço de Convivência (CSV com ponto e vírgula, chave NIS)
  const [siscFile, setSiscFile] = useState<File | null>(null);
  const [siscStrategy, setSiscStrategy] = useState("replace");
  const [siscStatus, setSiscStatus] = useState("");
  const [siscProgress, setSiscProgress] = useState(0);
  const [siscUploading, setSiscUploading] = useState(false);

  // Base geográfica (tbl_geo — CSV com vírgula)
  const [geoFile, setGeoFile] = useState<File | null>(null);
  const [geoStrategy, setGeoStrategy] = useState("replace");
  const [geoStatus, setGeoStatus] = useState("");
  const [geoProgress, setGeoProgress] = useState(0);
  const [geoUploading, setGeoUploading] = useState(false);
  const [geoReport, setGeoReport] = useState<Record<string, unknown> | null>(null);
  const [geoReportLoading, setGeoReportLoading] = useState(false);
  const [geoReportError, setGeoReportError] = useState("");
  const [geoRepTodasElegiveis, setGeoRepTodasElegiveis] = useState(false);
  /** Famílias elegíveis sorteadas para o cruzamento quando não usa “todas” (amostra_pool na API). */
  const [geoRepPool, setGeoRepPool] = useState(8_000);
  const [geoRepLimite, setGeoRepLimite] = useState(5_000);
  const [geoBulkLoading, setGeoBulkLoading] = useState(false);
  const [geoBulkStatus, setGeoBulkStatus] = useState("");
  const [geoBulkLastPreview, setGeoBulkLastPreview] = useState<{ fam: number; lin: number } | null>(null);
  const [geoCepApplyLoading, setGeoCepApplyLoading] = useState(false);
  const [geoCepApplyStatus, setGeoCepApplyStatus] = useState("");
  const [bairrosCrasFile, setBairrosCrasFile] = useState<File | null>(null);
  const [geoCrasLoading, setGeoCrasLoading] = useState(false);
  const [geoCrasStatus, setGeoCrasStatus] = useState("");
  const [geoCrasPreview, setGeoCrasPreview] = useState<Record<string, unknown> | null>(null);
  const [bairrosCreasFile, setBairrosCreasFile] = useState<File | null>(null);
  const [geoCreasLoading, setGeoCreasLoading] = useState(false);
  const [geoCreasStatus, setGeoCreasStatus] = useState("");
  const [geoCreasPreview, setGeoCreasPreview] = useState<Record<string, unknown> | null>(null);
  const [geoMapsLoading, setGeoMapsLoading] = useState(false);
  const [geoMapsStatus, setGeoMapsStatus] = useState("");
  const [geoMissingLoading, setGeoMissingLoading] = useState(false);
  const [geoMissingCeps, setGeoMissingCeps] = useState<Array<Record<string, unknown>>>([]);
  const [geoViaCepLoading, setGeoViaCepLoading] = useState(false);
  const [geoViaCepStatus, setGeoViaCepStatus] = useState("");
  const [geoViaCepPreview, setGeoViaCepPreview] = useState<Record<string, unknown> | null>(null);
  const [geoViaCepLimit, setGeoViaCepLimit] = useState(50);

  async function submitCadu(e: FormEvent) {
    e.preventDefault();
    setCaduStatus("");
    setCaduProgress(0);
    if (!caduFile) {
      setCaduStatus("Selecione um arquivo CSV ou XLSX.");
      return;
    }
    const fd = new FormData();
    fd.append("file", caduFile);
    fd.append("source", "cecad");
    fd.append("dataset", "cadu");
    fd.append("strategy", caduStrategy);
    fd.append("csv_delimiter", ";");
    setCaduUploading(true);
    const res = await runIngestionUpload(fd, token, setCaduProgress);
    setCaduUploading(false);
    if (res.ok) {
      setCaduProgress(100);
      setCaduStatus(`Dados inseridos com sucesso. Total de ${res.data.row_count} registros.`);
      setCaduFile(null);
      await loadRuns();
    } else {
      setCaduStatus(res.errorText || "Falha na ingestão.");
    }
  }

  async function submitPbf(e: FormEvent) {
    e.preventDefault();
    setPbfStatus("");
    setPbfProgress(0);
    if (!pbfFile) {
      setPbfStatus("Selecione um arquivo CSV ou XLSX.");
      return;
    }
    if (!/^\d{6}$/.test(pbfCompetencia)) {
      setPbfStatus("Informe a competência no formato AAAAMM (mês de referência da folha). Ex.: 202504");
      return;
    }
    const fd = new FormData();
    fd.append("file", pbfFile);
    fd.append("source", "sibec");
    fd.append("dataset", "programa_bolsa_familia");
    fd.append("strategy", pbfStrategy);
    fd.append("csv_delimiter", ";");
    fd.append("competencia", pbfCompetencia);
    fd.append("overwrite_competencia", pbfOverwrite ? "true" : "false");
    setPbfUploading(true);
    const res = await runIngestionUpload(fd, token, setPbfProgress);
    setPbfUploading(false);
    if (res.ok) {
      setPbfProgress(100);
      setPbfStatus(
        `Dados inseridos com sucesso. Competência ${String(res.data.competencia)}. Total de ${res.data.row_count} registros na base Bolsa Família.`
      );
      setPbfFile(null);
      await loadRuns();
    } else {
      setPbfStatus(res.errorText || "Falha na ingestão.");
    }
  }

  async function submitBpc(e: FormEvent) {
    e.preventDefault();
    setBpcStatus("");
    setBpcProgress(0);
    if (!bpcFile) {
      setBpcStatus("Selecione um arquivo CSV ou XLSX.");
      return;
    }
    if (!/^\d{6}$/.test(bpcCompetencia)) {
      setBpcStatus("Informe a competência no formato AAAAMM (mês de referência da carga). Ex.: 202504");
      return;
    }
    const fd = new FormData();
    fd.append("file", bpcFile);
    fd.append("source", "bpc");
    fd.append("dataset", "beneficio_prestacao_continuada");
    fd.append("strategy", bpcStrategy);
    fd.append("csv_delimiter", bpcCsvDelimiter);
    fd.append("competencia", bpcCompetencia);
    fd.append("overwrite_competencia", bpcOverwrite ? "true" : "false");
    setBpcUploading(true);
    const res = await runIngestionUpload(fd, token, setBpcProgress);
    setBpcUploading(false);
    if (res.ok) {
      setBpcProgress(100);
      setBpcStatus(
        `Dados inseridos com sucesso. Competência ${String(res.data.competencia)}. Total de ${res.data.row_count} registros na base BPC.`
      );
      setBpcFile(null);
      await loadRuns();
    } else {
      setBpcStatus(res.errorText || "Falha na ingestão.");
    }
  }

  async function submitSibec(e: FormEvent) {
    e.preventDefault();
    setSibecStatus("");
    setSibecProgress(0);
    if (!sibecFile) {
      setSibecStatus("Selecione um arquivo CSV ou XLSX.");
      return;
    }
    if (!/^\d{6}$/.test(sibecCompetencia)) {
      setSibecStatus("Informe a competência no formato AAAAMM. Ex.: 202505");
      return;
    }
    const fd = new FormData();
    fd.append("file", sibecFile);
    fd.append("source", "sibec");
    fd.append("dataset", "manutencoes");
    fd.append("strategy", sibecStrategy);
    fd.append("csv_delimiter", ";");
    fd.append("competencia", sibecCompetencia);
    fd.append("overwrite_competencia", sibecOverwrite ? "true" : "false");
    setSibecUploading(true);
    const res = await runIngestionUpload(fd, token, setSibecProgress);
    setSibecUploading(false);
    if (res.ok) {
      setSibecProgress(100);
      setSibecStatus(
        `Dados inseridos com sucesso. Competência ${String(res.data.competencia)}. Total de ${res.data.row_count} registros.`
      );
      setSibecFile(null);
      await loadRuns();
    } else {
      setSibecStatus(res.errorText || "Falha na ingestão.");
    }
  }

  async function submitSisc(e: FormEvent) {
    e.preventDefault();
    setSiscStatus("");
    setSiscProgress(0);
    if (!siscFile) {
      setSiscStatus("Selecione o arquivo SISC.csv.");
      return;
    }
    const fd = new FormData();
    fd.append("file", siscFile);
    fd.append("source", "sisc");
    fd.append("dataset", "sisc");
    fd.append("strategy", siscStrategy);
    fd.append("csv_delimiter", ";");
    setSiscUploading(true);
    const res = await runIngestionUpload(fd, token, setSiscProgress);
    setSiscUploading(false);
    if (res.ok) {
      setSiscProgress(100);
      setSiscStatus(
        `Tabela raw.sisc__sisc atualizada. ${String(res.data.row_count ?? 0)} linhas. Próximo passo: Vigilância → aba «SISC Convivência» (atualize Pessoas e Família antes de qualificar).`,
      );
      setSiscFile(null);
      await loadRuns();
    } else {
      setSiscStatus(res.errorText || "Falha na ingestão SISC.");
    }
  }

  async function submitGeo(e: FormEvent) {
    e.preventDefault();
    setGeoStatus("");
    setGeoProgress(0);
    if (!geoFile) {
      setGeoStatus("Selecione o arquivo tbl_geo.csv.");
      return;
    }
    const fd = new FormData();
    fd.append("file", geoFile);
    fd.append("source", "geo");
    fd.append("dataset", "tbl_geo");
    fd.append("strategy", geoStrategy);
    fd.append("csv_delimiter", ",");
    setGeoUploading(true);
    const res = await runIngestionUpload(fd, token, setGeoProgress);
    setGeoUploading(false);
    if (res.ok) {
      setGeoProgress(100);
      setGeoStatus(
        `Tabela raw.geo__tbl_geo atualizada. ${String(res.data.row_count ?? 0)} linhas. Use o relatório abaixo para cruzar com o CADU.`,
      );
      setGeoFile(null);
      await loadRuns();
    } else {
      setGeoStatus(res.errorText || "Falha na ingestão.");
    }
  }

  async function applyGeoCras(dryRun: boolean) {
    if (!bairrosCrasFile) {
      setGeoCrasStatus("Selecione o arquivo bairros_cras.csv.");
      return;
    }
    setGeoCrasLoading(true);
    setGeoCrasStatus("");
    if (!dryRun) setGeoCrasPreview(null);
    try {
      const fd = new FormData();
      fd.append("file", bairrosCrasFile);
      const q = dryRun ? "?dry_run=true" : "";
      const response = await fetch(`${API_URL}/api/v1/geo/apply-cras-bairros${q}`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: fd,
      });
      const data = (await response.json().catch(() => ({}))) as Record<string, unknown> & { detail?: unknown };
      if (!response.ok) {
        const msg =
          typeof data.detail === "string"
            ? data.detail
            : "Falha ao aplicar CRAS na tbl_geo.";
        throw new Error(msg);
      }
      setGeoCrasPreview(data);
      if (dryRun) {
        setGeoCrasStatus(
          `Prévia: ${String(data.linhas_geo_atualizadas ?? 0)} linhas receberiam CRAS ` +
            `(mapa com ${String(data.bairros_no_mapa ?? 0)} bairros).`,
        );
      } else {
        setGeoCrasStatus(
          `CRAS gravado em ${String(data.linhas_geo_atualizadas ?? 0)} linhas de raw.geo__tbl_geo.`,
        );
      }
    } catch (e) {
      setGeoCrasStatus(e instanceof Error ? e.message : "Erro inesperado.");
    } finally {
      setGeoCrasLoading(false);
    }
  }

  async function applyGeoCreas(dryRun: boolean) {
    if (!bairrosCreasFile) {
      setGeoCreasStatus("Selecione o arquivo bairros_creas.csv.");
      return;
    }
    setGeoCreasLoading(true);
    setGeoCreasStatus("");
    if (!dryRun) setGeoCreasPreview(null);
    try {
      const fd = new FormData();
      fd.append("file", bairrosCreasFile);
      const q = dryRun ? "?dry_run=true" : "?refresh_familia=false";
      const response = await fetch(`${API_URL}/api/v1/geo/apply-creas-bairros${q}`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: fd,
      });
      const data = (await response.json().catch(() => ({}))) as Record<string, unknown> & { detail?: unknown };
      if (!response.ok) {
        const msg =
          typeof data.detail === "string"
            ? data.detail
            : "Falha ao aplicar CREAS na tbl_geo.";
        throw new Error(msg);
      }
      setGeoCreasPreview(data);
      if (dryRun) {
        setGeoCreasStatus(
          `Prévia: ${String(data.linhas_geo_atualizadas ?? 0)} linhas receberiam CREAS ` +
            `(mapa com ${String(data.bairros_no_mapa ?? 0)} bairros).`,
        );
      } else {
        const linhas = Number(data.linhas_geo_atualizadas ?? 0);
        if (linhas === 0) {
          setGeoCreasStatus(
            "ATENÇÃO: 0 linhas receberam CREAS. Use «Aplicar» (não só Prévia) com bairros_creas.csv selecionado.",
          );
        } else {
          setGeoCreasStatus(
            `CREAS gravado em ${linhas.toLocaleString("pt-BR")} linhas. ` +
              "Depois vá em Vigilância → Família → Gerar visão (separado, quando quiser).",
          );
        }
      }
    } catch (e) {
      setGeoCreasStatus(e instanceof Error ? e.message : "Erro inesperado.");
    } finally {
      setGeoCreasLoading(false);
    }
  }

  async function reapplyTerritorialMaps() {
    setGeoMapsLoading(true);
    setGeoMapsStatus("");
    try {
      const response = await fetch(`${API_URL}/api/v1/geo/reapply-territorial-maps?refresh_familia=false`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = (await response.json().catch(() => ({}))) as Record<string, unknown> & { detail?: unknown };
      if (!response.ok) {
        throw new Error(typeof data.detail === "string" ? data.detail : "Falha ao reaplicar mapas.");
      }
      if (data.reaplicado === false) {
        setGeoMapsStatus(
          String(
            data.motivo ??
              "Nenhum mapa salvo. Aplique bairros_cras.csv e bairros_creas.csv uma vez para gravar o mapa.",
          ),
        );
        return;
      }
      const pos = (data.geo_apos_reaplicar ?? {}) as Record<string, unknown>;
      setGeoMapsStatus(
        `Mapas reaplicados. Linhas com CRAS: ${String(pos.linhas_com_cras ?? "—")}, CREAS: ${String(pos.linhas_com_creas ?? "—")}.`,
      );
    } catch (e) {
      setGeoMapsStatus(e instanceof Error ? e.message : "Erro inesperado.");
    } finally {
      setGeoMapsLoading(false);
    }
  }

  async function loadGeoMissingCeps() {
    setGeoMissingLoading(true);
    setGeoViaCepStatus("");
    try {
      const response = await fetch(`${API_URL}/api/v1/geo/missing-ceps?limit=100`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = (await response.json().catch(() => ({}))) as { ceps?: Array<Record<string, unknown>>; detail?: unknown };
      if (!response.ok) {
        throw new Error(typeof data.detail === "string" ? data.detail : "Falha ao listar CEPs ausentes.");
      }
      setGeoMissingCeps(Array.isArray(data.ceps) ? data.ceps : []);
    } catch (e) {
      setGeoViaCepStatus(e instanceof Error ? e.message : "Erro inesperado.");
      setGeoMissingCeps([]);
    } finally {
      setGeoMissingLoading(false);
    }
  }

  async function supplementGeoViaCep(dryRun: boolean) {
    setGeoViaCepLoading(true);
    setGeoViaCepStatus("");
    if (!dryRun) setGeoViaCepPreview(null);
    try {
      const response = await fetch(
        `${API_URL}/api/v1/geo/supplement-viacep?dry_run=${dryRun ? "true" : "false"}&limit=${geoViaCepLimit}`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({}),
        },
      );
      const data = (await response.json().catch(() => ({}))) as Record<string, unknown> & { detail?: unknown };
      if (!response.ok) {
        throw new Error(typeof data.detail === "string" ? data.detail : "Falha ao complementar geo via ViaCEP.");
      }
      setGeoViaCepPreview(data);
      if (dryRun) {
        setGeoViaCepStatus(
          `Prévia: ${String(data.linhas_inseridas ?? 0)} linhas seriam inseridas ` +
            `(${String(data.ceps_analisados ?? 0)} CEPs analisados).`,
        );
      } else {
        setGeoViaCepStatus(`Geo atualizada: ${String(data.linhas_inseridas ?? 0)} linhas inseridas via ViaCEP.`);
        await loadGeoMissingCeps();
      }
    } catch (e) {
      setGeoViaCepStatus(e instanceof Error ? e.message : "Erro inesperado.");
    } finally {
      setGeoViaCepLoading(false);
    }
  }

  const loadGeoReport = useCallback(async () => {
    setGeoReportError("");
    setGeoReport(null);
    setGeoReportLoading(true);
    try {
      const q = new URLSearchParams();
      q.set("todas_elegiveis_outro_cep", geoRepTodasElegiveis ? "true" : "false");
      q.set("amostra_limite", String(geoRepLimite));
      if (!geoRepTodasElegiveis) {
        q.set("amostra_pool", String(geoRepPool));
      }
      const res = await fetch(`${API_URL}/api/v1/geo/match-report?${q}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = (await res.json().catch(() => ({}))) as Record<string, unknown> & { detail?: unknown };
      if (!res.ok) {
        const msg =
          typeof data.detail === "string"
            ? data.detail
            : Array.isArray(data.detail)
              ? JSON.stringify(data.detail)
              : "Falha ao gerar relatório.";
        throw new Error(msg);
      }
      setGeoReport(data);
    } catch (err) {
      setGeoReportError(err instanceof Error ? err.message : "Erro ao consultar relatório.");
    } finally {
      setGeoReportLoading(false);
    }
  }, [token, geoRepTodasElegiveis, geoRepLimite, geoRepPool]);

  function bulkGeoThresholds(): { sim_media_min: number; sim_outro_cep_min: number } {
    const pr = geoReport?.parametros_relatorio as Record<string, unknown> | undefined;
    const sm = typeof pr?.sim_media_min === "number" ? pr.sim_media_min : 0.35;
    const so = typeof pr?.sim_outro_cep_min === "number" ? pr.sim_outro_cep_min : 0.6;
    return { sim_media_min: sm, sim_outro_cep_min: so };
  }

  async function geoBulkPreview() {
    setGeoBulkStatus("");
    setGeoBulkLoading(true);
    try {
      const th = bulkGeoThresholds();
      const res = await fetch(`${API_URL}/api/v1/geo/bulk-apply-outro-cep`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ ...th, dry_run: true }),
      });
      const data = (await res.json().catch(() => ({}))) as Record<string, unknown> & { detail?: unknown };
      if (!res.ok) {
        const msg =
          typeof data.detail === "string"
            ? data.detail
            : Array.isArray(data.detail)
              ? JSON.stringify(data.detail)
              : "Falha na prévia em massa.";
        throw new Error(msg);
      }
      const fam = Number(data.familias_com_candidato ?? 0);
      const lin = Number(data.linhas_cadu_que_seriam_atualizadas ?? 0);
      setGeoBulkLastPreview({ fam, lin });
      setGeoBulkStatus(
        `Prévia: ${fam.toLocaleString("pt-BR")} família(s) com candidato; ${lin.toLocaleString("pt-BR")} linha(s) no CADU seriam atualizadas (uma consulta no servidor).`
      );
    } catch (err) {
      setGeoBulkLastPreview(null);
      setGeoBulkStatus(err instanceof Error ? err.message : "Erro na prévia em massa.");
    } finally {
      setGeoBulkLoading(false);
    }
  }

  async function geoBulkApply() {
    const th = bulkGeoThresholds();
    const prev = geoBulkLastPreview;
    const ok = window.confirm(
      prev
        ? `Confirmar: aplicar CEP candidato da geo em ${prev.fam.toLocaleString("pt-BR")} família(s) ` +
            `(${prev.lin.toLocaleString("pt-BR")} linha(s) em raw.cecad__cadu), com sim_media_min=${th.sim_media_min} e sim_outro_cep_min=${th.sim_outro_cep_min}? Sem desfazer automático.`
        : `Aplicar correções em massa no CADU (sem prévia recente). Limiares: sim_media_min=${th.sim_media_min}, sim_outro_cep_min=${th.sim_outro_cep_min}. Confirma?`
    );
    if (!ok) return;
    setGeoBulkStatus("");
    setGeoBulkLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/v1/geo/bulk-apply-outro-cep`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ ...th, dry_run: false }),
      });
      const data = (await res.json().catch(() => ({}))) as Record<string, unknown> & { detail?: unknown };
      if (!res.ok) {
        const msg =
          typeof data.detail === "string"
            ? data.detail
            : Array.isArray(data.detail)
              ? JSON.stringify(data.detail)
              : "Falha ao aplicar em massa.";
        throw new Error(msg);
      }
      const fam = Number(data.familias_com_candidato ?? 0);
      const lin = Number(data.linhas_cadu_atualizadas ?? 0);
      setGeoBulkLastPreview({ fam, lin });
      setGeoBulkStatus(
        `Concluído (servidor): ${fam.toLocaleString("pt-BR")} família(s), ${lin.toLocaleString("pt-BR")} linha(s) atualizadas em raw.cecad__cadu. Recarregando relatório…`
      );
      try {
        await loadGeoReport();
      } catch {
        setGeoBulkStatus(
          `Atualização feita (${lin.toLocaleString("pt-BR")} linhas), mas falhou ao recarregar o relatório. Clique em «Relatório» de novo.`
        );
        return;
      }
      setGeoBulkStatus(
        `Concluído: ${fam.toLocaleString("pt-BR")} família(s), ${lin.toLocaleString("pt-BR")} linha(s) no CADU. Relatório atualizado.`
      );
    } catch (err) {
      setGeoBulkStatus(err instanceof Error ? err.message : "Erro ao aplicar em massa.");
    } finally {
      setGeoBulkLoading(false);
    }
  }

  async function applyGeoCepSuggestionsFromSample() {
    const raw = geoReport?.amostra_suspeita_cep_errado_outro_cep_mais_parecido;
    if (!Array.isArray(raw) || raw.length === 0) return;
    const updates = raw
      .map((row) => {
        const r = row as Record<string, unknown>;
        return {
          cod_fam: String(r.cod_fam ?? "").trim(),
          cep_candidato: String(r.cep_candidato ?? "").trim(),
        };
      })
      .filter((u) => u.cod_fam.length > 0 && u.cep_candidato.length > 0);
    if (updates.length === 0) {
      setGeoCepApplyStatus("Nenhum par código familiar + CEP candidato na amostra.");
      return;
    }
    const ok = window.confirm(
      `Atualizar o CEP no CADU bruto (raw.cecad__cadu) para ${updates.length} família(s) desta amostra? ` +
        "Todas as linhas de cada código familiar receberão o CEP candidato da geo. Esta ação não tem desfazer automático."
    );
    if (!ok) return;

    setGeoCepApplyStatus("");
    setGeoCepApplyLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/v1/geo/apply-cep-suggestions`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ updates }),
      });
      const data = (await res.json().catch(() => ({}))) as Record<string, unknown> & { detail?: unknown };
      if (!res.ok) {
        const msg =
          typeof data.detail === "string"
            ? data.detail
            : Array.isArray(data.detail)
              ? JSON.stringify(data.detail)
              : "Falha ao aplicar CEPs.";
        throw new Error(msg);
      }
      const fam = data.familias_unicas_atualizadas;
      const lin = data.linhas_cadu_atualizadas;
      setGeoCepApplyStatus(
        `Atualizado: ${String(fam)} família(s), ${String(lin)} linha(s) no CADU. Recalculando relatório…`
      );
      try {
        await loadGeoReport();
      } catch {
        setGeoCepApplyStatus(
          `CEPs aplicados (${String(fam)} fam., ${String(lin)} linhas), mas falhou ao recarregar o relatório. Clique em «Relatório» de novo.`
        );
        return;
      }
      setGeoCepApplyStatus(
        `Concluído: ${String(fam)} família(s), ${String(lin)} linha(s) alteradas em raw.cecad__cadu.`
      );
    } catch (err) {
      setGeoCepApplyStatus(err instanceof Error ? err.message : "Erro ao aplicar sugestões de CEP.");
    } finally {
      setGeoCepApplyLoading(false);
    }
  }

  const tabs: { id: TabId; label: string; hint: string }[] = [
    { id: "cadu", label: "CADU", hint: "Cadastro Único (CECAD)" },
    { id: "pbf", label: "Bolsa Família", hint: "Programa Bolsa Família" },
    { id: "bpc", label: "BPC", hint: "Benefício Prestação Continuada" },
    { id: "sibec", label: "SIBEC Manutenções", hint: "Analíticos mensais por competência" },
    { id: "sisc", label: "SISC Convivência", hint: "Atendidos — vínculo por NIS" },
    { id: "geo", label: "Geo / CEP", hint: "Logradouros e teste de cruzamento" },
  ];

  return (
    <div className="ingestao-page">
      <aside className="ingestao-sidebar" aria-label="Fontes de dados">
        <div className="ingestao-sidebar-head">
          <h2>Ingestão RAW</h2>
          <p className="ingestao-sidebar-sub">Envio de arquivos para as bases brutas</p>
        </div>
        <nav className="ingestao-nav">
          {tabs.map((t) => (
            <button
              key={t.id}
              type="button"
              className={`ingestao-nav-item ${tab === t.id ? "active" : ""}`}
              onClick={() => setTab(t.id)}
            >
              <span className="ingestao-nav-label">{t.label}</span>
              <span className="ingestao-nav-hint">{t.hint}</span>
            </button>
          ))}
        </nav>
        <Link to="/" className="ingestao-back">
          ← Voltar ao painel
        </Link>
      </aside>

      <div className="ingestao-main-stack">
        <main className="ingestao-content">
          {tab === "cadu" && (
            <section className="ingestao-panel">
              <h1>CADU — Cadastro Único</h1>
              <p className="ingestao-desc">Base do Cadastro Único (CECAD).</p>
              <form onSubmit={submitCadu} className="auth-form">
                <label>
                  Estratégia
                  <select value={caduStrategy} onChange={(ev) => setCaduStrategy(ev.target.value)} disabled={caduUploading}>
                    <option value="replace">Substituir tabela inteira</option>
                    <option value="append">Agregar linhas</option>
                  </select>
                </label>
                <label>
                  Arquivo (CSV ou XLSX)
                  <input
                    type="file"
                    accept=".csv,.xlsx"
                    onChange={(ev) => setCaduFile(ev.target.files?.[0] || null)}
                    disabled={caduUploading}
                    required
                  />
                </label>
                <button type="submit" disabled={caduUploading}>
                  {caduUploading ? "Processando…" : "Processar CADU"}
                </button>
              </form>
              <div className="progress-wrap" aria-live="polite">
                <div className="progress-track">
                  <div className="progress-fill" style={{ width: `${caduProgress}%` }} />
                </div>
                <small>{caduUploading ? `Enviando: ${caduProgress}%` : "Aguardando envio"}</small>
              </div>
              {caduStatus && <p className={caduStatus.includes("sucesso") ? "status-ok" : "error"}>{caduStatus}</p>}
            </section>
          )}

          {tab === "pbf" && (
            <section className="ingestao-panel">
              <h1>Programa Bolsa Família</h1>
              <p className="ingestao-desc">
                Folha de pagamento: informe a competência (AAAAMM) do mês de referência do pagamento. A coluna{" "}
                <strong>competencia</strong> é gravada na RAW para cruzar na visão Família (último mês carregado).
              </p>
              <form onSubmit={submitPbf} className="auth-form">
                <label>
                  Competência (AAAAMM)
                  <input
                    type="text"
                    value={pbfCompetencia}
                    onChange={(ev) => setPbfCompetencia(ev.target.value)}
                    placeholder="202504"
                    maxLength={6}
                    disabled={pbfUploading}
                    required
                  />
                </label>
                <label>
                  Estratégia
                  <select value={pbfStrategy} onChange={(ev) => setPbfStrategy(ev.target.value)} disabled={pbfUploading}>
                    <option value="replace">Substituir tabela inteira</option>
                    <option value="append">Agregar linhas (recomendado)</option>
                  </select>
                </label>
                <label className="checkbox-inline">
                  <input
                    type="checkbox"
                    checked={pbfOverwrite}
                    onChange={(ev) => setPbfOverwrite(ev.target.checked)}
                    disabled={pbfUploading}
                  />
                  Sobrescrever esta competência se já existir
                </label>
                <label>
                  Arquivo (CSV ou XLSX)
                  <input
                    type="file"
                    accept=".csv,.xlsx"
                    onChange={(ev) => setPbfFile(ev.target.files?.[0] || null)}
                    disabled={pbfUploading}
                    required
                  />
                </label>
                <button type="submit" disabled={pbfUploading}>
                  {pbfUploading ? "Processando…" : "Processar Bolsa Família"}
                </button>
              </form>
              <div className="progress-wrap" aria-live="polite">
                <div className="progress-track">
                  <div className="progress-fill" style={{ width: `${pbfProgress}%` }} />
                </div>
                <small>{pbfUploading ? `Enviando: ${pbfProgress}%` : "Aguardando envio"}</small>
              </div>
              {pbfStatus && <p className={pbfStatus.includes("sucesso") ? "status-ok" : "error"}>{pbfStatus}</p>}
            </section>
          )}

          {tab === "bpc" && (
            <section className="ingestao-panel">
              <h1>BPC — Benefício de Prestação Continuada</h1>
              <p className="ingestao-desc">
                Carga por competência (AAAAMM), como na folha Bolsa Família e nas manutenções SIBEC: o mês de
                referência fica na coluna <strong>competencia</strong> na tabela RAW. Arquivos CSV do BPC costumam usar{" "}
                <strong>vírgula (,)</strong> como delimitador.
              </p>
              <form onSubmit={submitBpc} className="auth-form">
                <label>
                  Competência (AAAAMM)
                  <input
                    type="text"
                    value={bpcCompetencia}
                    onChange={(ev) => setBpcCompetencia(ev.target.value)}
                    placeholder="202504"
                    maxLength={6}
                    disabled={bpcUploading}
                    required
                  />
                </label>
                <label>
                  Estratégia
                  <select value={bpcStrategy} onChange={(ev) => setBpcStrategy(ev.target.value)} disabled={bpcUploading}>
                    <option value="replace">Substituir tabela inteira</option>
                    <option value="append">Agregar linhas (recomendado)</option>
                  </select>
                </label>
                <label>
                  Delimitador CSV
                  <select
                    value={bpcCsvDelimiter}
                    onChange={(ev) => setBpcCsvDelimiter(ev.target.value)}
                    disabled={bpcUploading}
                  >
                    <option value=",">Vírgula (,)</option>
                    <option value=";">Ponto e vírgula (;)</option>
                    <option value={"\t"}>Tabulação</option>
                  </select>
                </label>
                <label className="checkbox-inline">
                  <input
                    type="checkbox"
                    checked={bpcOverwrite}
                    onChange={(ev) => setBpcOverwrite(ev.target.checked)}
                    disabled={bpcUploading}
                  />
                  Sobrescrever esta competência se já existir
                </label>
                <label>
                  Arquivo (CSV ou XLSX)
                  <input
                    type="file"
                    accept=".csv,.xlsx"
                    onChange={(ev) => setBpcFile(ev.target.files?.[0] || null)}
                    disabled={bpcUploading}
                    required
                  />
                </label>
                <button type="submit" disabled={bpcUploading}>
                  {bpcUploading ? "Processando…" : "Processar BPC"}
                </button>
              </form>
              <div className="progress-wrap" aria-live="polite">
                <div className="progress-track">
                  <div className="progress-fill" style={{ width: `${bpcProgress}%` }} />
                </div>
                <small>{bpcUploading ? `Enviando: ${bpcProgress}%` : "Aguardando envio"}</small>
              </div>
              {bpcStatus && <p className={bpcStatus.includes("sucesso") ? "status-ok" : "error"}>{bpcStatus}</p>}
            </section>
          )}

          {tab === "sibec" && (
            <section className="ingestao-panel">
              <h1>SIBEC — Manutenções mensais</h1>
              <p className="ingestao-desc">
                Manutenções mensais SIBEC: informe a competência (AAAAMM) de cada arquivo. Carga inicial pode ser vários meses em modo <strong>acrescentar</strong>; depois, prefira um mês por vez.
              </p>
              <form onSubmit={submitSibec} className="auth-form">
                <label>
                  Competência (AAAAMM)
                  <input
                    type="text"
                    value={sibecCompetencia}
                    onChange={(ev) => setSibecCompetencia(ev.target.value)}
                    placeholder="202505"
                    maxLength={6}
                    disabled={sibecUploading}
                    required
                  />
                </label>
                <label>
                  Estratégia
                  <select
                    value={sibecStrategy}
                    onChange={(ev) => setSibecStrategy(ev.target.value)}
                    disabled={sibecUploading}
                  >
                    <option value="replace">Substituir tabela inteira</option>
                    <option value="append">Agregar linhas (recomendado)</option>
                  </select>
                </label>
                <label className="checkbox-inline">
                  <input
                    type="checkbox"
                    checked={sibecOverwrite}
                    onChange={(ev) => setSibecOverwrite(ev.target.checked)}
                    disabled={sibecUploading}
                  />
                  Sobrescrever esta competência se já existir
                </label>
                <label>
                  Arquivo (CSV ou XLSX)
                  <input
                    type="file"
                    accept=".csv,.xlsx"
                    onChange={(ev) => setSibecFile(ev.target.files?.[0] || null)}
                    disabled={sibecUploading}
                    required
                  />
                </label>
                <button type="submit" disabled={sibecUploading}>
                  {sibecUploading ? "Processando…" : "Processar manutenções"}
                </button>
              </form>
              <div className="progress-wrap" aria-live="polite">
                <div className="progress-track">
                  <div className="progress-fill" style={{ width: `${sibecProgress}%` }} />
                </div>
                <small>{sibecUploading ? `Enviando: ${sibecProgress}%` : "Aguardando envio"}</small>
              </div>
              {sibecStatus && <p className={sibecStatus.includes("sucesso") ? "status-ok" : "error"}>{sibecStatus}</p>}
            </section>
          )}

          {tab === "sisc" && (
            <section className="ingestao-panel">
              <h1>SISC — Serviço de Convivência</h1>
              <p className="ingestao-desc">
                Relatório de atendidos (SCFV). O arquivo <code className="inline-code">SISC.csv</code> usa{" "}
                <strong>ponto e vírgula (;)</strong> e a chave <strong>nu_nis_pessoa</strong> para cruzar com o CADU.
                Após a carga: atualize as visões <Link to="/vigilancia">Pessoas</Link> e{" "}
                <Link to="/vigilancia">Família</Link>, depois qualifique em{" "}
                <Link to="/convivencia">Convivência</Link>.
              </p>
              <form onSubmit={submitSisc} className="auth-form">
                <label>
                  Estratégia
                  <select
                    value={siscStrategy}
                    onChange={(ev) => setSiscStrategy(ev.target.value)}
                    disabled={siscUploading}
                  >
                    <option value="replace">Substituir tabela inteira</option>
                    <option value="append">Acrescentar linhas</option>
                  </select>
                </label>
                <label>
                  Arquivo CSV (SISC)
                  <input
                    type="file"
                    accept=".csv"
                    onChange={(ev) => setSiscFile(ev.target.files?.[0] || null)}
                    disabled={siscUploading}
                    required
                  />
                </label>
                <button type="submit" disabled={siscUploading}>
                  {siscUploading ? "Enviando…" : "Carregar SISC"}
                </button>
              </form>
              <div className="progress-wrap" aria-live="polite">
                <div className="progress-track">
                  <div className="progress-fill" style={{ width: `${siscProgress}%` }} />
                </div>
                <small>{siscUploading ? `Enviando: ${siscProgress}%` : "Aguardando envio"}</small>
              </div>
              {siscStatus && (
                <p className={siscStatus.includes("atualizada") ? "status-ok" : "error"}>{siscStatus}</p>
              )}
            </section>
          )}

          {tab === "geo" && (
            <section className="ingestao-panel">
              <h1>Geo — base local (tbl_geo)</h1>
              <p className="ingestao-desc">
                Envie o CSV <code className="inline-code">tbl_geo.csv</code> (cabeçalho com{" "}
                <code className="inline-code">cep_norm</code>, <code className="inline-code">endereco</code>,{" "}
                <code className="inline-code">bairro</code>, etc.). Delimitador deve ser{" "}
                <strong>vírgula</strong>. A API grava em <code className="inline-code">raw.geo__tbl_geo</code>.
                Depois, o relatório cruza CEP normalizado do CADU com essa tabela e mostra quantas famílias têm CEP
                ambíguo, sem correspondência ou match estrito de rua+bairro.
              </p>
              <form onSubmit={submitGeo} className="auth-form">
                <label>
                  Estratégia
                  <select
                    value={geoStrategy}
                    onChange={(ev) => setGeoStrategy(ev.target.value)}
                    disabled={geoUploading}
                  >
                    <option value="replace">Substituir tabela inteira (recomendado)</option>
                    <option value="append">Agregar linhas</option>
                  </select>
                </label>
                <label>
                  Arquivo CSV (tbl_geo)
                  <input
                    type="file"
                    accept=".csv"
                    onChange={(ev) => setGeoFile(ev.target.files?.[0] || null)}
                    disabled={geoUploading}
                    required
                  />
                </label>
                <button type="submit" disabled={geoUploading}>
                  {geoUploading ? "Enviando…" : "Carregar tbl_geo"}
                </button>
              </form>
              <div className="progress-wrap" aria-live="polite">
                <div className="progress-track">
                  <div className="progress-fill" style={{ width: `${geoProgress}%` }} />
                </div>
                <small>{geoUploading ? `Enviando: ${geoProgress}%` : "Aguardando envio"}</small>
              </div>
              {geoStatus && <p className={geoStatus.includes("atualizada") ? "status-ok" : "error"}>{geoStatus}</p>}

              <div
                className="auth-form"
                style={{ marginTop: "1.25rem", padding: "0.75rem 0", borderTop: "1px solid var(--color-border, #333)" }}
              >
                <h2 style={{ fontSize: "1.05rem", margin: "0 0 0.5rem" }}>CRAS por bairro (pontual)</h2>
                <p className="ingestao-desc" style={{ marginBottom: "0.75rem" }}>
                  Envie <code className="inline-code">bairros_cras.csv</code> (matriz CRAS 1–12 × bairros, delimitador{" "}
                  <strong>;</strong>). Preenche <code className="inline-code">cras</code> em{" "}
                  <code className="inline-code">raw.geo__tbl_geo</code> pelo <strong>bairro</strong> (sem rua). Duplicata
                  em CRAS 1–7 e 8–12: prevalece 8–12. Abreviações Jd/Cond/Vl são normalizadas; alias{" "}
                  <em>Residencial Vida Nova Ribeirão</em> → <em>Jardim Cristo Redentor</em>.
                </p>
                <label>
                  Arquivo bairros_cras.csv
                  <input
                    type="file"
                    accept=".csv"
                    onChange={(ev) => setBairrosCrasFile(ev.target.files?.[0] || null)}
                    disabled={geoCrasLoading}
                  />
                </label>
                <div className="vig-actions" style={{ flexWrap: "wrap", gap: "0.5rem", marginTop: "0.5rem" }}>
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={() => void applyGeoCras(true)}
                    disabled={geoCrasLoading}
                  >
                    {geoCrasLoading ? "Processando…" : "Prévia (dry-run)"}
                  </button>
                  <button type="button" onClick={() => void applyGeoCras(false)} disabled={geoCrasLoading}>
                    Aplicar CRAS na tbl_geo
                  </button>
                </div>
                {geoCrasStatus && (
                  <p
                    className={
                      geoCrasStatus.includes("Prévia") || geoCrasStatus.includes("gravado") ? "status-ok" : "error"
                    }
                    style={{ marginTop: "0.75rem" }}
                  >
                    {geoCrasStatus}
                  </p>
                )}
                {geoCrasPreview && (
                  <ul className="vig-warnings" style={{ listStyle: "disc", marginTop: "0.5rem" }}>
                    <li>Bairros no mapa: {String(geoCrasPreview.bairros_no_mapa ?? "—")}</li>
                    <li>Linhas com bairro na geo: {String(geoCrasPreview.linhas_geo_com_bairro ?? "—")}</li>
                    <li>CRAS atualizados: {String(geoCrasPreview.linhas_geo_atualizadas ?? "—")}</li>
                    <li>
                      Bairros renomeados na geo:{" "}
                      {String(geoCrasPreview.linhas_geo_bairro_renomeadas ?? "—")}
                    </li>
                    {Array.isArray(geoCrasPreview.bairros_geo_sem_match) &&
                      (geoCrasPreview.bairros_geo_sem_match as string[]).length > 0 && (
                        <li>
                          Bairros na geo sem match (amostra):{" "}
                          {(geoCrasPreview.bairros_geo_sem_match as string[]).slice(0, 8).join("; ")}
                        </li>
                      )}
                    {Array.isArray(geoCrasPreview.conflitos_bairro) &&
                      (geoCrasPreview.conflitos_bairro as unknown[]).length > 0 && (
                        <li>
                          Duplicatas resolvidas (CRAS 8–12 prevalece):{" "}
                          {(geoCrasPreview.conflitos_bairro as unknown[]).length}
                        </li>
                      )}
                  </ul>
                )}
              </div>

              <div
                className="auth-form"
                style={{ marginTop: "1.25rem", padding: "0.75rem 0", borderTop: "1px solid var(--color-border, #333)" }}
              >
                <h2 style={{ fontSize: "1.05rem", margin: "0 0 0.5rem" }}>CREAS por bairro (pontual)</h2>
                <p className="ingestao-desc" style={{ marginBottom: "0.75rem" }}>
                  Envie <code className="inline-code">bairros_creas.csv</code> (matriz CREAS 1–5 × bairros, delimitador{" "}
                  <strong>;</strong>). Preenche <code className="inline-code">creas</code> em{" "}
                  <code className="inline-code">raw.geo__tbl_geo</code> pelo <strong>bairro</strong>.
                  <strong> Ordem:</strong> aplique CRAS → aplique CREAS → Vigilância (visão Família, separado).
                  Use «Aplicar», não só «Prévia». O CREAS aparece nos filtros pela geo (CEP) sem precisar regenerar Família.
                </p>
                <label>
                  Arquivo bairros_creas.csv
                  <input
                    type="file"
                    accept=".csv"
                    onChange={(ev) => setBairrosCreasFile(ev.target.files?.[0] || null)}
                    disabled={geoCreasLoading}
                  />
                </label>
                <div className="vig-actions" style={{ flexWrap: "wrap", gap: "0.5rem", marginTop: "0.5rem" }}>
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={() => void applyGeoCreas(true)}
                    disabled={geoCreasLoading}
                  >
                    {geoCreasLoading ? "Processando…" : "Prévia (dry-run)"}
                  </button>
                  <button type="button" onClick={() => void applyGeoCreas(false)} disabled={geoCreasLoading}>
                    Aplicar CREAS na tbl_geo
                  </button>
                </div>
                {geoCreasStatus && (
                  <p
                    className={
                      geoCreasStatus.startsWith("ATENÇÃO")
                        ? "error"
                        : geoCreasStatus.includes("Prévia") || geoCreasStatus.includes("gravado") || geoCreasStatus.includes("regenerada")
                          ? "status-ok"
                          : "error"
                    }
                    style={{ marginTop: "0.75rem" }}
                  >
                    {geoCreasStatus}
                  </p>
                )}
                {geoCreasPreview && (
                  <ul className="vig-warnings" style={{ listStyle: "disc", marginTop: "0.5rem" }}>
                    <li>Bairros no mapa: {String(geoCreasPreview.bairros_no_mapa ?? "—")}</li>
                    <li>Linhas com bairro na geo: {String(geoCreasPreview.linhas_geo_com_bairro ?? "—")}</li>
                    <li>CREAS atualizados: {String(geoCreasPreview.linhas_geo_atualizadas ?? "—")}</li>
                  </ul>
                )}
              </div>

              <div
                className="auth-form"
                style={{ marginTop: "1.25rem", padding: "0.75rem 0", borderTop: "1px solid var(--color-border, #333)" }}
              >
                <h2 style={{ fontSize: "1.05rem", margin: "0 0 0.5rem" }}>Reaplicar CRAS/CREAS na geo</h2>
                <p className="ingestao-desc" style={{ marginBottom: "0.75rem" }}>
                  Depois de reenviar <code className="inline-code">tbl_geo.csv</code> ou refazer Vigilância, os códigos
                  CRAS/CREAS somem das linhas (o CSV base não traz essas colunas). Use este botão para restaurar a
                  partir do último <strong>bairros_cras.csv</strong> e <strong>bairros_creas.csv</strong> aplicados.
                </p>
                <button type="button" className="btn btn-secondary" onClick={() => void reapplyTerritorialMaps()} disabled={geoMapsLoading}>
                  {geoMapsLoading ? "Reaplicando…" : "Reaplicar mapas salvos na tbl_geo"}
                </button>
                {geoMapsStatus && (
                  <p className={geoMapsStatus.includes("reaplicados") ? "status-ok" : "error"} style={{ marginTop: "0.75rem" }}>
                    {geoMapsStatus}
                  </p>
                )}
              </div>

              <div
                className="auth-form"
                style={{ marginTop: "1.25rem", padding: "0.75rem 0", borderTop: "1px solid var(--color-border, #333)" }}
              >
                <h2 style={{ fontSize: "1.05rem", margin: "0 0 0.5rem" }}>Completar geo — ViaCEP</h2>
                <p className="ingestao-desc" style={{ marginBottom: "0.75rem" }}>
                  CEPs presentes no CADU mas ausentes em <code className="inline-code">raw.geo__tbl_geo</code>{" "}
                  (<code className="inline-code">n_geo_por_cep = 0</code>). A API consulta{" "}
                  <a href="https://viacep.com.br/" target="_blank" rel="noreferrer">
                    ViaCEP
                  </a>{" "}
                  (logradouro e bairro oficiais) e insere na geo; se ViaCEP falhar, usa texto do CADU. Copia{" "}
                  <code className="inline-code">cras</code> de linhas existentes com o mesmo bairro.
                </p>
                <label style={{ display: "block", marginBottom: "0.5rem" }}>
                  Máximo de CEPs por execução
                  <input
                    type="number"
                    min={1}
                    max={200}
                    value={geoViaCepLimit}
                    onChange={(ev) => setGeoViaCepLimit(Number(ev.target.value))}
                    disabled={geoViaCepLoading}
                    style={{ marginLeft: "0.35rem", width: "5rem" }}
                  />
                </label>
                <div className="vig-actions" style={{ flexWrap: "wrap", gap: "0.5rem" }}>
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={() => void loadGeoMissingCeps()}
                    disabled={geoMissingLoading || geoViaCepLoading}
                  >
                    {geoMissingLoading ? "Listando…" : "Listar CEPs ausentes (CADU)"}
                  </button>
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={() => void supplementGeoViaCep(true)}
                    disabled={geoViaCepLoading}
                  >
                    {geoViaCepLoading ? "Consultando ViaCEP…" : "Prévia ViaCEP"}
                  </button>
                  <button type="button" onClick={() => void supplementGeoViaCep(false)} disabled={geoViaCepLoading}>
                    Inserir na tbl_geo
                  </button>
                </div>
                {geoViaCepStatus && (
                  <p
                    className={
                      geoViaCepStatus.includes("Prévia") ||
                      geoViaCepStatus.includes("atualizada") ||
                      geoViaCepStatus.includes("Listando")
                        ? "status-ok"
                        : "error"
                    }
                    style={{ marginTop: "0.75rem" }}
                  >
                    {geoViaCepStatus}
                  </p>
                )}
                {geoMissingCeps.length > 0 && (
                  <details style={{ marginTop: "0.75rem" }}>
                    <summary>{geoMissingCeps.length} CEP(s) no CADU sem linha na geo (amostra)</summary>
                    <ul className="vig-warnings" style={{ listStyle: "disc", marginTop: "0.5rem" }}>
                      {geoMissingCeps.slice(0, 12).map((row) => (
                        <li key={String(row.cep_n)}>
                          {String(row.cep_n)} — {String(row.familias ?? 0)} fam. — {String(row.bairro_raw ?? "—")}
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
                {geoViaCepPreview && (
                  <ul className="vig-warnings" style={{ listStyle: "disc", marginTop: "0.5rem" }}>
                    <li>Inseridas: {String(geoViaCepPreview.linhas_inseridas ?? "—")}</li>
                    <li>Já na geo: {String(geoViaCepPreview.ceps_ja_na_geo ?? "—")}</li>
                    <li>Sem dados: {String(geoViaCepPreview.ceps_sem_dados ?? "—")}</li>
                    {Array.isArray(geoViaCepPreview.amostra_insercoes) &&
                      (geoViaCepPreview.amostra_insercoes as unknown[]).length > 0 && (
                        <li>
                          Amostra:{" "}
                          {(geoViaCepPreview.amostra_insercoes as Array<Record<string, unknown>>)
                            .slice(0, 5)
                            .map((r) => `${r.cep_norm} → ${r.bairro} (${r.fonte})`)
                            .join("; ")}
                        </li>
                      )}
                  </ul>
                )}
              </div>

              <div
                className="auth-form"
                style={{ marginTop: "1.25rem", padding: "0.75rem 0", borderTop: "1px solid var(--color-border, #333)" }}
              >
                <p className="ingestao-desc" style={{ marginBottom: "0.5rem" }}>
                  <strong>Relatório</strong> — cruzamento “outro CEP”. Sem “todas as famílias”, aumente o{" "}
                  <em>pool aleatório</em> para encher a amostra JSON até o limite de linhas; volume muito grande: use a
                  correção em massa abaixo.
                </p>
                <label style={{ display: "flex", gap: "0.5rem", alignItems: "center", marginBottom: "0.5rem" }}>
                  <input
                    type="checkbox"
                    checked={geoRepTodasElegiveis}
                    onChange={(ev) => setGeoRepTodasElegiveis(ev.target.checked)}
                    disabled={geoReportLoading}
                  />
                  Todas as famílias elegíveis no cruzamento (sem amostra aleatória; consulta longa no PostgreSQL)
                </label>
                <label style={{ display: "block", marginBottom: "0.5rem", opacity: geoRepTodasElegiveis ? 0.55 : 1 }}>
                  Pool aleatório — quantas famílias elegíveis entram no sorteio (só quando a opção acima{" "}
                  <strong>não</strong> está marcada; máx. 100 000 na API)
                  <input
                    type="number"
                    min={1}
                    max={100000}
                    value={geoRepPool}
                    onChange={(ev) => setGeoRepPool(Number(ev.target.value))}
                    disabled={geoReportLoading || geoRepTodasElegiveis}
                    style={{ marginLeft: "0.35rem", width: "6.5rem" }}
                  />
                </label>
                <label>
                  Limite de linhas na amostra JSON (0 = sem limite — pode travar o navegador)
                  <input
                    type="number"
                    min={0}
                    max={200000}
                    value={geoRepLimite}
                    onChange={(ev) => setGeoRepLimite(Number(ev.target.value))}
                    disabled={geoReportLoading}
                    style={{ marginLeft: "0.35rem", width: "6rem" }}
                  />
                </label>
              </div>

              <div className="vig-actions" style={{ marginTop: "0.75rem", flexWrap: "wrap", gap: "0.5rem" }}>
                <button type="button" className="btn btn-secondary" onClick={() => void loadGeoReport()} disabled={geoReportLoading}>
                  {geoReportLoading ? "Calculando…" : "Relatório: CADU × geo (CEP)"}
                </button>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => void geoBulkPreview()}
                  disabled={geoBulkLoading || geoReportLoading}
                >
                  {geoBulkLoading ? "Servidor…" : "Prévia em massa (contagem no servidor)"}
                </button>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => void geoBulkApply()}
                  disabled={geoBulkLoading || geoReportLoading}
                >
                  Aplicar CEPs em massa no CADU (uma transação)
                </button>
              </div>
              {geoBulkStatus && (
                <p
                  className={
                    geoBulkStatus.startsWith("Prévia:") ||
                    geoBulkStatus.startsWith("Concluído") ||
                    geoBulkStatus.includes("Relatório atualizado") ||
                    geoBulkStatus.startsWith("Atualização feita")
                      ? "status-ok"
                      : "error"
                  }
                  style={{ marginTop: "0.5rem" }}
                >
                  {geoBulkStatus}
                </p>
              )}
              {geoReportError && <p className="error">{geoReportError}</p>}
              {geoReport && (
                <div className="vig-result" style={{ marginTop: "1rem", textAlign: "left" }}>
                  <p className="ingestao-desc" style={{ textAlign: "left" }}>
                    <strong>pg_trgm</strong> (similaridade de texto):{" "}
                    {geoReport.pg_trgm_disponivel === true
                      ? "ativo — faixas abaixo usam a melhor similaridade entre o CADU e alguma linha da geo com o mesmo CEP."
                      : "indisponível — peça CREATE EXTENSION pg_trgm no PostgreSQL para ver faixas e suspeita de CEP errado."}
                  </p>
                  {geoReport.parametros_relatorio != null && (
                    <p className="ingestao-desc" style={{ textAlign: "left", marginTop: "0.5rem" }}>
                      <strong>Parâmetros</strong> desta consulta (sobrescreva na URL do endpoint{" "}
                      <code className="inline-code">/api/v1/geo/match-report</code>):{" "}
                      <code className="inline-code" style={{ fontSize: "0.78rem" }}>
                        {JSON.stringify(geoReport.parametros_relatorio)}
                      </code>
                    </p>
                  )}
                  <dl className="run-card-meta" style={{ marginTop: "0.75rem" }}>
                    {(() => {
                      const pr = geoReport.parametros_relatorio as Record<string, number> | undefined;
                      const simAlta = typeof pr?.sim_alta_min === "number" ? pr.sim_alta_min : 0.65;
                      const simMedia = typeof pr?.sim_media_min === "number" ? pr.sim_media_min : 0.35;
                      const fmt = (n: number) =>
                        n.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
                      const metricRows: [string, string][] = [
                        ["familias_total", "Famílias (1 por código no CADU)"],
                        ["familias_cep_invalido", "Famílias com CEP inválido/vazio"],
                        ["familias_cep_valido", "Famílias com CEP válido"],
                        ["familias_sem_linha_geo_no_cep", "CEP válido, mas não existe na tbl_geo"],
                        ["familias_cep_unico_na_base", "CEP com exatamente 1 linha na tbl_geo"],
                        ["familias_cep_ambiguo", "CEP com mais de 1 logradouro na tbl_geo"],
                        ["familias_match_estrito_rua_bairro", "Match estrito: CEP + rua + bairro (igual, lower)"],
                        ["familias_com_cep_na_geo", "Famílias cujo CEP existe na geo (≥1 linha)"],
                        [
                          "familias_mesmo_cep_sim_alta",
                          `Mesmo CEP: similaridade média ≥ ${fmt(simAlta)} (rua+bairro)`,
                        ],
                        ["familias_mesmo_cep_sim_media", `Mesmo CEP: similaridade ${fmt(simMedia)}–${fmt(simAlta)}`],
                        ["familias_mesmo_cep_sim_baixa", `Mesmo CEP: similaridade abaixo de ${fmt(simMedia)}`],
                        ["familias_mesmo_cep_sem_texto_para_comparar", "CEP na geo, mas logradouro e bairro vazios no CADU"],
                        ["geo_linhas_total", "Linhas na tbl_geo"],
                        ["geo_ceps_distintos", "CEPs distintos na tbl_geo"],
                      ];
                      return metricRows;
                    })().map(([key, label]) => (
                      <div key={key}>
                        <dt>{label}</dt>
                        <dd>
                          {typeof geoReport[key] === "number" || typeof geoReport[key] === "bigint"
                            ? Number(geoReport[key]).toLocaleString("pt-BR")
                            : String(geoReport[key] ?? "—")}
                        </dd>
                      </div>
                    ))}
                  </dl>
                  <p className="ingestao-desc" style={{ textAlign: "left", marginTop: "1rem" }}>
                    Metodologia (ordem: CEP → depois grafia):
                  </p>
                  <pre
                    className="inline-code"
                    style={{
                      display: "block",
                      padding: "0.75rem",
                      overflow: "auto",
                      fontSize: "0.78rem",
                      maxHeight: "16rem",
                    }}
                  >
                    {JSON.stringify(geoReport.metodologia ?? {}, null, 2)}
                  </pre>
                  <p className="ingestao-desc" style={{ textAlign: "left", marginTop: "1rem" }}>
                    Amostra — CEP ambíguo (vários logradouros na geo para o mesmo CEP):
                  </p>
                  <pre
                    className="inline-code"
                    style={{
                      display: "block",
                      padding: "0.75rem",
                      overflow: "auto",
                      fontSize: "0.78rem",
                      maxHeight: "12rem",
                    }}
                  >
                    {JSON.stringify(geoReport.amostra_familias_cep_ambiguo ?? [], null, 2)}
                  </pre>
                  <p className="ingestao-desc" style={{ textAlign: "left", marginTop: "1rem" }}>
                    Amostra — CEP do CADU ausente na tbl_geo:
                  </p>
                  <pre
                    className="inline-code"
                    style={{
                      display: "block",
                      padding: "0.75rem",
                      overflow: "auto",
                      fontSize: "0.78rem",
                      maxHeight: "12rem",
                    }}
                  >
                    {JSON.stringify(geoReport.amostra_familias_sem_geo_no_cep ?? [], null, 2)}
                  </pre>
                  <p className="ingestao-desc" style={{ textAlign: "left", marginTop: "1rem" }}>
                    Amostra — suspeita de CEP errado: melhor parecer com linha da geo em <strong>outro</strong> CEP
                    (texto parecido; revisar CEP antes da grafia).
                  </p>
                  <div className="vig-actions" style={{ marginTop: "0.5rem", marginBottom: "0.5rem" }}>
                    <button
                      type="button"
                      className="btn btn-secondary"
                      disabled={
                        geoCepApplyLoading ||
                        geoReportLoading ||
                        !Array.isArray(geoReport.amostra_suspeita_cep_errado_outro_cep_mais_parecido) ||
                        (geoReport.amostra_suspeita_cep_errado_outro_cep_mais_parecido as unknown[]).length === 0
                      }
                      onClick={() => void applyGeoCepSuggestionsFromSample()}
                    >
                      {geoCepApplyLoading ? "Aplicando CEPs…" : "Aplicar CEPs candidatos desta amostra no CADU"}
                    </button>
                  </div>
                  {geoCepApplyStatus && (
                    <p
                      className={
                        geoCepApplyStatus.startsWith("Concluído:") ||
                        geoCepApplyStatus.startsWith("Atualizado:") ||
                        geoCepApplyStatus.includes("aplicados (")
                          ? "status-ok"
                          : "error"
                      }
                      style={{ marginBottom: "0.5rem" }}
                    >
                      {geoCepApplyStatus}
                    </p>
                  )}
                  <pre
                    className="inline-code"
                    style={{
                      display: "block",
                      padding: "0.75rem",
                      overflow: "auto",
                      fontSize: "0.78rem",
                      maxHeight: "18rem",
                    }}
                  >
                    {JSON.stringify(geoReport.amostra_suspeita_cep_errado_outro_cep_mais_parecido ?? [], null, 2)}
                  </pre>
                </div>
              )}
            </section>
          )}
        </main>

        <section className="ingestao-history" aria-labelledby="ingestao-history-title">
          <div className="ingestao-history-head">
            <div>
              <h2 id="ingestao-history-title">Última ingestão por base</h2>
              <p className="ingestao-history-sub">
                Para cada base de dados, só aparece a carga mais recente (várias execuções do mesmo tipo são resumidas num único registro).
              </p>
            </div>
            <button type="button" onClick={() => loadRuns()} disabled={runsLoading}>
              {runsLoading ? "Atualizando…" : "Atualizar lista"}
            </button>
          </div>
          {runsError && <p className="error">{runsError}</p>}
          {!runsError && runs.length === 0 && !runsLoading && (
            <p className="ingestao-desc" style={{ margin: 0 }}>
              Nenhuma execução registrada ainda.
            </p>
          )}
          {!runsError && runsByBase.length > 0 && (
            <ul className="runs-cards" aria-label="Resumo das últimas ingestões">
              {runsByBase.map((run) => (
                <li key={run.id} className="run-card">
                  <div className="run-card-top">
                    <h3 className="run-card-title">{humanBaseTitle(run)}</h3>
                    <span
                      className={`run-card-status ${runStatusClass(run.status)}`}
                    >
                      {formatStatusLabel(run.status)}
                    </span>
                  </div>
                  <dl className="run-card-meta">
                    <div>
                      <dt>Data e hora</dt>
                      <dd>{formatRunDate(run.finished_at || run.created_at)}</dd>
                    </div>
                    <div>
                      <dt>Registros</dt>
                      <dd>{run.row_count.toLocaleString("pt-BR")}</dd>
                    </div>
                    <div>
                      <dt>Origem</dt>
                      <dd>{formatSourceLabel(run.source)}</dd>
                    </div>
                    <div>
                      <dt>Modo</dt>
                      <dd>{formatStrategyLabel(run.strategy)}</dd>
                    </div>
                    <div className="run-card-meta-file">
                      <dt>Arquivo</dt>
                      <dd title={run.file_name}>{run.file_name}</dd>
                    </div>
                    <div>
                      <dt>Enviado por</dt>
                      <dd className="run-card-email">{run.created_by_email}</dd>
                    </div>
                  </dl>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
