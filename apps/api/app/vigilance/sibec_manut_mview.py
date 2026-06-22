"""Materialized view vig.mvw_sibec_manut_familia_mes — uma linha por família × competência.

Grão analítico: eventos SIBEC no nível família (NIVEL_ACAO = 00), situação consolidada
pela última DT_HORA_ACAO do mês. Território via vig.mvw_familia (geo × CEP).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .familia_mview import _columns, _pick_column, _table_exists, ensure_vig_functions

MANUT_TABLE = "sibec__manutencoes"

COD_FAM_CANDIDATES = (
    "cod_familiar",
    "cod_familiar_fam",
    "d_cod_familiar_fam",
    "codigo_familiar",
)
NIS_CANDIDATES = ("nis", "num_nis", "p_num_nis_pessoa_atual")
CPF_CANDIDATES = ("cpf", "num_cpf", "p_num_cpf_pessoa")
NIVEL_CANDIDATES = ("nivel_acao", "nivel")
DT_CANDIDATES = ("dt_hora_acao", "data_hora_acao", "dt_acao")
ACAO_CANDIDATES = ("acao",)
MOTIVO_COD_CANDIDATES = ("cod_motivo",)
MOTIVO_TXT_CANDIDATES = ("motivo",)
SIT_CANDIDATES = ("sit_resultante", "situacao_resultante")
REF_CANDIDATES = ("ref_folha", "ref_folha_pbf", "competencia")


def _qi(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


@dataclass
class SibecManutRefreshResult:
    row_count: int
    competencias: list[str]
    warnings: list[str]


def _acao_grupo_expr(acao_col: str) -> str:
    a = f"NULLIF(upper(btrim(COALESCE({_qi(acao_col)}::text, ''))), '')"
    return f"""
    CASE
      WHEN {a} LIKE '%CANCEL%' THEN 'Cancelar'
      WHEN {a} LIKE '%BLOQUE%' THEN 'Bloquear'
      WHEN {a} LIKE '%SUSPEN%' THEN 'Suspender'
      WHEN {a} LIKE '%ENCERR%' THEN 'Encerrar'
      WHEN {a} LIKE '%EXCLU%' THEN 'Excluir'
      WHEN {a} LIKE '%REVERTER%' THEN 'Reverter'
      WHEN {a} LIKE '%DESBLOQUE%' THEN 'Desbloquear'
      ELSE 'Outros'
    END
    """


def _competencia_expr(*, competencia_col: str | None, ref_col: str | None) -> str:
    parts: list[str] = []
    if competencia_col:
        parts.append(f"btrim(COALESCE({_qi(competencia_col)}::text, ''))")
    if ref_col and ref_col != competencia_col:
        parts.append(f"btrim(COALESCE({_qi(ref_col)}::text, ''))")
    if not parts:
        return "NULL::text"
    if len(parts) == 1:
        return f"NULLIF({parts[0]}, '')"
    return f"NULLIF(COALESCE({parts[0]}, {parts[1]}), '')"


def build_sibec_manut_mview_sql(
    *,
    cols: set[str],
    cod_col: str,
    nis_col: str | None,
    cpf_col: str | None,
    nivel_col: str | None,
    dt_col: str,
    acao_col: str,
    motivo_cod_col: str | None,
    motivo_txt_col: str | None,
    sit_col: str | None,
    competencia_col: str | None,
    ref_col: str | None,
    use_pessoas: bool,
) -> str:
    comp_expr = _competencia_expr(competencia_col=competencia_col, ref_col=ref_col)
    cod_direct = f"vig.norm_familia_cod(COALESCE({_qi(cod_col)}::text, ''))"
    nis_expr = (
        f"vig.norm_nis(COALESCE({_qi(nis_col)}::text, ''))" if nis_col else "NULL::text"
    )
    cpf_expr = (
        f"""CASE
          WHEN regexp_replace(COALESCE({_qi(cpf_col)}::text, ''), '[^0-9]', '', 'g') ~ '^[0-9]{{11}}$'
          THEN lpad(regexp_replace(COALESCE({_qi(cpf_col)}::text, ''), '[^0-9]', '', 'g'), 11, '0')
          ELSE NULL
        END"""
        if cpf_col
        else "NULL::text"
    )
    acao_txt = f"NULLIF(upper(btrim(COALESCE({_qi(acao_col)}::text, ''))), '')"
    dt_parse = f"""
    COALESCE(
      to_timestamp(btrim(COALESCE({_qi(dt_col)}::text, '')), 'DD/MM/YYYY HH24:MI:SS'),
      to_timestamp(btrim(COALESCE({_qi(dt_col)}::text, '')), 'DD/MM/YYYY HH24:MI:SS'),
      vig.parse_cadu_date({_qi(dt_col)}::text)::timestamp
    )
    """
    motivo_cod_out = (
        f"btrim(COALESCE({_qi(motivo_cod_col)}::text, ''))" if motivo_cod_col else "NULL::text"
    )
    motivo_txt_out = (
        f"btrim(COALESCE({_qi(motivo_txt_col)}::text, ''))" if motivo_txt_col else "NULL::text"
    )
    sit_out = f"btrim(COALESCE({_qi(sit_col)}::text, ''))" if sit_col else "NULL::text"

    nivel_filter = ""
    if nivel_col:
        nivel_filter = f"AND btrim(COALESCE({_qi(nivel_col)}::text, '')) = '00'"

    nis_join = ""
    cpf_join = ""
    cod_resolved = "e.cod_fam_direct"
    origem_parts = [
        "WHEN e.cod_fam_direct IS NOT NULL THEN 'cod_familiar'",
    ]

    if use_pessoas and nis_col:
        nis_join = """
      LEFT JOIN vig.mvw_pessoas pn
        ON pn.num_nis = e.nis_norm
       AND e.cod_fam_direct IS NULL
        """
        cod_resolved = "COALESCE(e.cod_fam_direct, pn.codigo_familiar)"
        origem_parts.append("WHEN pn.codigo_familiar IS NOT NULL THEN 'nis'")

    if use_pessoas and cpf_col:
        cpf_join = """
      LEFT JOIN vig.mvw_pessoas pc
        ON pc.num_cpf = e.cpf_norm
       AND e.cod_fam_direct IS NULL
       AND pn.codigo_familiar IS NULL
        """ if nis_col else """
      LEFT JOIN vig.mvw_pessoas pc
        ON pc.num_cpf = e.cpf_norm
       AND e.cod_fam_direct IS NULL
        """
        if nis_col:
            cod_resolved = "COALESCE(e.cod_fam_direct, pn.codigo_familiar, pc.codigo_familiar)"
            origem_parts.append("WHEN pc.codigo_familiar IS NOT NULL THEN 'cpf'")
        else:
            cod_resolved = "COALESCE(e.cod_fam_direct, pc.codigo_familiar)"
            origem_parts.append("WHEN pc.codigo_familiar IS NOT NULL THEN 'cpf'")

    origem_vinculo = "CASE\n      " + "\n      ".join(origem_parts) + "\n      ELSE 'sem_vinculo'\n    END"

    acao_grupo_last = """
    CASE
      WHEN l.acao_txt LIKE '%CANCEL%' THEN 'Cancelar'
      WHEN l.acao_txt LIKE '%BLOQUE%' THEN 'Bloquear'
      WHEN l.acao_txt LIKE '%SUSPEN%' THEN 'Suspender'
      WHEN l.acao_txt LIKE '%ENCERR%' THEN 'Encerrar'
      WHEN l.acao_txt LIKE '%EXCLU%' THEN 'Excluir'
      WHEN l.acao_txt LIKE '%REVERTER%' THEN 'Reverter'
      WHEN l.acao_txt LIKE '%DESBLOQUE%' THEN 'Desbloquear'
      ELSE 'Outros'
    END
    """

    sql = f"""
    CREATE MATERIALIZED VIEW vig.mvw_sibec_manut_familia_mes AS
    WITH raw_events AS (
      SELECT
        {comp_expr} AS competencia,
        {cod_direct} AS cod_fam_direct,
        {nis_expr} AS nis_norm,
        {cpf_expr} AS cpf_norm,
        {acao_txt} AS acao_txt,
        {dt_parse} AS dt_acao,
        {motivo_cod_out} AS cod_motivo,
        {motivo_txt_out} AS motivo_txt,
        {sit_out} AS sit_resultante
      FROM raw.{_qi(MANUT_TABLE)} m
      WHERE {comp_expr} IS NOT NULL
        AND {acao_txt} IS NOT NULL
        {nivel_filter}
    ),
    resolved AS (
      SELECT
        e.competencia,
        {cod_resolved} AS codigo_familiar,
        {origem_vinculo} AS origem_vinculo,
        e.acao_txt,
        e.dt_acao,
        e.cod_motivo,
        e.motivo_txt,
        e.sit_resultante
      FROM raw_events e
      {nis_join}
      {cpf_join}
    ),
    valid AS (
      SELECT * FROM resolved
      WHERE codigo_familiar IS NOT NULL
    ),
    flags AS (
      SELECT
        competencia,
        codigo_familiar,
        COUNT(*)::int AS n_eventos_nivel_familia,
        BOOL_OR(acao_txt LIKE '%REVERTER%') AS teve_reversao,
        BOOL_OR(acao_txt LIKE '%BLOQUE%') AS teve_bloqueio,
        BOOL_OR(acao_txt LIKE '%CANCEL%') AS teve_cancelamento,
        BOOL_OR(acao_txt LIKE '%SUSPEN%') AS teve_suspensao,
        BOOL_OR(acao_txt LIKE '%EXCLU%') AS teve_exclusao,
        BOOL_OR(acao_txt LIKE '%DESBLOQUE%') AS teve_desbloqueio
      FROM valid
      GROUP BY competencia, codigo_familiar
    ),
    ranked AS (
      SELECT
        v.*,
        ROW_NUMBER() OVER (
          PARTITION BY v.competencia, v.codigo_familiar
          ORDER BY v.dt_acao DESC NULLS LAST, v.acao_txt
        ) AS rn
      FROM valid v
    ),
    last_evt AS (
      SELECT * FROM ranked WHERE rn = 1
    )
    SELECT
      l.competencia,
      l.codigo_familiar,
      l.origem_vinculo,
      l.acao_txt AS acao_principal,
      {acao_grupo_last} AS acao_grupo,
      l.sit_resultante,
      l.cod_motivo,
      l.motivo_txt,
      l.dt_acao AS dt_hora_ultima_acao,
      fl.n_eventos_nivel_familia,
      fl.teve_reversao,
      fl.teve_bloqueio,
      fl.teve_cancelamento,
      fl.teve_suspensao,
      fl.teve_exclusao,
      fl.teve_desbloqueio,
      fam.bairro,
      fam.num_cras,
      fam.nom_cras,
      fam.num_creas,
      fam.nom_creas,
      (fam.codigo_familiar IS NOT NULL) AS vinculo_cadu,
      (
        fam.codigo_familiar IS NOT NULL
        AND (
          (fam.num_cras IS NOT NULL AND btrim(fam.num_cras::text) <> '')
          OR (fam.nom_cras IS NOT NULL AND btrim(fam.nom_cras::text) <> '')
        )
      ) AS tem_territorio
    FROM last_evt l
    INNER JOIN flags fl
      ON fl.competencia = l.competencia AND fl.codigo_familiar = l.codigo_familiar
    LEFT JOIN vig.mvw_familia fam ON fam.codigo_familiar = l.codigo_familiar
    """
    return " ".join(sql.split())


def refresh_sibec_manut_mview(conn: Connection) -> SibecManutRefreshResult:
    """Recria vig.mvw_sibec_manut_familia_mes a partir de raw.sibec__manutencoes."""
    warnings: list[str] = []
    ensure_vig_functions(conn)

    if not _table_exists(conn, "raw", MANUT_TABLE):
        raise ValueError(
            "Tabela raw.sibec__manutencoes não encontrada. "
            "Ingeste os analíticos de manutenção SIBEC antes."
        )

    if not _table_exists(conn, "vig", "mvw_familia"):
        raise ValueError(
            "vig.mvw_familia ausente. Gere a visão Família antes da MV SIBEC Manutenções."
        )

    cols = _columns(conn, "raw", MANUT_TABLE)
    cod_col = _pick_column(cols, COD_FAM_CANDIDATES)
    dt_col = _pick_column(cols, DT_CANDIDATES)
    acao_col = _pick_column(cols, ACAO_CANDIDATES)
    if not cod_col or not dt_col or not acao_col:
        raise ValueError(
            "Colunas mínimas ausentes em raw.sibec__manutencoes "
            "(cod_familiar, dt_hora_acao, acao)."
        )

    nivel_col = _pick_column(cols, NIVEL_CANDIDATES)
    if not nivel_col:
        warnings.append(
            "Coluna nivel_acao não encontrada: a MV incluirá todas as linhas "
            "(risco de duplicar famílias). Reingira o CSV SIBEC padrão."
        )

    competencia_col = "competencia" if "competencia" in cols else None
    ref_col = _pick_column(cols, REF_CANDIDATES)
    if not competencia_col and not ref_col:
        raise ValueError("Sem coluna competencia ou ref_folha na tabela de manutenções.")

    use_pessoas = _table_exists(conn, "vig", "mvw_pessoas")
    if not use_pessoas:
        warnings.append(
            "vig.mvw_pessoas ausente: vínculo secundário por NIS/CPF desativado."
        )

    nis_col = _pick_column(cols, NIS_CANDIDATES) if use_pessoas else None
    cpf_col = _pick_column(cols, CPF_CANDIDATES) if use_pessoas else None
    motivo_cod_col = _pick_column(cols, MOTIVO_COD_CANDIDATES)
    motivo_txt_col = _pick_column(cols, MOTIVO_TXT_CANDIDATES)
    sit_col = _pick_column(cols, SIT_CANDIDATES)

    mview_sql = build_sibec_manut_mview_sql(
        cols=cols,
        cod_col=cod_col,
        nis_col=nis_col,
        cpf_col=cpf_col,
        nivel_col=nivel_col,
        dt_col=dt_col,
        acao_col=acao_col,
        motivo_cod_col=motivo_cod_col,
        motivo_txt_col=motivo_txt_col,
        sit_col=sit_col,
        competencia_col=competencia_col,
        ref_col=ref_col,
        use_pessoas=use_pessoas,
    )

    conn.execute(text("DROP MATERIALIZED VIEW IF EXISTS vig.mvw_sibec_manut_familia_mes CASCADE"))
    conn.execute(text(mview_sql))
    conn.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS mvw_sibec_manut_fam_mes_uq
              ON vig.mvw_sibec_manut_familia_mes (competencia, codigo_familiar)
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS mvw_sibec_manut_fam_mes_cras_idx
              ON vig.mvw_sibec_manut_familia_mes (competencia, num_cras)
            """
        )
    )

    row_count = int(conn.execute(text("SELECT COUNT(*) FROM vig.mvw_sibec_manut_familia_mes")).scalar() or 0)
    comp_rows = conn.execute(
        text(
            """
            SELECT DISTINCT competencia
            FROM vig.mvw_sibec_manut_familia_mes
            WHERE competencia IS NOT NULL
            ORDER BY competencia DESC
            """
        )
    ).all()
    competencias = [str(r[0]) for r in comp_rows if r[0]]

    warnings.append(
        "Grão: 1 linha por (competencia, codigo_familiar) no nível família (NIVEL_ACAO=00), "
        "ação principal = última do mês. KPIs territoriais usam DISTINCT família."
    )

    return SibecManutRefreshResult(
        row_count=row_count,
        competencias=competencias,
        warnings=warnings,
    )


