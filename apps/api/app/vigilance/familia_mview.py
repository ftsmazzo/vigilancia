"""Materialized view vig.mvw_familia: uma linha por código familiar (CADU + folha PBF).

Territorialização (bairro, endereço, CRAS, lat/long) vem de raw.geo__tbl_geo via CEP quando a base
geo está ingerida. Campos *_cadu preservam o texto original do CADU para auditoria.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection

CADU_TABLE = "cecad__cadu"
PBF_TABLE = "sibec__programa_bolsa_familia"
GEO_TABLE = "geo__tbl_geo"

PBF_COD_CANDIDATES = (
    "cod_familiar",
    "cod_familiar_fam",
    "d_cod_familiar_fam",
    "codigo_familiar",
    "cod_familiar_familia",
)

PBF_VALOR_CANDIDATES = (
    "vlrtotal",
    "vlr_total",
    "vlr_total_fam",
    "valor_total",
    "vlr_parcela",
    "valor_parcela",
    "vlr_beneficio",
    "valor_beneficio",
    "vl_parcela",
    "val_parcela",
    "vlr_tot",
    "valor",
)

PBF_REF_CANDIDATES = (
    "competencia",
    "ref_folha",
    "ref_pbf",
    "inicio_vig_beneficio",
    "inicio_vig",
    "ref_competencia",
    "ano_mes_referencia",
)


def _qi(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def _table_exists(conn: Connection, schema: str, table: str) -> bool:
    """Tabelas RAW e também materialized views (não aparecem só em information_schema.tables)."""
    qualified = f"{schema}.{table}"
    r = conn.execute(
        text(
            """
            SELECT (
              to_regclass(:qualified) IS NOT NULL
              OR EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = :s AND table_name = :t
              )
            )
            """
        ),
        {"s": schema, "t": table, "qualified": qualified},
    ).scalar()
    return bool(r)


def _columns(conn: Connection, schema: str, table: str) -> set[str]:
    rows = conn.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = :s AND table_name = :t
            """
        ),
        {"s": schema, "t": table},
    ).all()
    return {r[0] for r in rows}


def _pick_column(cols: set[str], candidates: tuple[str, ...]) -> str | None:
    for c in candidates:
        if c in cols:
            return c
    lower_map = {x.lower(): x for x in cols}
    for c in candidates:
        if c.lower() in lower_map:
            return lower_map[c.lower()]
    return None


