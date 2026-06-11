import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import User
from ..ivs.ivs_familia import refresh_ivs_familia
from ..vigilance.domicilio_mview import refresh_domicilio_mview
from ..vigilance.familia_mview import (
    bolsa_folha_kpis_from_raw,
    ensure_vig_functions,
    refresh_familia_mview,
)
from ..vigilance.pessoas_mview import refresh_pessoas_mview

router = APIRouter(prefix="/vigilance", tags=["vigilance"])


def _require_ivs_mview(conn) -> None:
    if not conn.execute(text("SELECT to_regclass('core.mvw_ivs_familia')")).scalar():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="IVS não calculado. Execute POST /vigilance/materialized-views/ivs/refresh.",
        )


def _ivs_resumo_sql(*, num_cras: str | None, bairro: str | None) -> tuple[str, dict]:
    clauses = ["1=1"]
    params: dict = {}
    if num_cras is not None:
        clauses.append("f.num_cras = :num_cras")
        params["num_cras"] = num_cras
    if bairro is not None and bairro.strip():
        clauses.append("f.bairro ILIKE :bairro")
        params["bairro"] = f"%{bairro.strip()}%"
    where = " AND ".join(clauses)
    sql = f"""
        SELECT
          COUNT(*) FILTER (WHERE i.elegivel_ivs)::bigint AS familias_elegiveis,
          COUNT(*)::bigint AS familias_total,
          ROUND(AVG(i.ivs) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS ivs_medio,
          ROUND(AVG(i.idx_nc) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS idx_nc,
          ROUND(AVG(i.idx_dpi) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS idx_dpi,
          ROUND(AVG(i.idx_dca) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS idx_dca,
          ROUND(AVG(i.idx_tqa) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS idx_tqa,
          ROUND(AVG(i.idx_dr) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS idx_dr,
          ROUND(AVG(i.idx_ch) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS idx_ch
        FROM core.mvw_ivs_familia i
        INNER JOIN vig.mvw_familia f ON f.codigo_familiar = i.codigo_familiar
        WHERE {where}
    """
    return sql, params

# Painel: manutenções SIBEC — março/2026 (competência AAAAMM da ingestão).
MANUT_KPI_COMPETENCIA = "202603"

# Ordem fixa das colunas no painel (tabela por CRAS).
CRAS_MANUT_GRUPOS: tuple[str, ...] = ("Cancelar", "Bloquear", "Suspender", "Encerrar", "Excluir")