def latest_manut_competencia(conn: Connection) -> str | None:
    """Última competência disponível na MV ou, em fallback, na RAW."""
    if _table_exists(conn, "vig", "mvw_sibec_manut_familia_mes"):
        val = conn.execute(
            text(
                """
                SELECT competencia
                FROM vig.mvw_sibec_manut_familia_mes
                WHERE competencia IS NOT NULL
                ORDER BY competencia DESC
                LIMIT 1
                """
            )
        ).scalar()
        if val:
            return str(val)

    if not _table_exists(conn, "raw", MANUT_TABLE):
        return None

    cols = _columns(conn, "raw", MANUT_TABLE)
    if "competencia" in cols:
        val = conn.execute(
            text(
                f"""
                SELECT competencia FROM raw.{_qi(MANUT_TABLE)}
                WHERE competencia IS NOT NULL AND btrim(competencia) <> ''
                ORDER BY competencia DESC LIMIT 1
                """
            )
        ).scalar()
        if val:
            return str(val)

    ref_col = _pick_column(cols, REF_CANDIDATES)
    if ref_col:
        val = conn.execute(
            text(
                f"""
                SELECT {_qi(ref_col)} FROM raw.{_qi(MANUT_TABLE)}
                WHERE {_qi(ref_col)} IS NOT NULL AND btrim({_qi(ref_col)}::text) <> ''
                ORDER BY {_qi(ref_col)} DESC LIMIT 1
                """
            )
        ).scalar()
        if val:
            return str(val)
    return None