VIG_DDL_STATEMENTS: list[str] = [
    "CREATE SCHEMA IF NOT EXISTS vig",
    r"""
CREATE OR REPLACE FUNCTION vig.clean_spaces(t text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT NULLIF(
    trim(both ' ' FROM regexp_replace(coalesce(t, ''), '\s+', ' ', 'g')),
    ''
  )
$$;
""",
    r"""
CREATE OR REPLACE FUNCTION vig.only_digits(t text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE
    WHEN t IS NULL OR btrim(t) = '' THEN NULL
    ELSE regexp_replace(btrim(t), '[^0-9]', '', 'g')
  END
$$;
""",
    r"""
CREATE OR REPLACE FUNCTION vig.norm_familia_cod(t text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
  /* Somente dígitos, sem espaços internos; remove zeros à esquerda (ex.: SIBEC x CADU). */
  SELECT CASE
    WHEN vig.only_digits(vig.clean_spaces(t)) IS NULL THEN NULL
    WHEN trim(LEADING '0' FROM vig.only_digits(vig.clean_spaces(t))) = '' THEN '0'
    ELSE trim(LEADING '0' FROM vig.only_digits(vig.clean_spaces(t)))
  END
$$;
""",
    r"""
CREATE OR REPLACE FUNCTION vig.norm_cep(t text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE
    WHEN vig.only_digits(t) IS NULL THEN NULL
    ELSE lpad(vig.only_digits(t), 8, '0')
  END
$$;
""",
    r"""
CREATE OR REPLACE FUNCTION vig.norm_nis(t text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE
    WHEN vig.only_digits(t) IS NULL OR btrim(vig.only_digits(t)) = '' THEN NULL
    WHEN length(vig.only_digits(t)) > 11 THEN NULL
    ELSE lpad(vig.only_digits(t), 11, '0')
  END
$$;
""",
    r"""
CREATE OR REPLACE FUNCTION vig.ltrim_zeros_text(t text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE
    WHEN vig.clean_spaces(t) IS NULL THEN NULL
    WHEN trim(LEADING '0' FROM vig.clean_spaces(t)) = '' THEN '0'
    ELSE trim(LEADING '0' FROM vig.clean_spaces(t))
  END
$$;
""",
    r"""
CREATE OR REPLACE FUNCTION vig.parse_cadu_date(t text)
RETURNS date
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
  s text := vig.clean_spaces(t);
BEGIN
  IF s IS NULL THEN RETURN NULL; END IF;
  IF s ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN
    RETURN s::date;
  END IF;
  IF s ~ '^[0-9]{8}$' THEN
    RETURN to_date(s, 'YYYYMMDD');
  END IF;
  IF s ~ '^[0-9]{2}/[0-9]{2}/[0-9]{4}$' THEN
    RETURN to_date(s, 'DD/MM/YYYY');
  END IF;
  RETURN NULL;
EXCEPTION WHEN OTHERS THEN
  RETURN NULL;
END;
$$;
""",
    r"""
CREATE OR REPLACE FUNCTION vig.parse_money_br(t text)
RETURNS numeric
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
  s text := vig.clean_spaces(t);
BEGIN
  IF s IS NULL THEN RETURN NULL; END IF;
  IF s ~ '^[0-9]+$' THEN
    RETURN s::numeric;
  END IF;
  IF s ~ '^[0-9]{1,3}(\.[0-9]{3})*,[0-9]{2}$' THEN
    s := replace(replace(s, '.', ''), ',', '.');
    RETURN s::numeric;
  END IF;
  IF s ~ '^[0-9]+,[0-9]{1,2}$' THEN
    s := replace(s, ',', '.');
    RETURN s::numeric;
  END IF;
  RETURN NULL;
EXCEPTION WHEN OTHERS THEN
  RETURN NULL;
END;
$$;
""",
    r"""
CREATE OR REPLACE FUNCTION vig.meses_desde(atual date)
RETURNS integer
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE
    WHEN atual IS NULL THEN NULL
    ELSE (
      EXTRACT(YEAR FROM age(current_date, atual))::int * 12
      + EXTRACT(MONTH FROM age(current_date, atual))::int
    )
  END
$$;
""",
]


def ensure_vig_functions(conn: Connection) -> None:
    for stmt in VIG_DDL_STATEMENTS:
        conn.execute(text(stmt))


@dataclass
class FamiliaRefreshResult:
    row_count: int
    warnings: list[str]
    pbf_cod_column: str | None
    pbf_valor_column: str | None
    pbf_ref_column: str | None


def _cadu_required_columns() -> dict[str, str]:
    """Nome lógico -> coluna física esperada em raw.cecad__cadu (pós-normalização ingestão)."""
    return {
        "cod": "d_cod_familiar_fam",
        "cad": "d_dat_cadastramento_fam",
        "atual": "d_dat_atual_fam",
        "forma": "d_cod_forma_coleta_fam",
        "entrev": "d_dta_entrevista_fam",
        "bairro": "d_nom_localidade_fam",
        "tip_log": "d_nom_tip_logradouro_fam",
        "tit_log": "d_nom_titulo_logradouro_fam",
        "nom_log": "d_nom_logradouro_fam",
        "cep": "d_num_cep_logradouro_fam",
        "cras_cod": "d_cod_unidade_territorial_fam",
        "cras_nom": "d_nom_unidade_territorial_fam",
        "renda_pc": "d_vlr_renda_media_fam",
        "fx_rfpc": "d_fx_rfpc",
        "renda_tot": "d_vlr_renda_total_fam",
        "marc_pbf": "d_marc_pbf",
        "ref_cad": "d_ref_cad",
        "ref_pbf": "d_ref_pbf",
    }


def _validate_cadu_columns(cols: set[str]) -> None:
    req = _cadu_required_columns()
    optional = frozenset({"ref_cad", "ref_pbf"})
    missing = [
        logical for logical, phys in req.items() if logical not in optional and phys not in cols
    ]
    if missing:
        phys_missing = [req[m] for m in missing]
        raise ValueError(
            "Tabela raw.cecad__cadu sem colunas esperadas do CADU: "
            + ", ".join(phys_missing)
            + ". Recarregue o arquivo oficial (layout d.* / família)."
        )


def _cadu_col_expr(cols: set[str], key: str) -> str:
    phys = _cadu_required_columns()[key]
    if phys in cols:
        return f'{_qi(phys)}'
    return "NULL"