def _qi(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def _pick_column(cols: set[str], candidates: tuple[str, ...]) -> str | None:
    for c in candidates:
        if c in cols:
            return c
    lower_map = {x.lower(): x for x in cols}
    for c in candidates:
        if c.lower() in lower_map:
            return lower_map[c.lower()]
    return None


def _manutencoes_kpis_from_raw(conn, competencia: str) -> dict:
    """Conta linhas de manutenção por tipo de ação e famílias distintas (código familiar normalizado)."""
    ensure_vig_functions(conn)
    table_name = conn.execute(
        text(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'raw'
              AND table_name LIKE '%__manutencoes'
            ORDER BY table_name
            LIMIT 1
            """
        )
    ).scalar()
    if not table_name:
        return {
            "competencia": competencia,
            "total_acoes": 0,
            "familias_distintas": 0,
            "por_acao": [],
            "por_cras": [],
        }

    cols_rows = conn.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'raw' AND table_name = :t
            """
        ),
        {"t": table_name},
    ).all()
    cols = {r[0] for r in cols_rows}
    fam_col = _pick_column(
        cols,
        ("cod_familiar", "cod_familiar_fam", "d_cod_familiar_fam", "codigo_familiar"),
    )
    acao_col = _pick_column(cols, ("acao",))
    ref_col = _pick_column(cols, ("ref_folha", "ref_folha_pbf", "competencia"))

    if not fam_col or not acao_col:
        return {
            "competencia": competencia,
            "total_acoes": 0,
            "familias_distintas": 0,
            "por_acao": [],
            "por_cras": [],
        }

    if "competencia" in cols:
        filtro_mes = f"btrim(COALESCE({_qi('competencia')}::text, '')) = btrim(:competencia)"
    elif ref_col:
        filtro_mes = f"btrim(COALESCE({_qi(ref_col)}::text, '')) = btrim(:competencia)"
    else:
        return {
            "competencia": competencia,
            "total_acoes": 0,
            "familias_distintas": 0,
            "por_acao": [],
            "por_cras": [],
        }

    # Código familiar: ::text força varchar; norm_familia_cod remove não-dígitos e zeros à esquerda.
    fam_expr = f"vig.norm_familia_cod(COALESCE({_qi(fam_col)}::text, ''))"
    base_cte = f"""
    WITH m AS (
      SELECT
        {fam_expr} AS cod_fam,
        NULLIF(upper(btrim(COALESCE({_qi(acao_col)}::text, ''))), '') AS acao_txt
      FROM raw.{_qi(table_name)} m
      WHERE {filtro_mes}
    )
    """
    row_tot = conn.execute(
        text(
            base_cte
            + """
    SELECT
      COUNT(*)::bigint AS total_acoes,
      COUNT(DISTINCT cod_fam) FILTER (WHERE cod_fam IS NOT NULL)::bigint AS familias_distintas
    FROM m
    WHERE acao_txt IS NOT NULL
    """
        ),
        {"competencia": competencia},
    ).mappings().first() or {}
    total = int(row_tot.get("total_acoes") or 0)
    n_fam_tot = int(row_tot.get("familias_distintas") or 0)

    detail_rows = conn.execute(
        text(
            base_cte
            + """
    SELECT
      acao_txt,
      COUNT(*)::bigint AS n_lin,
      COUNT(DISTINCT cod_fam) FILTER (WHERE cod_fam IS NOT NULL)::bigint AS n_fam
    FROM m
    WHERE acao_txt IS NOT NULL
    GROUP BY acao_txt
    ORDER BY n_lin DESC, acao_txt
    """
        ),
        {"competencia": competencia},
    ).mappings().all()

    def pct_part(n: int, den: int) -> float:
        if den <= 0:
            return 0.0
        return round((n / den) * 100, 2)

    por_acao = []
    for r in detail_rows:
        label = str(r.get("acao_txt") or "").strip()
        linhas = int(r.get("n_lin") or 0)
        n_fam = int(r.get("n_fam") or 0)
        por_acao.append(
            {
                "acao": label,
                "linhas": linhas,
                "pct_linhas": pct_part(linhas, total),
                "familias_distintas": n_fam,
                "pct_familias": pct_part(n_fam, n_fam_tot),
            }
        )

    por_cras: list[dict] = []
    mvw_ok = conn.execute(text("SELECT to_regclass('vig.mvw_familia')")).scalar()
    if mvw_ok:
        por_cras = _manutencoes_por_cras_cadu(
            conn,
            competencia=competencia,
            table_name=table_name,
            fam_col=fam_col,
            acao_col=acao_col,
            filtro_mes=filtro_mes,
        )

    return {
        "competencia": competencia,
        "total_acoes": total,
        "familias_distintas": n_fam_tot,
        "por_acao": por_acao,
        "por_cras": por_cras,
    }


def _manutencoes_por_cras_cadu(
    conn,
    *,
    competencia: str,
    table_name: str,
    fam_col: str,
    acao_col: str,
    filtro_mes: str,
) -> list[dict]:
    """
    Manutenções com código familiar presente no CADU (vig.mvw_familia), apenas famílias com
    referência de CRAS (código ou nome territorial). Ações mapeadas aos grupos:
    Cancelar, Bloquear, Suspender, Encerrar, Excluir (via substring na descrição da ação).
    Por CRAS, retorna sempre os cinco grupos (zeros onde não houver ocorrência).
    """
    fam_expr = f"vig.norm_familia_cod(COALESCE({_qi(fam_col)}::text, ''))"
    sql = f"""
    WITH m AS (
      SELECT
        {fam_expr} AS cod_fam,
        NULLIF(upper(btrim(COALESCE({_qi(acao_col)}::text, ''))), '') AS acao_txt
      FROM raw.{_qi(table_name)} m
      WHERE {filtro_mes}
    ),
    mb AS (
      SELECT
        cod_fam,
        CASE
          WHEN acao_txt LIKE '%CANCEL%' THEN 'Cancelar'
          WHEN acao_txt LIKE '%BLOQUE%' THEN 'Bloquear'
          WHEN acao_txt LIKE '%SUSPEN%' THEN 'Suspender'
          WHEN acao_txt LIKE '%ENCERR%' THEN 'Encerrar'
          WHEN acao_txt LIKE '%EXCLU%' THEN 'Excluir'
          ELSE NULL
        END AS acao_grupo
      FROM m
      WHERE acao_txt IS NOT NULL AND cod_fam IS NOT NULL
    ),
    j AS (
      SELECT
        f.num_cras,
        f.nom_cras,
        mb.cod_fam,
        mb.acao_grupo
      FROM mb
      INNER JOIN vig.mvw_familia f ON f.codigo_familiar = mb.cod_fam
      WHERE mb.acao_grupo IS NOT NULL
        AND (
          (f.num_cras IS NOT NULL AND btrim(f.num_cras::text) <> '')
          OR (f.nom_cras IS NOT NULL AND btrim(f.nom_cras::text) <> '')
        )
    ),
    agg AS (
      SELECT
        btrim(COALESCE(num_cras::text, '')) AS num_cras,
        btrim(COALESCE(nom_cras::text, '')) AS nom_cras,
        acao_grupo,
        COUNT(DISTINCT cod_fam)::bigint AS n_fam
      FROM j
      GROUP BY 1, 2, 3
    ),
    tot AS (
      SELECT
        btrim(COALESCE(num_cras::text, '')) AS num_cras,
        btrim(COALESCE(nom_cras::text, '')) AS nom_cras,
        COUNT(DISTINCT cod_fam)::bigint AS n_fam_cras
      FROM j
      GROUP BY 1, 2
    )
    SELECT
      a.num_cras,
      a.nom_cras,
      a.acao_grupo,
      a.n_fam,
      t.n_fam_cras
    FROM agg a
    INNER JOIN tot t ON t.num_cras = a.num_cras AND t.nom_cras = a.nom_cras
    ORDER BY t.n_fam_cras DESC, a.num_cras, a.nom_cras, a.n_fam DESC, a.acao_grupo
    """
    rows = conn.execute(text(sql), {"competencia": competencia}).mappings().all()

    def pct_part(n: int, den: int) -> float:
        if den <= 0:
            return 0.0
        return round((n / den) * 100, 2)

    counts: dict[tuple[str, str], dict[str, int]] = defaultdict(dict)
    totals: dict[tuple[str, str], int] = {}
    for r in rows:
        key = (str(r.get("num_cras") or ""), str(r.get("nom_cras") or ""))
        totals[key] = int(r.get("n_fam_cras") or 0)
        grupo = str(r.get("acao_grupo") or "").strip()
        counts[key][grupo] = int(r.get("n_fam") or 0)

    out: list[dict] = []
    for key in sorted(counts.keys(), key=lambda k: -totals.get(k, 0)):
        num_cras, nom_cras = key
        tot_cras = totals.get(key, 0)
        grupos_list = []
        for g in CRAS_MANUT_GRUPOS:
            n = int(counts[key].get(g, 0))
            grupos_list.append(
                {
                    "grupo": g,
                    "familias_distintas": n,
                    "pct_sobre_manut_cras": pct_part(n, tot_cras),
                }
            )
        out.append(
            {
                "num_cras": num_cras,
                "nom_cras": nom_cras,
                "familias_com_manutencao": tot_cras,
                "top_grupos": grupos_list,
            }
        )
    return out


def _bpc_kpis_from_raw(conn) -> tuple[int, int, int]:
    table_name = conn.execute(
        text(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'raw'
              AND table_name LIKE '%__beneficio_prestacao_continuada'
            ORDER BY table_name
            LIMIT 1
            """
        )
    ).scalar()
    if not table_name:
        return 0, 0, 0

    cols_rows = conn.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'raw' AND table_name = :t
            """
        ),
        {"t": table_name},
    ).all()
    cols = {r[0] for r in cols_rows}
    especie_col = _pick_column(cols, ("especie_ben", "especie_beneficio", "especie"))
    situacao_col = _pick_column(cols, ("situacao", "status", "situacao_beneficio"))
    ben_col = _pick_column(cols, ("numero_beneficio", "num_beneficio", "beneficio", "nb"))

    if not especie_col:
        return 0, 0, 0

    situacao_filter = ""
    if situacao_col:
        situacao_filter = f"WHERE UPPER(COALESCE(b.{_qi(situacao_col)}::text, '')) = 'ATIVO'"

    beneficio_expr = "NULL"
    if ben_col:
        beneficio_expr = f"NULLIF(regexp_replace(COALESCE(b.{_qi(ben_col)}::text, ''), '[^0-9]', '', 'g'), '')"

    sql = f"""
    WITH b AS (
      SELECT * FROM raw.{_qi(table_name)} b
      {situacao_filter}
    ),
    d AS (
      SELECT
        {beneficio_expr} AS beneficio_id,
        UPPER(COALESCE(b.{_qi(especie_col)}::text, '')) AS especie_txt
      FROM b
    )
    SELECT
      COUNT(DISTINCT COALESCE(beneficio_id, especie_txt))::bigint AS total_bpc,
      COUNT(DISTINCT CASE
        WHEN especie_txt LIKE '%IDOSO%' THEN COALESCE(beneficio_id, especie_txt)
      END)::bigint AS total_bpc_idoso,
      COUNT(DISTINCT CASE
        WHEN especie_txt LIKE '%DEFIC%' OR especie_txt LIKE '%RMV%' THEN COALESCE(beneficio_id, especie_txt)
      END)::bigint AS total_bpc_deficiente
    FROM d
    """
    row = conn.execute(text(sql)).mappings().first() or {}
    return (
        int(row.get("total_bpc") or 0),
        int(row.get("total_bpc_idoso") or 0),
        int(row.get("total_bpc_deficiente") or 0),
    )


@router.get("/kpis")
def get_vigilance_kpis(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    KPIs iniciais da vigilância:
    - total_familias (vig.mvw_familia)
    - total_pessoas (vig.mvw_pessoas)
    - total_homens / total_mulheres + percentual sobre total de pessoas
    - Bolsa Família: contagem e valores direto de raw.sibec__programa_bolsa_familia (igual agregação da MV).
    - % Bolsa sobre CADU: usa total_familias da vig.mvw_familia; TAC continua na MV.
    """
    with db.bind.begin() as conn:
        familias_exists = conn.execute(text("SELECT to_regclass('vig.mvw_familia')")).scalar()
        pessoas_exists = conn.execute(text("SELECT to_regclass('vig.mvw_pessoas')")).scalar()
        if not familias_exists or not pessoas_exists:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Views necessárias não encontradas. Gere primeiro vig.mvw_familia e vig.mvw_pessoas "
                    "na página Dados vigilância."
                ),
            )

        fam_row = conn.execute(
            text(
                """
                SELECT
                  COUNT(*)::bigint AS n_fam,
                  COUNT(*) FILTER (
                    WHERE meses_desatualizado IS NOT NULL AND meses_desatualizado <= 24
                  )::bigint AS n_tac,
                  COUNT(*) FILTER (
                    WHERE
                      meses_desatualizado IS NOT NULL
                      AND meses_desatualizado <= 24
                      AND renda_per_capita IS NOT NULL
                      AND renda_per_capita >= 0
                      AND renda_per_capita <= 218
                  )::bigint AS n_renda_ate_218,
                  COUNT(*) FILTER (
                    WHERE
                      meses_desatualizado IS NOT NULL
                      AND meses_desatualizado <= 24
                      AND renda_per_capita IS NOT NULL
                      AND renda_per_capita >= 219
                      AND renda_per_capita <= 706
                  )::bigint AS n_renda_219_706,
                  COUNT(*) FILTER (
                    WHERE
                      meses_desatualizado IS NOT NULL
                      AND meses_desatualizado <= 24
                      AND renda_per_capita IS NOT NULL
                      AND renda_per_capita > 706
                  )::bigint AS n_renda_acima_706
                FROM vig.mvw_familia
                """
            )
        ).mappings().first()
        fr = fam_row or {}
        total_familias = int(fr.get("n_fam") or 0)
        tac_familias = int(fr.get("n_tac") or 0)
        renda_ate_218_familias = int(fr.get("n_renda_ate_218") or 0)
        renda_219_706_familias = int(fr.get("n_renda_219_706") or 0)
        renda_acima_706_familias = int(fr.get("n_renda_acima_706") or 0)

        bolsa = bolsa_folha_kpis_from_raw(conn)
        total_bolsa_familia = bolsa.total_familias_folha
        total_pago_bf = bolsa.total_pago
        total_bpc, total_bpc_idoso, total_bpc_deficiente = _bpc_kpis_from_raw(conn)
        manutencoes = _manutencoes_kpis_from_raw(conn, MANUT_KPI_COMPETENCIA)

        total_pessoas = int(conn.execute(text("SELECT COUNT(*) FROM vig.mvw_pessoas")).scalar() or 0)

        total_homens = int(
            conn.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM vig.mvw_pessoas
                    WHERE UPPER(COALESCE(cod_sexo, '')) IN ('1', 'M', 'MASCULINO')
                    """
                )
            ).scalar()
            or 0
        )
        total_mulheres = int(
            conn.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM vig.mvw_pessoas
                    WHERE UPPER(COALESCE(cod_sexo, '')) IN ('2', 'F', 'FEMININO')
                    """
                )
            ).scalar()
            or 0
        )

    def pct(value: int, total: int) -> float:
        if total <= 0:
            return 0.0
        return round((value / total) * 100, 2)

    media_valor_bf = (
        round(total_pago_bf / total_bolsa_familia, 2) if total_bolsa_familia > 0 else 0.0
    )

    n_fam_manut = int(manutencoes.get("familias_distintas") or 0)
    manutencoes = {
        **manutencoes,
        "pct_familias_manutencao_sobre_bolsa": pct(n_fam_manut, total_bolsa_familia),
    }

    return {
        "total_familias": total_familias,
        "total_pessoas": total_pessoas,
        "total_homens": total_homens,
        "pct_homens": pct(total_homens, total_pessoas),
        "total_mulheres": total_mulheres,
        "pct_mulheres": pct(total_mulheres, total_pessoas),
        "total_bolsa_familia": total_bolsa_familia,
        "pct_bolsa_familia_cadu": pct(total_bolsa_familia, total_familias),
        "tac_familias": tac_familias,
        "tac_pct": pct(tac_familias, total_familias),
        "total_pago_bolsa_familia": round(total_pago_bf, 2),
        "media_valor_bolsa_familia": media_valor_bf,
        "renda_ate_218_familias": renda_ate_218_familias,
        "renda_ate_218_pct": pct(renda_ate_218_familias, total_familias),
        "renda_219_706_familias": renda_219_706_familias,
        "renda_219_706_pct": pct(renda_219_706_familias, total_familias),
        "renda_acima_706_familias": renda_acima_706_familias,
        "renda_acima_706_pct": pct(renda_acima_706_familias, total_familias),
        "total_bpc": total_bpc,
        "total_bpc_idoso": total_bpc_idoso,
        "pct_bpc_idoso": pct(total_bpc_idoso, total_bpc),
        "total_bpc_deficiente": total_bpc_deficiente,
        "pct_bpc_deficiente": pct(total_bpc_deficiente, total_bpc),
        "manutencoes": manutencoes,
    }


@router.post("/materialized-views/familia/refresh")
def refresh_familia(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Recria a materialized view `vig.mvw_familia` (uma linha por código familiar).
    Pode levar vários segundos em bases grandes; o cliente deve exibir estado de carregamento.
    """
    t0 = time.perf_counter()
    try:
        with db.bind.begin() as conn:
            result = refresh_familia_mview(conn)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao gerar visão Família: {exc}",
        ) from exc

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    return {
        "status": "success",
        "view_schema": "vig",
        "view_name": "mvw_familia",
        "row_count": result.row_count,
        "elapsed_ms": elapsed_ms,
        "warnings": result.warnings,
        "pbf_columns_detected": {
            "codigo_familiar": result.pbf_cod_column,
            "valor": result.pbf_valor_column,
            "referencia_folha": result.pbf_ref_column,
        },
    }


