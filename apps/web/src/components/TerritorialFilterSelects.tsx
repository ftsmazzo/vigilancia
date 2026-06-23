import { useEffect, useState } from "react";

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

type Props = {
  token: string;
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

function compactFamilias(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1).replace(".", ",")}M`;
  if (n >= 10_000) return `${Math.round(n / 1000)}k`;
  if (n >= 1000) return `${(n / 1000).toFixed(1).replace(".", ",")}k`;
  return n.toLocaleString("pt-BR");
}

function unitOptionLabel(rotulo: string | undefined, familias: number): string {
  const short = (rotulo ?? "").split(" — ")[0].trim() || rotulo || "—";
  return `${short} · ${compactFamilias(familias)} fam.`;
}

export default function TerritorialFilterSelects({
  token,
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
  const [bairrosOptions, setBairrosOptions] = useState<BairroOption[]>([]);
  const [loadingBairros, setLoadingBairros] = useState(false);

  useEffect(() => {
    const ctrl = new AbortController();
    fetch(`${API_URL}/api/v1/cras/catalog?lite=true`, {
      headers: { Authorization: `Bearer ${token}` },
      signal: ctrl.signal,
    })
      .then(async (res) => {
        if (!res.ok) throw new Error();
        const data = (await res.json()) as { items: TerritorialUnitOption[] };
        setCrasCatalog(data.items || []);
      })
      .catch(() => {
        if (!ctrl.signal.aborted) setCrasCatalog([]);
      });
    return () => ctrl.abort();
  }, [token]);

  useEffect(() => {
    const ctrl = new AbortController();
    fetch(`${API_URL}/api/v1/creas/catalog?lite=true`, {
      headers: { Authorization: `Bearer ${token}` },
      signal: ctrl.signal,
    })
      .then(async (res) => {
        if (!res.ok) throw new Error();
        const data = (await res.json()) as { items: TerritorialUnitOption[] };
        setCreasCatalog(data.items || []);
      })
      .catch(() => {
        if (!ctrl.signal.aborted) setCreasCatalog([]);
      });
    return () => ctrl.abort();
  }, [token]);

  useEffect(() => {
    const crasAtivo = crasCod && crasCod !== "__todos__" && crasCod !== "__sem_cras__";
    const creasAtivo = creasCod && creasCod !== "__todos__" && creasCod !== "__sem_creas__";
    if (!crasAtivo && !creasAtivo) {
      setBairrosOptions([]);
      return;
    }

    const ctrl = new AbortController();
    setLoadingBairros(true);
    const url = creasAtivo
      ? `${API_URL}/api/v1/creas/bairros?num_creas=${encodeURIComponent(creasCod)}`
      : `${API_URL}/api/v1/cras/bairros?num_cras=${encodeURIComponent(crasCod)}`;

    fetch(url, { headers: { Authorization: `Bearer ${token}` }, signal: ctrl.signal })
      .then(async (res) => {
        if (!res.ok) throw new Error();
        const data = (await res.json()) as { items: BairroOption[] };
        setBairrosOptions(data.items ?? []);
      })
      .catch(() => {
        if (!ctrl.signal.aborted) setBairrosOptions([]);
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setLoadingBairros(false);
      });

    return () => ctrl.abort();
  }, [token, crasCod, creasCod]);

  const creasUnidades = creasCatalog.filter((c) => c.creas_cod && c.creas_cod !== "__sem_creas__");

  const bairroSelectDisabled =
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
    <div className={className}>
      <label className="territorial-filter-field">
        <span>CRAS territorial</span>
        <select className="cras-select territorial-select" value={crasCod} onChange={(e) => onCrasChange(e.target.value)}>
          <option value="__todos__">Município inteiro</option>
          <option value="__sem_cras__">Sem CRAS na geo</option>
          {crasCatalog.map((c) => (
            <option key={c.cras_cod} value={c.cras_cod}>
              {unitOptionLabel(c.rotulo_ordenado ?? c.cras_nome, c.familias)}
            </option>
          ))}
        </select>
      </label>
      <label className="territorial-filter-field">
        <span>CREAS territorial</span>
        <select
          className="cras-select territorial-select"
          value={creasCod}
          onChange={(e) => onCreasChange(e.target.value)}
        >
          <option value="__todos__">Todos os CREAS</option>
          <option value="__sem_creas__">Sem CREAS na geo</option>
          {creasUnidades.map((c) => (
            <option key={c.creas_cod} value={c.creas_cod}>
              {unitOptionLabel(c.rotulo_ordenado ?? c.creas_nome, c.familias)}
            </option>
          ))}
        </select>
      </label>
      <label className="territorial-filter-field">
        <span>Bairro</span>
        <select
          className="cras-select territorial-select"
          value={bairroFiltro}
          onChange={(e) => onBairroChange(e.target.value)}
          disabled={bairroSelectDisabled}
        >
          <option value="">{bairroPlaceholder}</option>
          {bairrosOptions.map((b) => (
            <option key={b.bairro} value={b.bairro}>
              {fmtBairro(b.bairro)} · {compactFamilias(b.familias)} fam.
            </option>
          ))}
        </select>
      </label>
    </div>
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