def _build_pbf_agg_subquery(
    *,
    pbf_cod: str | None,
    pbf_valor: str | None,
    pbf_ref: str | None,
) -> str:
    """CTE `pbf_agg`: uma linha por código familiar na folha PBF (mesma lógica da `vig.mvw_familia`)."""
    if not pbf_cod:
        return (
            "SELECT NULL::text AS codigo_familiar, NULL::numeric AS vlrtotal, "
            "NULL::boolean AS na_folha_pbf WHERE false"
        )
    if pbf_valor:
        ref_filter = ""
        if pbf_ref:
            ref_filter = f""" WHERE (
              ( SELECT MAX(btrim({_qi(pbf_ref)}::text))
                FROM raw.{_qi(PBF_TABLE)}
                WHERE {_qi(pbf_ref)} IS NOT NULL AND btrim({_qi(pbf_ref)}::text) <> ''
              ) IS NULL
              OR btrim({_qi(pbf_ref)}::text) = (
                SELECT MAX(btrim({_qi(pbf_ref)}::text))
                FROM raw.{_qi(PBF_TABLE)}
                WHERE {_qi(pbf_ref)} IS NOT NULL AND btrim({_qi(pbf_ref)}::text) <> ''
              )
            ) """
        return f"""
        SELECT
          vig.norm_familia_cod({_qi(pbf_cod)}::text) AS codigo_familiar,
          SUM(COALESCE(vig.parse_money_br({_qi(pbf_valor)}::text), 0))::numeric(14,2) AS vlrtotal,
          BOOL_OR(TRUE) AS na_folha_pbf
        FROM raw.{_qi(PBF_TABLE)}
        {ref_filter}
        GROUP BY 1
        HAVING vig.norm_familia_cod({_qi(pbf_cod)}::text) IS NOT NULL
        """
    return f"""
        SELECT DISTINCT ON (vig.norm_familia_cod({_qi(pbf_cod)}::text))
          vig.norm_familia_cod({_qi(pbf_cod)}::text) AS codigo_familiar,
          NULL::numeric AS vlrtotal,
          TRUE AS na_folha_pbf
        FROM raw.{_qi(PBF_TABLE)}
        WHERE vig.norm_familia_cod({_qi(pbf_cod)}::text) IS NOT NULL
        ORDER BY vig.norm_familia_cod({_qi(pbf_cod)}::text)
        """


@dataclass
class BolsaFolhaKpis:
    """Totais direto da folha em `raw`, sem filtrar pelo universo CADU."""

    total_familias_folha: int
    total_pago: float


def bolsa_folha_kpis_from_raw(conn: Connection) -> BolsaFolhaKpis:
    """Contagem de famílias distintas e soma de valores na folha PBF (última competência quando houver coluna)."""
    ensure_vig_functions(conn)
    if not _table_exists(conn, "raw", PBF_TABLE):
        return BolsaFolhaKpis(0, 0.0)
    cols = _columns(conn, "raw", PBF_TABLE)
    pbf_cod = _pick_column(cols, PBF_COD_CANDIDATES)
    pbf_valor = _pick_column(cols, PBF_VALOR_CANDIDATES)
    pbf_ref = _pick_column(cols, PBF_REF_CANDIDATES)
    inner = _build_pbf_agg_subquery(pbf_cod=pbf_cod, pbf_valor=pbf_valor, pbf_ref=pbf_ref)
    sql = f"""
    WITH pbf_agg AS (
      {inner}
    )
    SELECT
      COUNT(*)::bigint AS n_bf,
      COALESCE(SUM(vlrtotal), 0)::numeric AS total_pago
    FROM pbf_agg
    """
    row = conn.execute(text(sql)).mappings().first()
    fr = row or {}
    return BolsaFolhaKpis(
        total_familias_folha=int(fr.get("n_bf") or 0),
        total_pago=float(fr.get("total_pago") or 0),
    )