@router.post("/materialized-views/familia-domicilio/refresh")
def refresh_familia_domicilio(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Recria `vig.mvw_familia_domicilio` (moradia, riscos, GPTE — uma linha por família, só CADU)."""
    t0 = time.perf_counter()
    try:
        with db.bind.begin() as conn:
            result = refresh_domicilio_mview(conn)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao gerar visão Domicílio: {exc}",
        ) from exc

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    return {
        "status": "success",
        "view_schema": "vig",
        "view_name": "mvw_familia_domicilio",
        "row_count": result.row_count,
        "elapsed_ms": elapsed_ms,
        "warnings": result.warnings,
    }


@router.post("/materialized-views/pessoas/refresh")
def refresh_pessoas(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Recria `vig.mvw_pessoas` (uma linha por membro no CADU, com idade calculada)."""
    t0 = time.perf_counter()
    try:
        with db.bind.begin() as conn:
            result = refresh_pessoas_mview(conn)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao gerar visão Pessoas: {exc}",
        ) from exc

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    return {
        "status": "success",
        "view_schema": "vig",
        "view_name": "mvw_pessoas",
        "row_count": result.row_count,
        "elapsed_ms": elapsed_ms,
        "warnings": result.warnings,
    }


@router.post("/materialized-views/refresh-all")
def refresh_all_materialized_views(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Recria tronco CADU (família, pessoas, domicílio) e em seguida core.mvw_ivs_familia."""
    t0 = time.perf_counter()
    steps: list[dict] = []
    all_warnings: list[str] = []

    try:
        with db.bind.begin() as conn:
            r = refresh_familia_mview(conn)
        steps.append(
            {
                "view": "vig.mvw_familia",
                "row_count": r.row_count,
                "warnings": r.warnings,
            }
        )
        all_warnings.extend(r.warnings)

        with db.bind.begin() as conn:
            r = refresh_pessoas_mview(conn)
        steps.append(
            {
                "view": "vig.mvw_pessoas",
                "row_count": r.row_count,
                "warnings": r.warnings,
            }
        )
        all_warnings.extend(r.warnings)

        with db.bind.begin() as conn:
            r = refresh_domicilio_mview(conn)
        steps.append(
            {
                "view": "vig.mvw_familia_domicilio",
                "row_count": r.row_count,
                "warnings": r.warnings,
            }
        )
        all_warnings.extend(r.warnings)

        with db.bind.begin() as conn:
            r = refresh_ivs_familia(conn)
        steps.append(
            {
                "view": "core.mvw_ivs_familia",
                "row_count": r.row_count,
                "elegivel_count": r.elegivel_count,
                "warnings": r.warnings,
            }
        )
        all_warnings.extend(r.warnings)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha no refresh em cadeia: {exc}",
        ) from exc

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    return {
        "status": "success",
        "elapsed_ms": elapsed_ms,
        "steps": steps,
        "warnings": all_warnings,
    }


@router.post("/materialized-views/ivs/refresh")
def refresh_ivs(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Recria `core.mvw_ivs_familia` — IVS (Índice de Vulnerabilidade Social, IVCAD v1.0.5)."""
    t0 = time.perf_counter()
    try:
        with db.bind.begin() as conn:
            result = refresh_ivs_familia(conn)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao calcular IVS: {exc}",
        ) from exc

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    return {
        "status": "success",
        "view_schema": "core",
        "view_name": "mvw_ivs_familia",
        "row_count": result.row_count,
        "elegivel_count": result.elegivel_count,
        "elapsed_ms": elapsed_ms,
        "warnings": result.warnings,
    }


