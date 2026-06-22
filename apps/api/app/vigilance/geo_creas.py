"""CREAS territorial por bairro — matriz bairros_creas.csv × raw.geo__tbl_geo."""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from dataclasses import dataclass, field
from io import StringIO

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .geo_cras import (
    GEO_TABLE,
    canonical_bairro_display,
    lookup_bairro_key,
    normalize_bairro_key,
)


def _parse_creas_num(header: str) -> int | None:
    m = re.search(r"(\d+)", header or "")
    return int(m.group(1)) if m else None


def _split_bairro_cell(cell: str) -> list[str]:
    out: list[str] = []
    for part in re.split(r"[;,]", cell or ""):
        b = part.strip().strip('"').strip()
        if b:
            out.append(b)
    return out


def resolve_creas_duplicate(entries: list[tuple[int, str]]) -> tuple[int, dict | None]:
    """Bairro em mais de um CREAS: prevalece o de número maior (coluna mais à direita)."""
    creas_nums = sorted({c for c, _ in entries})
    if len(creas_nums) == 1:
        return creas_nums[0], None

    label = entries[0][1]
    chosen = max(creas_nums)
    return chosen, {
        "bairro": label,
        "creas_mantido": chosen,
        "creas_em_conflito": creas_nums,
        "creas_removidos": [c for c in creas_nums if c != chosen],
        "regra": "maior_numero_creas",
    }


def parse_bairros_creas_csv(content: bytes) -> tuple[dict[str, int], list[dict]]:
    """
    Lê matriz CREAS × bairros (delimitador ;).
    Linha 1 = cabeçalho CREAS 1…5; demais linhas = bairros por coluna.
    """
    try:
        text_content = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text_content = content.decode("latin-1")

    rows = list(csv.reader(StringIO(text_content), delimiter=";"))
    if len(rows) < 2:
        raise ValueError("CSV vazio ou sem linhas de bairros.")

    headers = rows[0]
    raw_assignments: dict[str, list[tuple[int, str]]] = defaultdict(list)

    for col_idx, header in enumerate(headers):
        creas_num = _parse_creas_num(header)
        if creas_num is None or "creas" not in (header or "").lower():
            continue
        for row in rows[1:]:
            if col_idx >= len(row):
                continue
            for bairro in _split_bairro_cell(row[col_idx]):
                key = normalize_bairro_key(bairro)
                if not key:
                    continue
                raw_assignments[key].append((creas_num, bairro))

    mapping: dict[str, int] = {}
    conflicts: list[dict] = []
    for key, entries in raw_assignments.items():
        chosen, conflict = resolve_creas_duplicate(entries)
        mapping[key] = chosen
        if conflict:
            conflicts.append(conflict)

    return mapping, conflicts


@dataclass
class ApplyCreasResult:
    bairros_no_mapa: int
    linhas_geo_atualizadas: int
    linhas_geo_bairro_renomeadas: int
    linhas_geo_ja_com_creas: int
    linhas_sem_bairro: int
    linhas_geo_total: int
    bairros_geo_sem_match: list[str] = field(default_factory=list)
    conflitos_bairro: list[dict] = field(default_factory=list)
    amostra_atualizacoes: list[dict] = field(default_factory=list)
    amostra_renomes_bairro: list[dict] = field(default_factory=list)
    dry_run: bool = False


def _resolve_creas_for_geo_row(bairro: str, bairro_to_creas: dict[str, int]) -> int | None:
    key = normalize_bairro_key(bairro)
    if not key:
        return None
    lookup = lookup_bairro_key(key)
    return bairro_to_creas.get(lookup) or bairro_to_creas.get(key)


