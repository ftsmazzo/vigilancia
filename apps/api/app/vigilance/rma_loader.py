"""Carga dos CSVs RMA para raw.rma__* e refresh do fato mensal."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .familia_mview import _table_exists
from .rma_catalogo import default_rma_data_dir, is_psr_indicador_creas
from .rma_equipamento import CENTRO_POP_CUTOVER, CENTRO_POP_ID_OFICIAL

FATO_TABLE = "fato_rma_mensal"

_META_COLS = frozenset(
    {
        "mes_referencia",
        "mes_ano",
        "nome_unidade",
        "id_cras",
        "id_creas",
        "id_unidade",
        "endereco",
        "municipio",
        "uf",
        "coordenador_cras",
        "coordenador_creas",
        "coordenador",
        "cpf",
        "codigoibge",
        "ibge",
        "oferta_serv_blocoii",
        "id",
        "competencia",
    }
)

_RAW_SPECS: tuple[tuple[str, str, str, str, str], ...] = (
    ("CRAS", "rma__cras", "cras.csv", "id_cras", "mes_referencia"),
    ("CREAS", "rma__creas", "creas.csv", "id_creas", "mes_referencia"),
    ("CENTRO_POP", "rma__centro_pop", "centro_pop.csv", "id_unidade", "mes_ano"),
)


def _qi(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def _normalize_identifier(value: str) -> str:
    normalized = value.strip().lower()
    normalized = re.sub(r"[^a-z0-9_]", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    if not normalized:
        normalized = "coluna"
    if normalized[0].isdigit():
        normalized = f"c_{normalized}"
    return normalized[:63]


def _read_csv_rows(path: Path) -> tuple[list[str], list[list[str]]]:
    content = path.read_bytes()
    try:
        text_content = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text_content = content.decode("latin-1")
    reader = csv.reader(StringIO(text_content), delimiter=";")
    rows = list(reader)
    if not rows:
        return [], []
    header = [h.strip() for h in rows[0]]
    return header, rows[1:]


def _strip_quotes(value: str | None) -> str | None:
    if value is None:
        return None
    v = value.strip()
    if v.startswith("'") and v.endswith("'"):
        v = v[1:-1]
    return v.strip() or None


def _parse_numeric(value: str | None) -> float | None:
    v = _strip_quotes(value)
    if v is None or v == "":
        return None
    v = v.replace(",", ".")
    try:
        return float(v)
    except ValueError:
        return None


def load_raw_rma_table(
    conn: Connection,
    *,
    tipo_formulario: str,
    csv_path: Path,
    strategy: str = "replace",
) -> int:
    spec = next(s for s in _RAW_SPECS if s[0] == tipo_formulario)
    _, table_name, _, _, _ = spec
    headers, data_rows = _read_csv_rows(csv_path)
    if not headers:
        return 0

    conn.execute(text("CREATE SCHEMA IF NOT EXISTS raw"))
    col_names = [_normalize_identifier(h) for h in headers]
    if strategy == "replace":
        conn.execute(text(f"DROP TABLE IF EXISTS raw.{_qi(table_name)} CASCADE"))
    cols_sql = ", ".join(f"{_qi(c)} TEXT" for c in col_names)
    conn.execute(text(f"CREATE TABLE IF NOT EXISTS raw.{_qi(table_name)} ({cols_sql})"))
    if strategy != "replace":
        # append: garantir colunas novas
        existing = {
            r[0]
            for r in conn.execute(
                text(
                    """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema = 'raw' AND table_name = :t
                    """
                ),
                {"t": table_name},
            )
        }
        for col in col_names:
            if col not in existing:
                conn.execute(
                    text(f"ALTER TABLE raw.{_qi(table_name)} ADD COLUMN {_qi(col)} TEXT")
                )

    if not data_rows:
        return 0

    insert_cols = ", ".join(_qi(c) for c in col_names)
    placeholders = ", ".join(f":{c}" for c in col_names)
    batch: list[dict] = []
    for row in data_rows:
        payload = {}
        for idx, col in enumerate(col_names):
            payload[col] = row[idx] if idx < len(row) else None
        batch.append(payload)

    conn.execute(
        text(
            f"INSERT INTO raw.{_qi(table_name)} ({insert_cols}) VALUES ({placeholders})"
        ),
        batch,
    )
    return len(batch)


@dataclass
class RawLoadResult:
    table: str
    rows: int


@dataclass
class RmaBootstrapResult:
    raw: list[RawLoadResult]
    catalogo: dict
    dim: dict
    fato: dict


def ensure_fato_rma_mensal(conn: Connection) -> None:
    conn.execute(text("CREATE SCHEMA IF NOT EXISTS vig"))
    conn.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS vig.{_qi(FATO_TABLE)} (
              competencia DATE NOT NULL,
              id_equipamento TEXT NOT NULL,
              tipo_formulario TEXT NOT NULL
                CHECK (tipo_formulario IN ('CRAS', 'CREAS', 'CENTRO_POP')),
              codigo_indicador TEXT NOT NULL,
              valor NUMERIC,
              incluir_analitico BOOLEAN NOT NULL DEFAULT TRUE,
              motivo_exclusao TEXT,
              PRIMARY KEY (competencia, id_equipamento, tipo_formulario, codigo_indicador)
            )
            """
        )
    )
    conn.execute(
        text(
            f"""
            CREATE INDEX IF NOT EXISTS idx_fato_rma_competencia
              ON vig.{_qi(FATO_TABLE)} (competencia)
            """
        )
    )
    conn.execute(
        text(
            f"""
            CREATE INDEX IF NOT EXISTS idx_fato_rma_equipamento
              ON vig.{_qi(FATO_TABLE)} (id_equipamento, competencia)
            """
        )
    )


