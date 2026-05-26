"""Expressões SQL reutilizáveis para classificação de campos CADU (pessoas)."""

from __future__ import annotations


def cadu_sim(col: str) -> str:
    return f"btrim(COALESCE({col}::text, '')) IN ('1', '01', 'sim', 's', 'true', 'yes')"


def classificacao_sexo_sql(col: str = "cod_sexo") -> str:
    c = f"btrim(COALESCE({col}::text, ''))"
    return f"""CASE
      WHEN {c} IN ('1', '01') THEN 'masculino'
      WHEN {c} IN ('2', '02') THEN 'feminino'
      WHEN UPPER({c}) IN ('M', 'MASCULINO') THEN 'masculino'
      WHEN UPPER({c}) IN ('F', 'FEMININO') THEN 'feminino'
      ELSE 'nao_informado'
    END"""


def classificacao_raca_sql(col: str = "cod_raca_cor") -> str:
    c = f"btrim(COALESCE({col}::text, ''))"
    return f"""CASE
      WHEN {c} IN ('1', '01') THEN 'branca'
      WHEN {c} IN ('2', '02') THEN 'preta'
      WHEN {c} IN ('3', '03') THEN 'amarela'
      WHEN {c} IN ('4', '04') THEN 'parda'
      WHEN {c} IN ('5', '05') THEN 'indigena'
      WHEN {c} <> '' THEN 'outro_codigo'
      ELSE 'nao_informado'
    END"""


def classificacao_escolaridade_sql(col: str = "grau_instrucao") -> str:
    c = f"btrim(COALESCE({col}::text, ''))"
    return f"""CASE
      WHEN {c} IN ('1', '01') THEN 'analfabeto'
      WHEN {c} IN ('2', '02') THEN 'fundamental_incompleto'
      WHEN {c} IN ('3', '03') THEN 'fundamental_completo'
      WHEN {c} IN ('4', '04') THEN 'medio_incompleto'
      WHEN {c} IN ('5', '05') THEN 'medio_completo'
      WHEN {c} IN ('6', '06') THEN 'superior_incompleto'
      WHEN {c} IN ('7', '07') THEN 'superior_completo'
      WHEN {c} <> '' THEN 'outro_codigo'
      ELSE 'nao_informado'
    END"""


def classificacao_idade_sql(col: str = "idade") -> str:
    return f"""CASE
      WHEN {col} IS NULL THEN 'idade_nao_informada'
      WHEN {col} < 12 THEN 'crianca_0_11'
      WHEN {col} < 18 THEN 'adolescente_12_17'
      WHEN {col} < 60 THEN 'adulto_18_59'
      ELSE 'idoso_60_mais'
    END"""


_DEF_FLAGS = (
    "ind_def_cegueira",
    "ind_def_baixa_visao",
    "ind_def_surdez_profunda",
    "ind_def_surdez_leve",
    "ind_def_fisica",
    "ind_def_mental",
    "ind_def_sindrome_down",
    "ind_def_transtorno_mental",
)


def tem_deficiencia_expr(prefix: str = "pes") -> str:
    parts = [cadu_sim(f"{prefix}.cod_deficiencia")]
    parts.extend(cadu_sim(f"{prefix}.{f}") for f in _DEF_FLAGS)
    return "(" + " OR ".join(parts) + ")"


def classificacao_deficiencia_sql(prefix: str = "pes") -> str:
    n_tipos = " + ".join(
        f"CASE WHEN {cadu_sim(f'{prefix}.{f}')} THEN 1 ELSE 0 END" for f in _DEF_FLAGS
    )
    any_def = tem_deficiencia_expr(prefix)
    return f"""CASE
      WHEN NOT ({any_def}) THEN 'sem_deficiencia'
      WHEN ({n_tipos}) >= 2 THEN 'deficiencia_multipla'
      WHEN {cadu_sim(f'{prefix}.ind_def_fisica')} THEN 'deficiencia_fisica'
      WHEN {cadu_sim(f'{prefix}.ind_def_cegueira')} OR {cadu_sim(f'{prefix}.ind_def_baixa_visao')} THEN 'deficiencia_visual'
      WHEN {cadu_sim(f'{prefix}.ind_def_surdez_profunda')} OR {cadu_sim(f'{prefix}.ind_def_surdez_leve')} THEN 'deficiencia_auditiva'
      WHEN {cadu_sim(f'{prefix}.ind_def_mental')} OR {cadu_sim(f'{prefix}.ind_def_transtorno_mental')}
        OR {cadu_sim(f'{prefix}.ind_def_sindrome_down')} THEN 'deficiencia_mental_cognitiva'
      WHEN {cadu_sim(f'{prefix}.cod_deficiencia')} THEN 'com_deficiencia_sem_tipo'
      ELSE 'sem_deficiencia'
    END"""