def build_familia_mview_sql(
    *,
    cadu_cols: set[str],
    pbf_cod: str | None,
    pbf_valor: str | None,
    pbf_ref: str | None,
    use_geo: bool = False,
) -> str:
    c = _cadu_required_columns()

    def qc(key: str) -> str:
        return f"{_cadu_col_expr(cadu_cols, key)}::text"

    pbf_subquery = _build_pbf_agg_subquery(pbf_cod=pbf_cod, pbf_valor=pbf_valor, pbf_ref=pbf_ref)

    # Endereço: tipos + título + logradouro, sanitizado
    endereco_expr = f"""vig.clean_spaces(
      concat_ws(
        ' ',
        NULLIF(vig.clean_spaces({qc('tip_log')}), ''),
        NULLIF(vig.clean_spaces({qc('tit_log')}), ''),
        NULLIF(vig.clean_spaces({qc('nom_log')}), '')
      )
    )"""

    geo_cte = ""
    geo_join = ""
    if use_geo:
        geo_cte = f""",
    geo_agg AS (
      SELECT
        g.cep_norm,
        mode() WITHIN GROUP (
          ORDER BY lower(NULLIF(btrim(g.bairro::text), ''))
        ) AS bairro,
        mode() WITHIN GROUP (
          ORDER BY lower(NULLIF(btrim(g.endereco::text), ''))
        ) AS endereco,
        mode() WITHIN GROUP (
          ORDER BY NULLIF(btrim(g.cras::text), '')
        ) AS cras,
        max(g.lat_num) AS lat_num,
        max(g.long_num) AS long_num
      FROM raw.{_qi(GEO_TABLE)} g
      WHERE g.cep_norm IS NOT NULL
        AND length(btrim(g.cep_norm::text)) = 8
      GROUP BY g.cep_norm
    )"""
        geo_join = "LEFT JOIN geo_agg g ON g.cep_norm = d.cep"

    if use_geo:
        bairro_out = "g.bairro"
        endereco_out = "g.endereco"
        num_cras_out = "vig.ltrim_zeros_text(g.cras::text)"
        nom_cras_out = """CASE
          WHEN g.cras IS NOT NULL AND btrim(g.cras::text) <> ''
          THEN 'CRAS ' || btrim(g.cras::text)
        END"""
        tem_geo_out = "(g.cep_norm IS NOT NULL)"
        lat_out = "g.lat_num"
        lng_out = "g.long_num"
    else:
        bairro_out = "d.bairro_cadu"
        endereco_out = "d.endereco_cadu"
        num_cras_out = "d.num_cras_cadu"
        nom_cras_out = "d.nom_cras_cadu"
        tem_geo_out = "FALSE"
        lat_out = "NULL::double precision"
        lng_out = "NULL::double precision"

    sql = f"""
    CREATE MATERIALIZED VIEW vig.mvw_familia AS
    WITH cadu_base AS (
      SELECT
        vig.norm_familia_cod({qc('cod')}) AS codigo_familiar,
        vig.parse_cadu_date({qc('cad')}) AS data_cadastro,
        vig.parse_cadu_date({qc('atual')}) AS data_atualizacao,
        vig.ltrim_zeros_text({qc('forma')}) AS tipo_coleta,
        vig.parse_cadu_date({qc('entrev')}) AS data_entrevista,
        vig.clean_spaces({qc('bairro')}) AS bairro_cadu,
        {endereco_expr} AS endereco_cadu,
        vig.norm_cep({qc('cep')}) AS cep,
        vig.ltrim_zeros_text({qc('cras_cod')}) AS num_cras_cadu,
        vig.clean_spaces({qc('cras_nom')}) AS nom_cras_cadu,
        vig.parse_money_br({qc('renda_pc')}) AS renda_per_capita,
        vig.ltrim_zeros_text({qc('fx_rfpc')}) AS faixa_renda,
        vig.parse_money_br({qc('renda_tot')}) AS renda_total,
        vig.ltrim_zeros_text({qc('marc_pbf')}) AS marc_pbf_cadu,
        vig.parse_cadu_date({qc('ref_cad')}) AS data_cadu,
        vig.parse_cadu_date({qc('ref_pbf')}) AS data_pbf
      FROM raw.{_qi(CADU_TABLE)}
      WHERE vig.norm_familia_cod({qc('cod')}) IS NOT NULL
    ),
    cadu_dedup AS (
      SELECT DISTINCT ON (codigo_familiar)
        codigo_familiar,
        data_cadastro,
        data_atualizacao,
        tipo_coleta,
        data_entrevista,
        bairro_cadu,
        endereco_cadu,
        cep,
        num_cras_cadu,
        nom_cras_cadu,
        renda_per_capita,
        faixa_renda,
        renda_total,
        marc_pbf_cadu,
        data_cadu,
        data_pbf
      FROM cadu_base
      ORDER BY
        codigo_familiar,
        data_atualizacao DESC NULLS LAST,
        data_cadastro DESC NULLS LAST
    ),
    pbf_agg AS (
      {pbf_subquery}
    ){geo_cte}
    SELECT
      d.codigo_familiar,
      d.data_cadastro,
      d.data_atualizacao,
      d.tipo_coleta,
      d.data_entrevista,
      {bairro_out} AS bairro,
      {endereco_out} AS endereco,
      d.cep,
      {num_cras_out} AS num_cras,
      {nom_cras_out} AS nom_cras,
      d.bairro_cadu,
      d.endereco_cadu,
      d.num_cras_cadu,
      d.nom_cras_cadu,
      {tem_geo_out} AS tem_geo,
      {lat_out} AS lat_num,
      {lng_out} AS long_num,
      d.renda_per_capita,
      d.faixa_renda,
      d.renda_total,
      COALESCE(p.na_folha_pbf, FALSE) AS marc_pbf,
      d.marc_pbf_cadu,
      p.vlrtotal,
      vig.meses_desde(d.data_atualizacao) AS meses_desatualizado,
      d.data_cadu,
      d.data_pbf
    FROM cadu_dedup d
    LEFT JOIN pbf_agg p ON p.codigo_familiar = d.codigo_familiar
    {geo_join}
    """
    return re.sub(r"\s+", " ", sql).strip()


