"""Consultas analíticas RMA — produção mensal por equipamento oficial."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .familia_mview import _table_exists
from .rma_mview import RESUMO_MVIEW


def _qi(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def _comp_str(value) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()[:10]
    return str(value)[:10]


def _num(value) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _pct(part: int, whole: int) -> float:
    if whole <= 0:
        return 0.0
    return round(100.0 * part / whole, 1)


_METRICAS_POR_TIPO: dict[str, list[tuple[str, str]]] = {
    "CRAS": [
        ("cras_familias_paif", "Famílias em acompanhamento PAIF"),
        ("cras_novas_familias_paif", "Novas famílias PAIF"),
        ("cras_atend_individual", "Atendimentos individuais"),
        ("cras_visitas_domiciliares", "Visitas domiciliares"),
    ],
    "CREAS": [
        ("creas_casos_paefi", "Casos em acompanhamento PAEFI"),
        ("creas_novos_casos_paefi", "Novos casos PAEFI"),
        ("creas_atend_individual", "Atendimentos individuais"),
        ("creas_visitas_domiciliares", "Visitas domiciliares"),
    ],
    "CENTRO_POP": [
        ("pop_pessoas_situacao_rua", "Pessoas em situação de rua"),
        ("pop_atendimentos_mes", "Atendimentos no mês"),
        ("pop_abordagens_pessoas", "Pessoas abordadas"),
        ("pop_total_abordagens", "Total de abordagens"),
    ],
}


def _ranking_field(tipo: str) -> str:
    return {
        "CRAS": "cras_atend_individual",
        "CREAS": "creas_atend_individual",
        "CENTRO_POP": "pop_atendimentos_mes",
    }.get(tipo, "cras_atend_individual")


def _rotulo_equipamento(row: dict) -> str:
    tipo = str(row.get("tipo_equipamento") or "")
    nome = str(row.get("nome_oficial") or row.get("id_equipamento") or "—")
    if tipo == "CRAS" and row.get("cras_num_territorial") is not None:
        return f"CRAS {row['cras_num_territorial']} — {nome}"
    if tipo == "CREAS" and row.get("creas_num_territorial") is not None:
        return f"CREAS {row['creas_num_territorial']} — {nome}"
    return nome


def list_competencias(conn: Connection) -> list[str]:
    if not _table_exists(conn, "vig", RESUMO_MVIEW):
        return []
    rows = conn.execute(
        text(
            f"""
            SELECT DISTINCT competencia
            FROM vig.{_qi(RESUMO_MVIEW)}
            ORDER BY competencia DESC
            """
        )
    ).scalars()
    return [_comp_str(r) for r in rows]


def serie_rma(
    conn: Connection,
    *,
    tipo_equipamento: str,
    id_equipamento: str | None = None,
    meses: int = 24,
) -> list[dict]:
    tipo = tipo_equipamento.strip().upper()
    competencias = list_competencias(conn)
    if not competencias:
        return []

    limite = max(1, min(meses, len(competencias)))
    ate = competencias[0]
    desde = competencias[limite - 1]
    rows = resumo_serie(
        conn,
        id_equipamento=id_equipamento,
        tipo_equipamento=tipo,
        desde=desde,
        ate=ate,
    )
    campo = _ranking_field(tipo)
    por_mes: dict[str, int] = {}
    for row in rows:
        comp = _comp_str(row["competencia"])
        por_mes[comp] = por_mes.get(comp, 0) + _num(row.get(campo))

    return [
        {"competencia": comp, "valor": por_mes.get(comp, 0)}
        for comp in sorted(por_mes.keys())
    ]


def painel_rma(
    conn: Connection,
    *,
    competencia: str,
    tipo_equipamento: str = "CRAS",
    id_equipamento: str | None = None,
) -> dict:
    if not _table_exists(conn, "vig", RESUMO_MVIEW):
        return {
            "disponivel": False,
            "mensagem": "Visão RMA não encontrada. Gere a visão na aba Ingestão → RMA SUAS.",
        }

    tipo = tipo_equipamento.strip().upper()
    comp = competencia.strip()[:10]
    rows = resumo_serie(
        conn,
        id_equipamento=id_equipamento,
        tipo_equipamento=tipo,
        desde=comp,
        ate=comp,
    )
    month_rows = [r for r in rows if _comp_str(r["competencia"]) == comp]
    if not rows:
        return {
            "disponivel": False,
            "mensagem": "Nenhum registro na visão RMA. Confira a ingestão e gere a visão novamente.",
        }
    if not month_rows:
        return {
            "disponivel": False,
            "mensagem": f"Sem produção RMA para {comp[:7]} neste recorte.",
        }

    metricas = _METRICAS_POR_TIPO.get(tipo, _METRICAS_POR_TIPO["CRAS"])
    resumo = {chave: sum(_num(r.get(chave)) for r in month_rows) for chave, _ in metricas}

    ranking_field = _ranking_field(tipo)
    ranking_raw = sorted(
        month_rows,
        key=lambda r: _num(r.get(ranking_field)),
        reverse=True,
    )
    total_ranking = sum(_num(r.get(ranking_field)) for r in ranking_raw) or 0
    ranking = [
        {
            "rotulo": _rotulo_equipamento(r),
            "id_equipamento": r.get("id_equipamento"),
            "total": _num(r.get(ranking_field)),
            "pct": _pct(_num(r.get(ranking_field)), total_ranking),
        }
        for r in ranking_raw
        if _num(r.get(ranking_field)) > 0
    ]

    titulo = _rotulo_equipamento(month_rows[0]) if id_equipamento and len(month_rows) == 1 else {
        "CRAS": "Todos os CRAS",
        "CREAS": "Todos os CREAS",
        "CENTRO_POP": "Centro POP",
    }.get(tipo, tipo)

    return {
        "disponivel": True,
        "competencia": comp,
        "tipo_equipamento": tipo,
        "titulo_recorte": titulo,
        "resumo": resumo,
        "metricas": [{"chave": chave, "rotulo": rotulo} for chave, rotulo in metricas],
        "ranking": ranking,
        "ranking_campo": ranking_field,
    }


def equipamento_catalog(conn: Connection) -> list[dict]:
    if not _table_exists(conn, "vig", "dim_equipamento_suas"):
        return []
    rows = conn.execute(
        text(
            """
            SELECT
              id_equipamento,
              tipo_equipamento,
              nome_oficial,
              cras_num_territorial,
              creas_num_territorial,
              grupo_psr_id,
              rma_historico_creas_pop,
              ativo
            FROM vig."dim_equipamento_suas"
            ORDER BY tipo_equipamento, cras_num_territorial NULLS LAST,
                     creas_num_territorial NULLS LAST, nome_oficial
            """
        )
    ).mappings()
    return [dict(r) for r in rows]


def resumo_serie(
    conn: Connection,
    *,
    id_equipamento: str | None = None,
    tipo_equipamento: str | None = None,
    desde: str | None = None,
    ate: str | None = None,
) -> list[dict]:
    if not _table_exists(conn, "vig", RESUMO_MVIEW):
        raise ValueError("MV vig.mvw_rma_resumo_mes não encontrada. Execute refresh.")

    clauses = ["1=1"]
    params: dict = {}
    if id_equipamento:
        clauses.append("id_equipamento = :id_equipamento")
        params["id_equipamento"] = id_equipamento.strip()
    if tipo_equipamento:
        clauses.append("tipo_equipamento = :tipo_equipamento")
        params["tipo_equipamento"] = tipo_equipamento.strip().upper()
    if desde:
        clauses.append("competencia >= :desde::date")
        params["desde"] = desde
    if ate:
        clauses.append("competencia <= :ate::date")
        params["ate"] = ate
    if not desde and not ate:
        clauses.append(
            f"competencia >= ("
            f"SELECT COALESCE(MAX(competencia), CURRENT_DATE) - INTERVAL '48 months' "
            f"FROM vig.{_qi(RESUMO_MVIEW)}"
            f")"
        )

    where_sql = " AND ".join(clauses)
    rows = conn.execute(
        text(
            f"""
            SELECT *
            FROM vig.{_qi(RESUMO_MVIEW)}
            WHERE {where_sql}
            ORDER BY competencia, id_equipamento
            """
        ),
        params,
    ).mappings()
    return [dict(r) for r in rows]


def comparativo_cras_carga_demanda(
    conn: Connection,
    *,
    competencia: str,
) -> list[dict]:
    """CRAS: produção RMA vs estoque famílias CADU no mesmo mês (aproximação por num_cras)."""
    if not _table_exists(conn, "vig", RESUMO_MVIEW):
        raise ValueError("MV vig.mvw_rma_resumo_mes não encontrada.")
    if not _table_exists(conn, "vig", "mvw_familia"):
        raise ValueError("MV vig.mvw_familia não encontrada.")

    rows = conn.execute(
        text(
            f"""
            WITH prod AS (
              SELECT
                cras_num_territorial,
                id_equipamento,
                nome_oficial,
                cras_familias_paif,
                cras_atend_individual,
                cras_visitas_domiciliares,
                cras_novas_familias_paif
              FROM vig.{_qi(RESUMO_MVIEW)}
              WHERE competencia = :competencia::date
                AND tipo_equipamento = 'CRAS'
                AND cras_num_territorial IS NOT NULL
            ),
            dem AS (
              SELECT
                NULLIF(regexp_replace(btrim(num_cras::text), '[^0-9]', '', 'g'), '')::smallint
                  AS cras_num_territorial,
                COUNT(*)::bigint AS familias_cadu
              FROM vig.mvw_familia
              WHERE num_cras IS NOT NULL AND btrim(num_cras::text) <> ''
              GROUP BY 1
            )
            SELECT
              p.cras_num_territorial,
              p.id_equipamento,
              p.nome_oficial,
              p.cras_familias_paif,
              p.cras_atend_individual,
              p.cras_visitas_domiciliares,
              p.cras_novas_familias_paif,
              COALESCE(d.familias_cadu, 0) AS familias_cadu_territorio,
              CASE
                WHEN COALESCE(d.familias_cadu, 0) > 0 AND p.cras_atend_individual IS NOT NULL
                THEN ROUND(p.cras_atend_individual / d.familias_cadu, 4)
              END AS razao_atendimentos_por_familia_cadu
            FROM prod p
            LEFT JOIN dem d ON d.cras_num_territorial = p.cras_num_territorial
            ORDER BY p.cras_num_territorial
            """
        ),
        {"competencia": competencia},
    ).mappings()
    return [dict(r) for r in rows]