@router.get("/ivs/resumo")
def get_ivs_resumo(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    num_cras: str | None = Query(None, description="Filtra por CRAS (vig.mvw_familia.num_cras)"),
    bairro: str | None = Query(None, description="Filtra por bairro (ILIKE parcial)"),
):
    """Médias IVS e dimensões no universo elegível (requer refresh prévio)."""
    with db.bind.begin() as conn:
        _require_ivs_mview(conn)
        sql, params = _ivs_resumo_sql(num_cras=num_cras, bairro=bairro)
        row = conn.execute(text(sql), params).mappings().first()
    out = dict(row or {})
    if num_cras is not None:
        out["num_cras"] = num_cras
    if bairro is not None and bairro.strip():
        out["bairro"] = bairro.strip()
    return out


@router.get("/ivs/por-cras")
def get_ivs_por_cras(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """IVS médio e dimensões por CRAS de referência (famílias elegíveis)."""
    with db.bind.begin() as conn:
        _require_ivs_mview(conn)
        rows = conn.execute(
            text(
                """
                SELECT
                  COALESCE(f.num_cras, '') AS num_cras,
                  COALESCE(NULLIF(btrim(f.nom_cras), ''), 'Sem referência territorial') AS nom_cras,
                  COUNT(*) FILTER (WHERE i.elegivel_ivs)::bigint AS familias_elegiveis,
                  ROUND(AVG(i.ivs) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS ivs_medio,
                  ROUND(AVG(i.idx_nc) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS idx_nc,
                  ROUND(AVG(i.idx_dpi) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS idx_dpi,
                  ROUND(AVG(i.idx_dca) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS idx_dca,
                  ROUND(AVG(i.idx_tqa) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS idx_tqa,
                  ROUND(AVG(i.idx_dr) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS idx_dr,
                  ROUND(AVG(i.idx_ch) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS idx_ch
                FROM core.mvw_ivs_familia i
                INNER JOIN vig.mvw_familia f ON f.codigo_familiar = i.codigo_familiar
                GROUP BY f.num_cras, f.nom_cras
                ORDER BY
                  NULLIF(regexp_replace(COALESCE(f.num_cras, ''), '[^0-9]', '', 'g'), '')::integer NULLS LAST,
                  f.nom_cras NULLS LAST
                """
            )
        ).mappings().all()
    return {"items": [dict(r) for r in rows]}
