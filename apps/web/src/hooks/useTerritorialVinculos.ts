import { useEffect, useMemo, useState } from "react";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

export type TerritorialVinculos = {
  disponivel: boolean;
  cras_to_creas: Record<string, string[]>;
  creas_to_cras: Record<string, string[]>;
  mensagem?: string;
};

export function isCrasAtivo(crasCod: string): boolean {
  return Boolean(crasCod && crasCod !== "__todos__" && crasCod !== "__sem_cras__");
}

export function isCreasAtivo(creasCod: string): boolean {
  return Boolean(creasCod && creasCod !== "__todos__" && creasCod !== "__sem_creas__");
}

export function useTerritorialVinculos(token: string): TerritorialVinculos | null {
  const [vinculos, setVinculos] = useState<TerritorialVinculos | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    fetch(`${API_URL}/api/v1/geo/territorial-vinculos`, {
      headers: { Authorization: `Bearer ${token}` },
      signal: ctrl.signal,
    })
      .then(async (res) => {
        if (!res.ok) throw new Error();
        const data = (await res.json()) as TerritorialVinculos;
        setVinculos(data);
      })
      .catch(() => {
        if (!ctrl.signal.aborted) setVinculos(null);
      });
    return () => ctrl.abort();
  }, [token]);

  return vinculos;
}

export function filterCrasCatalog<T extends { cras_cod?: string }>(
  catalog: T[],
  creasCod: string,
  vinculos: TerritorialVinculos | null,
  options?: { keepSemCras?: boolean },
): T[] {
  if (!vinculos?.disponivel || !isCreasAtivo(creasCod)) return catalog;
  const allowed = new Set(vinculos.creas_to_cras[creasCod] ?? []);
  if (allowed.size === 0) return catalog;
  return catalog.filter((c) => {
    if (options?.keepSemCras && c.cras_cod === "__sem_cras__") return true;
    return allowed.has(c.cras_cod ?? "");
  });
}

export function filterCreasCatalog<T extends { creas_cod?: string }>(
  catalog: T[],
  crasCod: string,
  vinculos: TerritorialVinculos | null,
  options?: { keepSemCreas?: boolean },
): T[] {
  if (!vinculos?.disponivel || !isCrasAtivo(crasCod)) return catalog;
  const allowed = new Set(vinculos.cras_to_creas[crasCod] ?? []);
  if (allowed.size === 0) return catalog;
  return catalog.filter((c) => {
    if (options?.keepSemCreas && c.creas_cod === "__sem_creas__") return true;
    return allowed.has(c.creas_cod ?? "");
  });
}

export function useTerritorialCrossFilter<T extends { cras_cod?: string }>(
  catalog: T[],
  creasCod: string,
  vinculos: TerritorialVinculos | null,
  options?: { keepSemCras?: boolean },
): T[] {
  return useMemo(
    () => filterCrasCatalog(catalog, creasCod, vinculos, options),
    [catalog, creasCod, vinculos, options?.keepSemCras],
  );
}

export function useCreasCrossFilter<T extends { creas_cod?: string }>(
  catalog: T[],
  crasCod: string,
  vinculos: TerritorialVinculos | null,
  options?: { keepSemCreas?: boolean },
): T[] {
  return useMemo(
    () => filterCreasCatalog(catalog, crasCod, vinculos, options),
    [catalog, crasCod, vinculos, options?.keepSemCreas],
  );
}

export function useResetInvalidTerritorialSelection(
  crasCod: string,
  creasCod: string,
  crasFiltrado: Array<{ cras_cod?: string }>,
  creasFiltrado: Array<{ creas_cod?: string }>,
  onCrasChange: (value: string) => void,
  onCreasChange: (value: string) => void,
): void {
  useEffect(() => {
    if (!isCreasAtivo(creasCod)) return;
    if (creasFiltrado.some((c) => c.creas_cod === creasCod)) return;
    onCreasChange("__todos__");
  }, [creasCod, creasFiltrado, onCreasChange]);

  useEffect(() => {
    if (!isCrasAtivo(crasCod)) return;
    if (crasFiltrado.some((c) => c.cras_cod === crasCod)) return;
    onCrasChange("__todos__");
  }, [crasCod, crasFiltrado, onCrasChange]);
}
