import { useEffect, useMemo, useState } from "react";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

export type TerritorialUnitOption = {
  cras_cod?: string;
  creas_cod?: string;
  cras_nome?: string;
  creas_nome?: string;
  cras_codigo_exibicao?: string;
  creas_codigo_exibicao?: string;
  rotulo_ordenado?: string;
  familias: number;
};

export type BairroOption = {
  bairro: string;
  familias: number;
};

type CreasDiagnostic = {
  acao_sugerida?: string;
  geo_preenchimento?: { linhas_com_creas?: number };
  mapas_persistidos?: { creas_bairros?: number };
};

type Props = {
  token: string;
  loading?: boolean;
  crasCod: string;
  creasCod: string;
  bairroFiltro: string;
  onCrasChange: (value: string) => void;
  onCreasChange: (value: string) => void;
  onBairroChange: (value: string) => void;
  className?: string;
};

export function fmtBairro(nome: string): string {
  return nome.toLocaleUpperCase("pt-BR");
}

export default function TerritorialFilterSelects({
  token,
  loading = false,
  crasCod,
  creasCod,
  bairroFiltro,
  onCrasChange,
  onCreasChange,
  onBairroChange,
  className = "caract-filtros-grid",
}: Props) {
  const [crasCatalog, setCrasCatalog] = useState<TerritorialUnitOption[]>([]);
  const [creasCatalog, setCreasCatalog] = useState<TerritorialUnitOption[]>([]);
  const [creasDiagnostic, setCreasDiagnostic] = useState<CreasDiagnostic | null>(null);
  const [bairrosOptions, setBairrosOptions] = useState<BairroOption[]>([]);
  const [loadingBairros, setLoadingBairros] = useState(false);

  useEffect(() => {
    fetch(`${API_URL}/api/v1/cras/catalog`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(async (res) => {
        if (!res.ok) throw new Error();
        const data = (await res.json()) as { items: TerritorialUnitOption[] };
        setCrasCatalog(data.items || []);
      })
      .catch(() => setCrasCatalog([]));
  }, [token]);

  useEffect(() => {
    fetch(`${API_URL}/api/v1/creas/catalog`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(async (res) => {
        if (!res.ok) {
          const err = (await res.json().catch(() => ({}))) as { detail?: string };
          throw new Error(typeof err.detail === "string" ? err.detail : "Falha ao carregar CREAS");
        }
        const data = (await res.json()) as {
          items: TerritorialUnitOption[];
          diagnostic?: CreasDiagnostic;
        };
        setCreasCatalog(data.items || []);
        setCreasDiagnostic(data.diagnostic ?? null);
      })
      .catch((e: unknown) => {
        setCreasCatalog([]);
        setCreasDiagnostic({
          acao_sugerida:
            e instanceof Error
              ? e.message
              : "Não foi possível carregar CREAS. Verifique se a visão Família foi gerada.",
        });
      });
  }, [token]);

  useEffect(() => {
    const crasAtivo = crasCod && crasCod !== "__todos__" && crasCod !== "__sem_cras__";
    const creasAtivo = creasCod && creasCod !== "__todos__" && creasCod !== "__sem_creas__";
    if (!crasAtivo && !creasAtivo) {
      setBairrosOptions([]);
      return;
    }

    setLoadingBairros(true);
    const url = creasAtivo
      ? `${API_URL}/api/v1/creas/bairros?num_creas=${encodeURIComponent(creasCod)}`
      : `${API_URL}/api/v1/cras/bairros?num_cras=${encodeURIComponent(crasCod)}`;

    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then(async (res) => {
        if (!res.ok) throw new Error();
        const data = (await res.json()) as { items: BairroOption[] };
        setBairrosOptions(data.items ?? []);
      })
      .catch(() => setBairrosOptions([]))
      .finally(() => setLoadingBairros(false));
  }, [token, crasCod, creasCod]);

  const creasUnidades = useMemo(
    () => creasCatalog.filter((c) => c.creas_cod && c.creas_cod !== "__sem_creas__"),
    [creasCatalog],
  );

  const creasAviso = useMemo(() => {
    if (creasUnidades.length > 0) return null;
    return (
      creasDiagnostic?.acao_sugerida ??
      "Nenhum CREAS territorial encontrado. Em Ingestão → Geo, aplique bairros_creas.csv ou use Reaplicar mapas salvos."
    );
  }, [creasUnidades.length, creasDiagnostic]);

  const bairroSelectDisabled =
    loading ||
    loadingBairros ||
    ((crasCod === "__todos__" || crasCod === "__sem_cras__") &&
      (creasCod === "__todos__" || creasCod === "__sem_creas__"));

  const bairroPlaceholder = (() => {
    const crasAtivo = crasCod && crasCod !== "__todos__" && crasCod !== "__sem_cras__";
    const creasAtivo = creasCod && creasCod !== "__todos__" && creasCod !== "__sem_creas__";
    if (!crasAtivo && !creasAtivo) return "Selecione CRAS ou CREAS";
    if (loadingBairros) return "Carregando bairros…";
    if (bairrosOptions.length === 0) return "Nenhum bairro territorial";
    return creasAtivo ? "Todos os bairros do CREAS" : "Todos os bairros do CRAS";
  })();

  return (
    <>
      {creasAviso ? (
        <p className="caract-filtro-aviso" role="status">
          {creasAviso}
        </p>
      ) : null}
      <div className={className}>
        <label>
          <span>CRAS territorial</span>
          <select
            className="cras-select"
            value={crasCod}
            onChange={(e) => onCrasChange(e.target.value)}
            disabled={loading}
          >
            <option value="__todos__">Município inteiro</option>
            <option value="__sem_cras__">Sem CRAS na geo</option>
            {crasCatalog.map((c) => (
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
        <label>
          <span>CREAS territorial</span>
          <select
            className="cras-select"
            value={creasCod}
            onChange={(e) => onCreasChange(e.target.value)}
            disabled={loading}
          >
            <option value="__todos__">Todos os CREAS</option>
            {creasUnidades.length === 0 ? (
              <option value="__sem_creas__">Sem CREAS na geo</option>
            ) : (
              <>
                <option value="__sem_creas__">Sem CREAS na geo</option>
                {creasUnidades.map((c) => (
                  <option key={c.creas_cod} value={c.creas_cod}>
                    {(c.rotulo_ordenado ?? c.creas_nome) +
                      (c.creas_codigo_exibicao && c.creas_codigo_exibicao !== "—"
                        ? ` [${c.creas_codigo_exibicao}]`
                        : "")}
                    {" · "}
                    {c.familias.toLocaleString("pt-BR")} fam.
                  </option>
                ))}
              </>
            )}
          </select>
        </label>
        <label>
          <span>Bairro</span>
          <select
            className="cras-select"
            value={bairroFiltro}
            onChange={(e) => onBairroChange(e.target.value)}
            disabled={bairroSelectDisabled}
          >
            <option value="">{bairroPlaceholder}</option>
            {bairrosOptions.map((b) => (
              <option key={b.bairro} value={b.bairro}>
                {fmtBairro(b.bairro)} · {b.familias.toLocaleString("pt-BR")} fam.
              </option>
            ))}
          </select>
        </label>
      </div>
    </>
  );
}

export function appendTerritorialParams(
  params: URLSearchParams,
  crasCod: string,
  creasCod: string,
  bairro: string,
  options?: { crasKey?: string; creasKey?: string; ivsMode?: boolean },
): void {
  const crasKey = options?.crasKey ?? "cras_cod";
  const creasKey = options?.creasKey ?? "creas_cod";
  const ivsMode = options?.ivsMode ?? false;
  if (crasCod && crasCod !== "__todos__") {
    params.set(ivsMode ? "num_cras" : crasKey, crasCod);
  }
  if (creasCod && creasCod !== "__todos__") {
    params.set(ivsMode ? "num_creas" : creasKey, creasCod);
  }
  if (bairro.trim()) params.set("bairro", bairro.trim());
}
