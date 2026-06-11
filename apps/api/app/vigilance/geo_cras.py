"""CRAS territorial por bairro — matriz bairros_cras.csv × raw.geo__tbl_geo."""

from __future__ import annotations

import csv
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from io import StringIO

from sqlalchemy import text
from sqlalchemy.engine import Connection

GEO_TABLE = "geo__tbl_geo"
CRAS_NOVOS_MIN = 8

# Chave normalizada → chave canônica para lookup no mapa CRAS
BAIRRO_ALIAS_TO_CANONICAL: dict[str, str] = {
    "residencial vida nova ribeirao": "jardim cristo redentor",
}

# Chave canônica → texto gravado na coluna bairro da tbl_geo
BAIRRO_CANONICAL_DISPLAY: dict[str, str] = {
    "jardim cristo redentor": "Jardim Cristo Redentor",
}

_ABBREV_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bjd\.?\b"), "jardim"),
    (re.compile(r"\bcond\.?\b"), "condominio"),
    (re.compile(r"\bvl\.?\b"), "vila"),
    (re.compile(r"\bpq\.?\b"), "parque"),
    (re.compile(r"\bconj\.?\b"), "conjunto"),
    (re.compile(r"\bres\.?\b"), "residencial"),
    (re.compile(r"\bhab\.?\b"), "habitacional"),
)


def _strip_accents(value: str) -> str:
    s = unicodedata.normalize("NFKD", value)
    return "".join(c for c in s if not unicodedata.combining(c))


