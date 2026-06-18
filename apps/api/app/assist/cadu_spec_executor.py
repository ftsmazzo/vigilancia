"""Executor composicional CADU — monta SQL a partir da QueryTaskSpec (sem LLM).

Responde consultas compostas (sexo + idade + bairro + recorte) de forma autônoma
e verificável, sem depender de regex por frase.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..vigilance.familia_mview import _table_exists
from .bairro_resolver import _pick_variant, _prefix_name
from .cadu_pessoas_metrics import PersonRecorte, _QUANT, _FAMILIA, _PESSOA, wants_familia_count
from .cadu_territory import CaduTerritory, resolve_cadu_territory, territory_sql_where
from .query_task_spec import EntityKind, MetricKind, QueryTaskSpec, TerritoryKind


def _fmt_int(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _spec_needs_execution(spec: QueryTaskSpec, message: str) -> bool:
    text_msg = (message or "").strip()
    if spec.metric == MetricKind.VALIDATE:
        return bool(spec.person_recorte or spec.age_range or spec.territory)
    if not spec.is_cadu_person_query():
        return False
    if not _QUANT.search(text_msg) and not _PESSOA.search(text_msg) and not _FAMILIA.search(text_msg):
        return False
    return bool(spec.person_recorte or spec.age_range)


def _resolve_territory(
    conn: Connection,
    message: str,
    spec: QueryTaskSpec,
    *,
    user_first_name: str = "",
) -> CaduTerritory | dict[str, Any] | None:
    resolved = resolve_cadu_territory(
        conn,
        message,
        user_first_name=user_first_name,
        allow_municipio=spec.territory is None
        or spec.territory.kind == TerritoryKind.MUNICIPIO,
    )
    if resolved is not None:
        return resolved
    if spec.territory and spec.territory.kind == TerritoryKind.BAIRRO and spec.territory.value:
        return CaduTerritory(bairro=spec.territory.value)
    if spec.territory and spec.territory.kind == TerritoryKind.CRAS and spec.territory.value:
        return CaduTerritory(num_cras=spec.territory.value)
    return None


def _build_predicates(spec: QueryTaskSpec) -> tuple[list[str], list[str]]:
    """Retorna (predicados SQL, labels humanos)."""
    preds: list[str] = []
    labels: list[str] = []

    if spec.person_recorte:
        preds.append(spec.person_recorte.sql_predicate)
        label = (
            spec.person_recorte.label_familia
            if spec.entity == EntityKind.FAMILIA
            else spec.person_recorte.label_pessoa
        )
        labels.append(label)

    if spec.age_range:
        preds.append(spec.age_range.sql_between())
        labels.append(f"idade {spec.age_range.label()}")

    return preds, labels


def _count_pessoas_composed(
    conn: Connection,
    *,
    preds: list[str],
    terr: CaduTerritory,
) -> int:
    terr_sql, params = territory_sql_where(terr)
    where_person = " AND ".join(preds) if preds else "TRUE"
    row = conn.execute(
        text(
            f"""
            SELECT COUNT(p.cadu_row_id)::bigint AS total
            FROM vig.mvw_pessoas p
            INNER JOIN vig.mvw_familia f ON f.codigo_familiar = p.codigo_familiar
            WHERE {terr_sql} AND {where_person}
            """
        ),
        params,
    ).mappings().first()
    return int((row or {}).get("total") or 0)


def _count_familias_composed(
    conn: Connection,
    *,
    preds: list[str],
    terr: CaduTerritory,
) -> int:
    terr_sql, params = territory_sql_where(terr)
    where_person = " AND ".join(preds) if preds else "TRUE"
    row = conn.execute(
        text(
            f"""
            SELECT COUNT(DISTINCT f.codigo_familiar)::bigint AS total
            FROM vig.mvw_familia f
            WHERE {terr_sql}
              AND EXISTS (
                SELECT 1 FROM vig.mvw_pessoas p
                WHERE p.codigo_familiar = f.codigo_familiar
                  AND {where_person}
              )
            """
        ),
        params,
    ).mappings().first()
    return int((row or {}).get("total") or 0)


def _format_answer(
    *,
    spec: QueryTaskSpec,
    total: int,
    terr: CaduTerritory,
    labels: list[str],
    user_first_name: str,
    seed: str,
) -> str:
    unit = "famílias" if spec.entity == EntityKind.FAMILIA else "pessoas"
    desc = ", ".join(labels) if labels else unit
    filter_note = ""
    if len(labels) > 1:
        filter_note = f" ({'; '.join(labels)})"

    templates = [
        f"Em {terr.label}, há **{_fmt_int(total)}** **{desc}** no CADU "
        f"({unit}, território geo via família){filter_note}.",
        f"No recorte {terr.label}, o CADU registra **{_fmt_int(total)}** **{desc}**{filter_note}.",
    ]
    return _prefix_name(user_first_name, _pick_variant(seed, templates))


def _build_sql_preview(
    *,
    spec: QueryTaskSpec,
    preds: list[str],
    terr: CaduTerritory,
    total: int,
) -> tuple[str, list[dict[str, Any]]]:
    terr_sql, _ = territory_sql_where(terr)
    where_person = " AND ".join(preds) if preds else "TRUE"
    if spec.entity == EntityKind.FAMILIA:
        sql = (
            "SELECT COUNT(DISTINCT f.codigo_familiar) FROM vig.mvw_familia f "
            f"WHERE {terr_sql} AND EXISTS (SELECT 1 FROM vig.mvw_pessoas p "
            f"WHERE p.codigo_familiar = f.codigo_familiar AND {where_person})"
        )
    else:
        sql = (
            "SELECT COUNT(p.cadu_row_id) FROM vig.mvw_pessoas p "
            "INNER JOIN vig.mvw_familia f ON f.codigo_familiar = p.codigo_familiar "
            f"WHERE {terr_sql} AND {where_person}"
        )
    preview: dict[str, Any] = {
        "total": total,
        "granularidade": spec.entity.value,
        "filters_applied": spec.applied_filters_summary(),
    }
    if spec.person_recorte:
        preview["recorte"] = spec.person_recorte.key
    if spec.age_range:
        preview["age_min"] = spec.age_range.min_age
        preview["age_max"] = spec.age_range.max_age
    if terr.bairro:
        preview["bairro"] = terr.bairro
    if terr.num_cras:
        preview["num_cras"] = terr.num_cras
    return sql, [preview]


def try_execute_cadu_spec(
    conn: Connection,
    spec: QueryTaskSpec,
    message: str,
    *,
    user_first_name: str = "",
) -> dict[str, Any] | None:
    """
    Executa contagem CADU composta a partir da TaskSpec.
    Retorna None se a spec não for executável deterministicamente.
    """
    text_msg = (message or "").strip()
    if not _spec_needs_execution(spec, text_msg):
        return None

    if not _table_exists(conn, "vig", "mvw_familia") or not _table_exists(conn, "vig", "mvw_pessoas"):
        return None

    resolved = _resolve_territory(conn, text_msg, spec, user_first_name=user_first_name)
    if resolved is None:
        return None
    if isinstance(resolved, dict):
        return resolved
    terr = resolved

    preds, labels = _build_predicates(spec)
    if not preds:
        return None

    familia = spec.entity == EntityKind.FAMILIA or wants_familia_count(text_msg)
    if familia:
        total = _count_familias_composed(conn, preds=preds, terr=terr)
    else:
        total = _count_pessoas_composed(conn, preds=preds, terr=terr)

    sql, preview = _build_sql_preview(spec=spec, preds=preds, terr=terr, total=total)

    if spec.metric == MetricKind.VALIDATE:
        summary = spec.applied_filters_summary() or "; ".join(labels)
        answer = _prefix_name(
            user_first_name,
            f"Sim, o total de **{_fmt_int(total)}** corresponde a **{summary}** "
            f"no recorte {terr.label}, conforme os filtros aplicados na consulta.",
        )
        metric = "cadu_spec_validate"
    else:
        answer = _format_answer(
            spec=spec,
            total=total,
            terr=terr,
            labels=labels,
            user_first_name=user_first_name,
            seed=text_msg,
        )
        metric = "cadu_spec_familias" if familia else "cadu_spec_pessoas"

    return {
        "answer": answer,
        "sql": sql,
        "row_count": 1,
        "preview": preview,
        "mode": "canonical",
        "metric": metric,
        "task_spec": spec.to_dict(),
        "filters_applied": spec.applied_filters_summary(),
        "use_analyst": not spec.is_simple_data_response(),
        "response_mode": spec.response_mode,
    }
