"""Materialized view vig.mvw_pessoas: uma linha por registro de pessoa no CADU (layout tudo)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .familia_mview import CADU_TABLE, _columns, _qi, _table_exists, ensure_vig_functions

# (alias na MV, coluna física na RAW, modo: fam|date|nome|code|text|cpf)
PESSOAS_FIELDS: list[tuple[str, str, str]] = [
    ("codigo_familiar", "p_cod_familiar_fam", "fam"),
    ("ind_trabalho_infantil", "p_ind_trabalho_infantil_pessoa", "code"),
    ("nome", "p_nom_pessoa", "nome"),
    ("num_nis", "p_num_nis_pessoa_atual", "nis"),
    ("cod_sexo", "p_cod_sexo_pessoa", "code"),
    ("data_nascimento", "p_dta_nasc_pessoa", "date"),
    ("cod_parentesco_rf", "p_cod_parentesco_rf_pessoa", "code"),
    ("cod_raca_cor", "p_cod_raca_cor_pessoa", "code"),
    ("ind_identidade_genero", "p_ind_identidade_genero", "code"),
    ("ind_transgenero", "p_ind_transgenero", "code"),
    ("ind_tipo_identidade_genero", "p_ind_tipo_identidade_genero", "code"),
    ("num_cpf", "p_num_cpf_pessoa", "cpf"),
    ("cod_sabe_ler_escrever", "p_cod_sabe_ler_escrever_memb", "code"),
    ("ind_frequenta_escola", "p_ind_frequenta_escola_memb", "code"),
    ("nome_escola", "p_nom_escola_memb", "nome"),
    ("cod_escola_local", "p_cod_escola_local_memb", "code"),
    ("cod_curso_frequenta", "p_cod_curso_frequenta_memb", "code"),
    ("cod_ano_serie_frequenta", "p_cod_ano_serie_frequenta_memb", "code"),
    ("cod_curso_frequentou", "p_cod_curso_frequentou_pessoa_memb", "code"),
    ("cod_ano_serie_frequentou", "p_cod_ano_serie_frequentou_memb", "code"),
    ("cod_concluiu_frequentou", "p_cod_concluiu_frequentou_memb", "code"),
    ("grau_instrucao", "p_grau_instrucao", "code"),
    ("cod_agricultura_trab", "p_cod_agricultura_trab_memb", "code"),
    ("cod_trabalhou", "p_cod_trabalhou_memb", "code"),
    ("cod_afastado_trab", "p_cod_afastado_trab_memb", "code"),
    ("cod_principal_trab", "p_cod_principal_trab_memb", "code"),
    ("fx_renda_individual_805", "p_fx_renda_individual_805", "code"),
    ("fx_renda_individual_808", "p_fx_renda_individual_808", "code"),
    ("fx_renda_individual_809_1", "p_fx_renda_individual_809_1", "code"),
    ("fx_renda_individual_809_2", "p_fx_renda_individual_809_2", "code"),
    ("fx_renda_individual_809_3", "p_fx_renda_individual_809_3", "code"),
    ("fx_renda_individual_809_4", "p_fx_renda_individual_809_4", "code"),
    ("fx_renda_individual_809_5", "p_fx_renda_individual_809_5", "code"),
    ("cod_deficiencia", "p_cod_deficiencia_memb", "code"),
    ("ind_def_cegueira", "p_ind_def_cegueira_memb", "code"),
    ("ind_def_baixa_visao", "p_ind_def_baixa_visao_memb", "code"),
    ("ind_def_surdez_profunda", "p_ind_def_surdez_profunda_memb", "code"),
    ("ind_def_surdez_leve", "p_ind_def_surdez_leve_memb", "code"),
    ("ind_def_fisica", "p_ind_def_fisica_memb", "code"),
    ("ind_def_mental", "p_ind_def_mental_memb", "code"),
    ("ind_def_sindrome_down", "p_ind_def_sindrome_down_memb", "code"),
    ("ind_def_transtorno_mental", "p_ind_def_transtorno_mental_memb", "code"),
    ("ind_ajuda_nao", "p_ind_ajuda_nao_memb", "code"),
    ("ind_ajuda_familia", "p_ind_ajuda_familia_memb", "code"),
    ("ind_ajuda_especializado", "p_ind_ajuda_especializado_memb", "code"),
    ("ind_ajuda_vizinho", "p_ind_ajuda_vizinho_memb", "code"),
    ("ind_ajuda_instituicao", "p_ind_ajuda_instituicao_memb", "code"),
    ("ind_ajuda_outra", "p_ind_ajuda_outra_memb", "code"),
    ("marc_sit_rua", "p_marc_sit_rua", "code"),
    ("ind_dormir_rua", "p_ind_dormir_rua_memb", "code"),
    ("qtd_dormir_freq_rua", "p_qtd_dormir_freq_rua_memb", "code"),
    ("ind_dormir_albergue", "p_ind_dormir_albergue_memb", "code"),
    ("qtd_dormir_freq_albergue", "p_qtd_dormir_freq_albergue_memb", "code"),
    ("ind_dormir_dom_part", "p_ind_dormir_dom_part_memb", "code"),
    ("qtd_dormir_freq_dom_part", "p_qtd_dormir_freq_dom_part_memb", "code"),
    ("ind_outro", "p_ind_outro_memb", "code"),
    ("qtd_freq_outro", "p_qtd_freq_outro_memb", "code"),
    ("cod_tempo_rua", "p_cod_tempo_rua_memb", "code"),
    ("ind_motivo_perda", "p_ind_motivo_perda_memb", "code"),
    ("ind_motivo_ameaca", "p_ind_motivo_ameaca_memb", "code"),
    ("ind_motivo_probs_fam", "p_ind_motivo_probs_fam_memb", "code"),
    ("ind_motivo_alcool", "p_ind_motivo_alcool_memb", "code"),
    ("ind_motivo_desemprego", "p_ind_motivo_desemprego_memb", "code"),
    ("ind_motivo_trabalho", "p_ind_motivo_trabalho_memb", "code"),
    ("ind_motivo_saude", "p_ind_motivo_saude_memb", "code"),
    ("ind_motivo_pref", "p_ind_motivo_pref_memb", "code"),
    ("ind_motivo_outro", "p_ind_motivo_outro_memb", "code"),
    ("ind_motivo_nao_sabe", "p_ind_motivo_nao_sabe_memb", "code"),
    ("ind_motivo_nao_resp", "p_ind_motivo_nao_resp_memb", "code"),
    ("cod_tempo_cidade", "p_cod_tempo_cidade_memb", "code"),
    ("cod_vive_fam_rua", "p_cod_vive_fam_rua_memb", "code"),
    ("cod_contato_parente", "p_cod_contato_parente_memb", "code"),
    ("ind_ativ_com_escola", "p_ind_ativ_com_escola_memb", "code"),
    ("ind_ativ_com_coop", "p_ind_ativ_com_coop_memb", "code"),
    ("ind_ativ_com_mov_soc", "p_ind_ativ_com_mov_soc_memb", "code"),
    ("ind_ativ_com_nao_sabe", "p_ind_ativ_com_nao_sabe_memb", "code"),
    ("ind_ativ_com_nao_resp", "p_ind_ativ_com_nao_resp_memb", "code"),
    ("ind_atend_cras", "p_ind_atend_cras_memb", "code"),
    ("ind_atend_creas", "p_ind_atend_creas_memb", "code"),
    ("ind_atend_centro_ref_rua", "p_ind_atend_centro_ref_rua_memb", "code"),
    ("ind_atend_inst_gov", "p_ind_atend_inst_gov_memb", "code"),
    ("ind_atend_inst_nao_gov", "p_ind_atend_inst_nao_gov_memb", "code"),
    ("ind_atend_hospital_geral", "p_ind_atend_hospital_geral_memb", "code"),
    ("cod_cart_assinada", "p_cod_cart_assinada_memb", "code"),
    ("ind_dinh_const", "p_ind_dinh_const_memb", "code"),
    ("ind_dinh_flanelhinha", "p_ind_dinh_flanelhinha_memb", "code"),
    ("ind_dinh_carregador", "p_ind_dinh_carregador_memb", "code"),
    ("ind_dinh_catador", "p_ind_dinh_catador_memb", "code"),
    ("ind_dinh_servs_gerais", "p_ind_dinh_servs_gerais_memb", "code"),
    ("ind_dinh_pede", "p_ind_dinh_pede_memb", "code"),
    ("ind_dinh_vendas", "p_ind_dinh_vendas_memb", "code"),
    ("ind_dinh_outro", "p_ind_dinh_outro_memb", "code"),
    ("ind_dinh_nao_resp", "p_ind_dinh_nao_resp_memb", "code"),
    ("ind_atend_nenhum", "p_ind_atend_nenhum_memb", "code"),
]


def _ref(cadu_cols: set[str], phys: str) -> str:
    if phys in cadu_cols:
        return f"t.{_qi(phys)}"
    return "NULL"


def _expr(ref: str, mode: str) -> str:
    if ref == "NULL":
        cast = "NULL::text"
        if mode == "date":
            return "NULL::date"
        if mode == "fam":
            return "NULL::text"
        if mode == "cpf":
            return "NULL::text"
        return cast
    if mode == "fam":
        return f"vig.norm_familia_cod({ref}::text)"
    if mode == "date":
        return f"vig.parse_cadu_date({ref}::text)"
    if mode == "nome":
        return f"vig.clean_spaces({ref}::text)"
    if mode == "code":
        return f"vig.ltrim_zeros_text({ref}::text)"
    if mode == "text":
        return f"vig.clean_spaces({ref}::text)"
    if mode in ("cpf", "nis"):
        # NIS/CPF: somente dígitos, 11 posições (zeros à esquerda).
        return f"""CASE
          WHEN vig.only_digits({ref}::text) IS NULL
            OR btrim(vig.only_digits({ref}::text)) = '' THEN NULL
          WHEN length(vig.only_digits({ref}::text)) > 11 THEN NULL
          ELSE lpad(vig.only_digits({ref}::text), 11, '0')
        END"""
    raise ValueError(f"modo desconhecido: {mode}")


def _validate_pessoas_columns(cols: set[str]) -> list[str]:
    optional = frozenset(
        {
            "p_cod_trabalhou_memb",
            "p_cod_afastado_trab_memb",
        }
    )
    missing: list[str] = []
    for _alias, phys, _m in PESSOAS_FIELDS:
        if phys not in cols and phys not in optional:
            missing.append(phys)
    return missing


def build_pessoas_mview_sql(*, cadu_cols: set[str]) -> str:
    select_parts: list[str] = ["t.id AS cadu_row_id"]

    for alias, phys, mode in PESSOAS_FIELDS:
        ref = _ref(cadu_cols, phys)
        expr = _expr(ref, mode)
        select_parts.append(f"{expr} AS {_qi(alias)}")
        if alias == "data_nascimento":
            idade_expr = f"""CASE
              WHEN vig.parse_cadu_date({ref}::text) IS NULL THEN NULL::integer
              ELSE EXTRACT(
                YEAR FROM age(CURRENT_DATE, vig.parse_cadu_date({ref}::text))
              )::integer
            END"""
            select_parts.append(f"{idade_expr} AS idade")

    inner = ", ".join(select_parts)
    sql = f"""
    CREATE MATERIALIZED VIEW vig.mvw_pessoas AS
    SELECT {inner}
    FROM raw.{_qi(CADU_TABLE)} AS t
    """
    return re.sub(r"\s+", " ", sql).strip()


@dataclass
class PessoasRefreshResult:
    row_count: int
    warnings: list[str]


def refresh_pessoas_mview(conn: Connection) -> PessoasRefreshResult:
    warnings: list[str] = []
    ensure_vig_functions(conn)

    if not _table_exists(conn, "raw", CADU_TABLE):
        raise ValueError("Tabela raw.cecad__cadu não encontrada. Ingeste o CADU antes.")

    cadu_cols = _columns(conn, "raw", CADU_TABLE)
    missing = _validate_pessoas_columns(cadu_cols)
    if missing:
        raise ValueError(
            "Tabela raw.cecad__cadu sem colunas do bloco pessoa (layout tudo): "
            + ", ".join(missing[:12])
            + ("…" if len(missing) > 12 else "")
            + ". Confirme a ingestão do arquivo CADU completo."
        )

    mview_sql = build_pessoas_mview_sql(cadu_cols=cadu_cols)

    conn.execute(text("DROP MATERIALIZED VIEW IF EXISTS vig.mvw_pessoas CASCADE"))
    conn.execute(text(mview_sql))
    conn.execute(
        text("CREATE UNIQUE INDEX IF NOT EXISTS mvw_pessoas_cadu_row_uq ON vig.mvw_pessoas (cadu_row_id)")
    )

    row_count = conn.execute(text("SELECT COUNT(*) FROM vig.mvw_pessoas")).scalar() or 0

    return PessoasRefreshResult(row_count=int(row_count), warnings=warnings)