def refresh_familia_mview(conn: Connection) -> FamiliaRefreshResult:
    warnings: list[str] = []
    ensure_vig_functions(conn)

    if not _table_exists(conn, "raw", CADU_TABLE):
        raise ValueError("Tabela raw.cecad__cadu não encontrada. Ingeste o CADU antes.")

    cadu_cols = _columns(conn, "raw", CADU_TABLE)
    _validate_cadu_columns(cadu_cols)

    pbf_cod = pbf_valor = pbf_ref = None
    if _table_exists(conn, "raw", PBF_TABLE):
        pbf_cols = _columns(conn, "raw", PBF_TABLE)
        pbf_cod = _pick_column(pbf_cols, PBF_COD_CANDIDATES)
        pbf_valor = _pick_column(pbf_cols, PBF_VALOR_CANDIDATES)
        pbf_ref = _pick_column(pbf_cols, PBF_REF_CANDIDATES)
        if not pbf_cod:
            warnings.append(
                "Folha Bolsa Família: não foi encontrada coluna de código familiar "
                f"(tente uma destas: {', '.join(PBF_COD_CANDIDATES)}). vlrtotal ficará vazio."
            )
        if pbf_cod and not pbf_valor:
            warnings.append(
                "Folha Bolsa Família: não foi encontrada coluna de valor total (esperado vlrtotal). "
                f"Procuradas: {', '.join(PBF_VALOR_CANDIDATES)}. vlrtotal ficará nulo."
            )
        if not pbf_ref:
            warnings.append(
                "Folha Bolsa Família: sem coluna competencia (ingestão por AAAAMM) nem outra referência de mês. "
                "Somando todas as linhas da tabela (pode duplicar meses). Nas próximas cargas use a competência no envio."
            )
    else:
        warnings.append(
            "Tabela raw.sibec__programa_bolsa_familia ausente. Gere a visão só com CADU; vlrtotal e marc_pbf (folha) virão nulos/falsos."
        )

    use_geo = _table_exists(conn, "raw", GEO_TABLE)
    if use_geo:
        warnings.append(
            "Território (bairro, endereço, CRAS, lat/long) vem de raw.geo__tbl_geo via CEP da família. "
            "Campos *_cadu preservam o texto original do CADU."
        )
    else:
        warnings.append(
            "Base geo ausente: bairro/CRAS/endereço continuam do CADU. "
            "Ingeste tbl_geo.csv e regenere esta visão para territorialização pela geo."
        )

    mview_sql = build_familia_mview_sql(
        cadu_cols=cadu_cols,
        pbf_cod=pbf_cod,
        pbf_valor=pbf_valor,
        pbf_ref=pbf_ref,
        use_geo=use_geo,
    )

    conn.execute(text("DROP MATERIALIZED VIEW IF EXISTS vig.mvw_familia CASCADE"))
    conn.execute(text(mview_sql))
    conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS mvw_familia_codigo_uq ON vig.mvw_familia (codigo_familiar)"
        )
    )

    row_count = conn.execute(text("SELECT COUNT(*) FROM vig.mvw_familia")).scalar() or 0

    return FamiliaRefreshResult(
        row_count=int(row_count),
        warnings=warnings,
        pbf_cod_column=pbf_cod,
        pbf_valor_column=pbf_valor,
        pbf_ref_column=pbf_ref,
    )