def normalize_bairro_key(value: str | None) -> str:
    """Chave de comparação: minúsculas, sem acento, abreviações expandidas, espaços colapsados."""
    if not value:
        return ""
    s = _strip_accents(value.strip().lower())
    s = re.sub(r"[''`´]", " ", s)
    s = re.sub(r"[^\w\s]", " ", s)
    for pattern, repl in _ABBREV_REPLACEMENTS:
        s = pattern.sub(repl, s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def lookup_bairro_key(normalized: str) -> str:
    """Aplica aliases conhecidos (ex.: Residencial Vida Nova → Jardim Cristo Redentor)."""
    if not normalized:
        return ""
    return BAIRRO_ALIAS_TO_CANONICAL.get(normalized, normalized)


def canonical_bairro_display(normalized: str) -> str | None:
    """Nome canônico para gravar na tbl_geo quando o texto local difere do oficial."""
    canonical = lookup_bairro_key(normalized)
    if canonical in BAIRRO_CANONICAL_DISPLAY:
        return BAIRRO_CANONICAL_DISPLAY[canonical]
    if normalized in BAIRRO_CANONICAL_DISPLAY:
        return BAIRRO_CANONICAL_DISPLAY[normalized]
    return None


def _parse_cras_num(header: str) -> int | None:
    m = re.search(r"(\d+)", header or "")
    return int(m.group(1)) if m else None


def _split_bairro_cell(cell: str) -> list[str]:
    out: list[str] = []
    for part in re.split(r"[;,]", cell or ""):
        b = part.strip().strip('"').strip()
        if b:
            out.append(b)
    return out


def resolve_cras_duplicate(entries: list[tuple[int, str]]) -> tuple[int, dict | None]:
    """
    Bairro em mais de um CRAS: se houver CRAS 8–12 (unidades novas), prevalecem sobre 1–7.
    Entre dois CRAS novos, mantém o de número maior (coluna mais à direita no CSV).
    """
    cras_nums = sorted({c for c, _ in entries})
    if len(cras_nums) == 1:
        return cras_nums[0], None

    label = entries[0][1]
    novos = [c for c in cras_nums if c >= CRAS_NOVOS_MIN]
    antigos = [c for c in cras_nums if c < CRAS_NOVOS_MIN]

    if novos and antigos:
        chosen = max(novos)
        return chosen, {
            "bairro": label,
            "cras_mantido": chosen,
            "cras_removidos": antigos + [c for c in novos if c != chosen],
            "regra": "cras_8_12_prevalece_sobre_1_7",
        }

    chosen = max(cras_nums)
    return chosen, {
        "bairro": label,
        "cras_mantido": chosen,
        "cras_em_conflito": cras_nums,
        "cras_removidos": [c for c in cras_nums if c != chosen],
        "regra": "maior_numero_cras" if novos else "maior_numero_cras_antigo",
    }


def parse_bairros_cras_csv(content: bytes) -> tuple[dict[str, int], list[dict]]:
    """
    Lê matriz CRAS × bairros (delimitador ;).
    Linha 1 = cabeçalho CRAS 1…12; demais linhas = bairros por coluna.
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
        cras_num = _parse_cras_num(header)
        if cras_num is None:
            continue
        for row in rows[1:]:
            if col_idx >= len(row):
                continue
            for bairro in _split_bairro_cell(row[col_idx]):
                key = normalize_bairro_key(bairro)
                if not key:
                    continue
                raw_assignments[key].append((cras_num, bairro))

    mapping: dict[str, int] = {}
    conflicts: list[dict] = []
    for key, entries in raw_assignments.items():
        chosen, conflict = resolve_cras_duplicate(entries)
        mapping[key] = chosen
        if conflict:
            conflicts.append(conflict)

    return mapping, conflicts


@dataclass
class ApplyCrasResult:
    bairros_no_mapa: int
    linhas_geo_atualizadas: int
    linhas_geo_bairro_renomeadas: int
    linhas_geo_ja_com_cras: int
    linhas_sem_bairro: int
    linhas_geo_total: int
    bairros_geo_sem_match: list[str] = field(default_factory=list)
    conflitos_bairro: list[dict] = field(default_factory=list)
    amostra_atualizacoes: list[dict] = field(default_factory=list)
    amostra_renomes_bairro: list[dict] = field(default_factory=list)
    dry_run: bool = False


def _resolve_cras_for_geo_row(bairro: str, bairro_to_cras: dict[str, int]) -> int | None:
    key = normalize_bairro_key(bairro)
    if not key:
        return None
    lookup = lookup_bairro_key(key)
    return bairro_to_cras.get(lookup) or bairro_to_cras.get(key)


def apply_cras_bairros_to_geo(
    conn: Connection,
    *,
    bairro_to_cras: dict[str, int],
    conflicts: list[dict],
    dry_run: bool = False,
) -> ApplyCrasResult:
    if not bairro_to_cras:
        raise ValueError("Nenhum bairro válido no arquivo de mapeamento.")

    has_cras = conn.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'raw'
              AND table_name = :t
              AND column_name = 'cras'
            """
        ),
        {"t": GEO_TABLE},
    ).scalar()
    if not has_cras:
        conn.execute(text(f'ALTER TABLE raw."{GEO_TABLE}" ADD COLUMN IF NOT EXISTS cras TEXT'))

    rows = conn.execute(
        text(
            f"""
            SELECT id, btrim(bairro::text) AS bairro, btrim(cras::text) AS cras
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

    cras_updates: list[tuple[int, str, str]] = []
    bairro_renames: list[tuple[int, str, str]] = []
    geo_unmatched: set[str] = set()

    for row in rows:
        bairro = str(row["bairro"] or "")
        key = normalize_bairro_key(bairro)
        if not key:
            continue

        cras_num = _resolve_cras_for_geo_row(bairro, bairro_to_cras)
        canonical = canonical_bairro_display(key)
        if canonical and canonical != bairro:
            bairro_renames.append((int(row["id"]), bairro, canonical))

        if cras_num is None:
            geo_unmatched.add(bairro)
            continue

        cras_val = str(cras_num)
        existing = str(row["cras"] or "").strip()
        if existing != cras_val:
            display_bairro = canonical or bairro
            cras_updates.append((int(row["id"]), display_bairro, cras_val))

    amostra = [{"id": i, "bairro": b, "cras": c} for i, b, c in cras_updates[:15]]
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

        if cras_updates:
            conn.execute(
                text(
                    f"""
                    CREATE TEMP TABLE _geo_cras_upd (
                      id bigint PRIMARY KEY,
                      cras text NOT NULL
                    ) ON COMMIT DROP
                    """
                )
            )
            conn.execute(
                text("INSERT INTO _geo_cras_upd (id, cras) VALUES (:id, :cras)"),
                [{"id": i, "cras": c} for i, _, c in cras_updates],
            )
            conn.execute(
                text(
                    f"""
                    UPDATE raw."{GEO_TABLE}" AS g
                    SET cras = u.cras
                    FROM _geo_cras_upd AS u
                    WHERE g.id = u.id
                    """
                )
            )

    ja_com_cras = sum(
        1
        for row in rows
        if (n := _resolve_cras_for_geo_row(str(row["bairro"] or ""), bairro_to_cras)) is not None
        and str(row["cras"] or "").strip() == str(n)
    )

    return ApplyCrasResult(
        bairros_no_mapa=len(bairro_to_cras),
        linhas_geo_atualizadas=len(cras_updates),
        linhas_geo_bairro_renomeadas=len(bairro_renames),
        linhas_geo_ja_com_cras=ja_com_cras,
        linhas_sem_bairro=int(geo_sem_bairro or 0),
        linhas_geo_total=len(rows),
        bairros_geo_sem_match=sorted(geo_unmatched)[:30],
        conflitos_bairro=conflicts[:30],
        amostra_atualizacoes=amostra,
        amostra_renomes_bairro=amostra_renomes,
        dry_run=dry_run,
    )
