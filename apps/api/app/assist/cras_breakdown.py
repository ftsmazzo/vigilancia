"""Formatação de desdobramento por CRAS (CADU territorial)."""

from __future__ import annotations

import re
from typing import Any

# CRAS 9 = Bonfim Paulista (referência municipal)
CRAS_BONFIM_NUM = "9"


def _fmt_int(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _parse_num_cras(value: Any) -> int | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    m = re.match(r"^(\d+)", s)
    if m:
        return int(m.group(1))
    return None


def _count_column(row: dict[str, Any]) -> tuple[str, int]:
    for key, val in row.items():
        kl = key.lower()
        if kl in ("total_familias", "total", "familias", "count", "n") or "total" in kl or "fam" in kl:
            try:
                return key, int(val or 0)
            except (TypeError, ValueError):
                continue
    # fallback: last numeric column
    for key, val in reversed(list(row.items())):
        if key.lower() in ("num_cras", "nom_cras", "cras_codigo", "cras_nome"):
            continue
        try:
            return key, int(val or 0)
        except (TypeError, ValueError):
            continue
    return "total", 0


def _name_column(row: dict[str, Any]) -> str:
    for key in ("nom_cras", "cras_nome", "nome_cras"):
        if key in row and row[key]:
            return str(row[key]).strip()
    return ""


def is_cras_breakdown(rows: list[dict[str, Any]]) -> bool:
    if not rows or len(rows) < 2:
        return False
    keys = {k.lower() for r in rows for k in r.keys()}
    has_cras = bool(keys & {"num_cras", "nom_cras", "cras_codigo", "cras_nome", "cras_numero"})
    has_count = any(
        k.lower() in ("total_familias", "total", "familias", "count", "n")
        or "total" in k.lower()
        or "fam" in k.lower()
        for k in keys
    )
    return has_cras and has_count


def sort_cras_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ordena por num_cras 1..12; sem referência (null) por último."""

    def sort_key(row: dict[str, Any]) -> tuple[int, str]:
        num = _parse_num_cras(row.get("num_cras") or row.get("cras_codigo"))
        if num is None:
            return (9999, "")
        return (num, _name_column(row))

    return sorted(rows, key=sort_key)


def format_cras_breakdown_summary(
    rows: list[dict[str, Any]],
    *,
    unit: str = "famílias",
) -> str:
    """Texto completo para o Orquestrador (todas as linhas, ordem numérica)."""
    if not rows:
        return "Nenhum CRAS encontrado."

    sorted_rows = sort_cras_rows(rows)
    lines: list[str] = []
    sem_ref = 0

    for row in sorted_rows:
        _, total = _count_column(row)
        num = _parse_num_cras(row.get("num_cras") or row.get("cras_codigo"))
        nome = _name_column(row)

        if num is None:
            sem_ref = total
            continue

        label = f"CRAS {num}"
        if num == int(CRAS_BONFIM_NUM) and nome:
            label = f"CRAS {num} (Bonfim Paulista)"
        elif nome:
            short = nome.replace("AREA DO CRAS ", "Área ").replace("AREA DO ", "")
            label = f"{label} — {short}"

        lines.append(f"- {label}: {_fmt_int(total)} {unit}")

    body = "\n".join(lines)
    if sem_ref:
        body += (
            f"\n- **Sem referência territorial de CRAS:** {_fmt_int(sem_ref)} {unit}"
        )
    return body


def format_cras_breakdown_answer(
    rows: list[dict[str, Any]],
    *,
    user_first_name: str = "",
    municipio_nome: str = "",
    metric_label: str = "famílias do Cadastro Único",
    unit: str = "famílias",
    intro: str | None = None,
    include_foot: bool = False,
) -> str:
    """Resposta humanizada determinística — lista todos os CRAS, sem truncar."""
    sorted_rows = sort_cras_rows(rows)
    total_geral = sum(_count_column(r)[1] for r in sorted_rows)
    summary = format_cras_breakdown_summary(rows, unit=unit)

    who = f"{user_first_name}, " if user_first_name else ""
    where = f" em {municipio_nome}" if municipio_nome else ""

    if intro:
        lead = intro
    else:
        lead = (
            f"{who}as **{_fmt_int(total_geral)}** {metric_label}{where} "
            f"estão distribuídas por território de CRAS da seguinte forma "
            f"(ordem numérica 1 a 12):"
        )

    foot = ""
    if include_foot:
        foot = (
            "\n\nEsse indicador mostra a concentração de "
            f"{unit} em cada área de abrangência dos CRAS. "
            f"{unit.capitalize()} sem vínculo territorial aparecem como **sem referência territorial**."
        )

    return f"{lead}\n\n{summary}{foot}"
