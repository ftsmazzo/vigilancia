"""Parâmetros cadastrais/renda alinhados ao município e IVCAD v1.0.5."""

from __future__ import annotations

# Salário mínimo vigente (atualizar por competência quando houver tabela param.*).
SALARIO_MINIMO = 1621.0
SM_METADE = 810.50  # ½ SM — universo IVCAD (renda per capita)
LIMIAR_POBREZA_EXTREMA = 218.0
MESES_TAC_MAX = 24


def sql_marcador_pbf_cadu(col: str) -> str:
    """Marcador PBF no CADU (d.marc_pbf → marc_pbf_cadu na MV)."""
    return (
        f"btrim(LOWER(COALESCE({col}::text, ''))) "
        f"IN ('1', '01', 'sim', 's', 'true')"
    )


def sql_universo_ivs_elegivel(*, alias: str = "f") -> str:
    """
    Universo IVCAD v1.0.5 (IN084):
    - Beneficiária PBF (folha SIBEC ou marcador CADU), OU
    - Cadastro atualizado ≤ 24 meses (mesma regra TAC) E renda per capita ≤ ½ SM.
    """
    a = alias
    return f"""(
      COALESCE({a}.marc_pbf, FALSE)
      OR {sql_marcador_pbf_cadu(f"{a}.marc_pbf_cadu")}
      OR (
        {a}.meses_desatualizado IS NOT NULL
        AND {a}.meses_desatualizado <= {MESES_TAC_MAX}
        AND {a}.renda_per_capita IS NOT NULL
        AND {a}.renda_per_capita >= 0
        AND {a}.renda_per_capita <= {SM_METADE}
      )
    )"""