def _should_exclude_creas_psr(*, id_equipamento: str, competencia: str, codigo: str) -> bool:
    if id_equipamento != CENTRO_POP_ID_OFICIAL:
        return False
    if competencia < CENTRO_POP_CUTOVER:
        return False
    return is_psr_indicador_creas(codigo)


def refresh_fato_rma_mensal(conn: Connection) -> dict:
    ensure_fato_rma_mensal(conn)
    conn.execute(text(f"TRUNCATE TABLE vig.{_qi(FATO_TABLE)}"))

    total = 0
    for tipo_form, table_name, _, id_col_raw, date_col_raw in _RAW_SPECS:
        if not _table_exists(conn, "raw", table_name):
            continue

        id_col = _normalize_identifier(id_col_raw)
        date_col = _normalize_identifier(date_col_raw)

        cols = {
            r[0]
            for r in conn.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'raw' AND table_name = :t
                    """
                ),
                {"t": table_name},
            )
        }
        indicator_cols = [
            c
            for c in sorted(cols)
            if c not in {_normalize_identifier(x) for x in _META_COLS}
            and c not in (id_col, date_col)
        ]
        if not indicator_cols:
            continue

        raw_rows = conn.execute(
            text(
                f"""
                SELECT *
                FROM raw.{_qi(table_name)}
                WHERE btrim(COALESCE({_qi(id_col)}::text, '')) <> ''
                  AND btrim(COALESCE({_qi(date_col)}::text, '')) <> ''
                """
            )
        ).mappings()

        batch: list[dict] = []
        for row in raw_rows:
            eid = _strip_quotes(str(row.get(id_col) or ""))
            comp_raw = _strip_quotes(str(row.get(date_col) or ""))
            if not eid or not comp_raw:
                continue
            competencia = comp_raw[:10]

            for cod in indicator_cols:
                val = _parse_numeric(str(row.get(cod)) if row.get(cod) is not None else None)
                excluir = _should_exclude_creas_psr(
                    id_equipamento=eid,
                    competencia=competencia,
                    codigo=cod,
                )
                batch.append(
                    {
                        "competencia": competencia,
                        "id_equipamento": eid,
                        "tipo_formulario": tipo_form,
                        "codigo_indicador": cod,
                        "valor": val,
                        "incluir_analitico": not excluir,
                        "motivo_exclusao": "psr_migrado_centro_pop" if excluir else None,
                    }
                )
                if len(batch) >= 5000:
                    conn.execute(
                        text(
                            f"""
                            INSERT INTO vig.{_qi(FATO_TABLE)} (
                              competencia, id_equipamento, tipo_formulario,
                              codigo_indicador, valor, incluir_analitico, motivo_exclusao
                            ) VALUES (
                              :competencia, :id_equipamento, :tipo_formulario,
                              :codigo_indicador, :valor, :incluir_analitico, :motivo_exclusao
                            )
                            """
                        ),
                        batch,
                    )
                    total += len(batch)
                    batch.clear()

        if batch:
            conn.execute(
                text(
                    f"""
                    INSERT INTO vig.{_qi(FATO_TABLE)} (
                      competencia, id_equipamento, tipo_formulario,
                      codigo_indicador, valor, incluir_analitico, motivo_exclusao
                    ) VALUES (
                      :competencia, :id_equipamento, :tipo_formulario,
                      :codigo_indicador, :valor, :incluir_analitico, :motivo_exclusao
                    )
                    """
                ),
                batch,
            )
            total += len(batch)

    return {"rows": total}


def bootstrap_rma_from_dados_brutos(
    conn: Connection,
    *,
    data_dir: Path | None = None,
) -> RmaBootstrapResult:
    from .rma_catalogo import refresh_catalogo_from_dicionarios
    from .rma_equipamento import refresh_dim_from_raw_rma

    base = data_dir or default_rma_data_dir()
    raw_results: list[RawLoadResult] = []
    for tipo_form, table_name, file_name, _, _ in _RAW_SPECS:
        sub = "POP" if tipo_form == "CENTRO_POP" else tipo_form
        path = base / sub / file_name
        if not path.is_file():
            continue
        n = load_raw_rma_table(conn, tipo_formulario=tipo_form, csv_path=path)
        raw_results.append(RawLoadResult(table=f"raw.{table_name}", rows=n))

    cat = refresh_catalogo_from_dicionarios(conn, data_dir=base)
    dim = refresh_dim_from_raw_rma(conn)
    fato = refresh_fato_rma_mensal(conn)

    return RmaBootstrapResult(
        raw=raw_results,
        catalogo={"inserted": cat.inserted, "by_tipo": cat.by_tipo},
        dim={"upserted": dim.upserted, "total": dim.total},
        fato=fato,
    )