def apply_creas_bairros_to_geo(
    conn: Connection,
    *,
    bairro_to_creas: dict[str, int],
    conflicts: list[dict],
    dry_run: bool = False,
) -> ApplyCreasResult:
    if not bairro_to_creas:
        raise ValueError("Nenhum bairro válido no arquivo de mapeamento.")

    has_creas = conn.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'raw'
              AND table_name = :t
              AND column_name = 'creas'
            """
        ),
        {"t": GEO_TABLE},
    ).scalar()
    if not has_creas:
        conn.execute(text(f'ALTER TABLE raw."{GEO_TABLE}" ADD COLUMN IF NOT EXISTS creas TEXT'))

    rows = conn.execute(
        text(
            f"""
            SELECT id, btrim(bairro::text) AS bairro, btrim(creas::text) AS creas
            FROM raw."{GEO_TABLE}"
            WHERE bairro IS NOT NULL AND btrim(bairro::text) <> ''
            """
        )
    ).mappings().all()

    geo_sem_bairro = conn.execute(
        text(
            f"""
            SELECT COUNT(*)::bigint
            FROM raw."{GEO_TABLE}"
            WHERE bairro IS NULL OR btrim(bairro::text) = ''
            """
        )
    ).scalar()

    creas_updates: list[tuple[int, str, str]] = []
    bairro_renames: list[tuple[int, str, str]] = []
    geo_unmatched: set[str] = set()

    for row in rows:
        bairro = str(row["bairro"] or "")
        key = normalize_bairro_key(bairro)
        if not key:
            continue

        creas_num = _resolve_creas_for_geo_row(bairro, bairro_to_creas)
        canonical = canonical_bairro_display(key)
        if canonical and canonical != bairro:
            bairro_renames.append((int(row["id"]), bairro, canonical))

        if creas_num is None:
            geo_unmatched.add(bairro)
            continue

        creas_val = str(creas_num)
        existing = str(row["creas"] or "").strip()
        if existing != creas_val:
            display_bairro = canonical or bairro
            creas_updates.append((int(row["id"]), display_bairro, creas_val))

    amostra = [{"id": i, "bairro": b, "creas": c} for i, b, c in creas_updates[:15]]
    amostra_renomes = [
        {"id": i, "bairro_anterior": old, "bairro_novo": new}
        for i, old, new in bairro_renames[:15]
    ]

    if not dry_run:
        if bairro_renames:
            conn.execute(
                text(
                    f"""
                    CREATE TEMP TABLE _geo_bairro_ren (
                      id bigint PRIMARY KEY,
                      bairro text NOT NULL
                    ) ON COMMIT DROP
                    """
                )
            )
            conn.execute(
                text("INSERT INTO _geo_bairro_ren (id, bairro) VALUES (:id, :bairro)"),
                [{"id": i, "bairro": new} for i, _, new in bairro_renames],
            )
            conn.execute(
                text(
                    f"""
                    UPDATE raw."{GEO_TABLE}" AS g
                    SET bairro = r.bairro
                    FROM _geo_bairro_ren AS r
                    WHERE g.id = r.id
                    """
                )
            )

        if creas_updates:
            conn.execute(
                text(
                    f"""
                    CREATE TEMP TABLE _geo_creas_upd (
                      id bigint PRIMARY KEY,
                      creas text NOT NULL
                    ) ON COMMIT DROP
                    """
                )
            )
            conn.execute(
                text("INSERT INTO _geo_creas_upd (id, creas) VALUES (:id, :creas)"),
                [{"id": i, "creas": c} for i, _, c in creas_updates],
            )
            conn.execute(
                text(
                    f"""
                    UPDATE raw."{GEO_TABLE}" AS g
                    SET creas = u.creas
                    FROM _geo_creas_upd AS u
                    WHERE g.id = u.id
                    """
                )
            )

    ja_com_creas = sum(
        1
        for row in rows
        if (n := _resolve_creas_for_geo_row(str(row["bairro"] or ""), bairro_to_creas)) is not None
        and str(row["creas"] or "").strip() == str(n)
    )

    return ApplyCreasResult(
        bairros_no_mapa=len(bairro_to_creas),
        linhas_geo_atualizadas=len(creas_updates),
        linhas_geo_bairro_renomeadas=len(bairro_renames),
        linhas_geo_ja_com_creas=ja_com_creas,
        linhas_sem_bairro=int(geo_sem_bairro or 0),
        linhas_geo_total=len(rows),
        bairros_geo_sem_match=sorted(geo_unmatched)[:30],
        conflitos_bairro=conflicts[:30],
        amostra_atualizacoes=amostra,
        amostra_renomes_bairro=amostra_renomes,
        dry_run=dry_run,
    )
