"""Catálogo de indicadores RMA (dicionários SUAS por tipo de formulário)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Connection

CATALOGO_TABLE = "rma_indicador"

# Indicadores PSR/abordagem no CREAS POP substituídos pelo formulário Centro POP.
PSR_INDICADORES_CREAS_PREFIXOS = ("i1", "k1", "k2", "k3", "k4", "k5", "k6", "l1")


def _qi(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def _monorepo_rma_dir() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "DadosBrutos" / "RMA"
        if candidate.is_dir():
            return candidate
    return None


def resolve_rma_data_dir() -> Path:
    from ..config import settings

    configured: Path | None = None
    if settings.rma_data_dir and settings.rma_data_dir.strip():
        configured = Path(settings.rma_data_dir.strip())
        if configured.is_dir():
            return configured
    docker = Path("/DadosBrutos/RMA")
    if docker.is_dir():
        return docker
    monorepo = _monorepo_rma_dir()
    if monorepo:
        return monorepo
    return configured or docker


def default_rma_data_dir() -> Path:
    return resolve_rma_data_dir()


def _parse_bloco(rotulo: str, codigo: str) -> str | None:
    m = re.match(r"^([A-Z])\.", rotulo or "", re.I)
    if m:
        return m.group(1).upper()
    if codigo and codigo[0].isalpha():
        return codigo[0].upper()
    return None


def _parse_desagregacao(codigo: str, rotulo: str) -> str | None:
    c = (codigo or "").lower()
    r = (rotulo or "").lower()
    if re.search(r"masculino|feminino", r):
        return "sexo_faixa"
    if c.endswith("a") or c.endswith("b") or re.search(r"\s-\s", rotulo or ""):
        if len(c) > 2 and c[-1].isalpha():
            return "sexo_faixa"
    if "total" in r:
        return "total"
    return None


def is_psr_indicador_creas(codigo: str) -> bool:
    c = (codigo or "").lower()
    return any(c == p or c.startswith(p) for p in PSR_INDICADORES_CREAS_PREFIXOS)


def load_dicionario_csv(path: Path, tipo_formulario: str) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="latin-1") as fh:
        for line in fh:
            line = line.strip()
            if not line or ";" not in line:
                continue
            codigo, _, rest = line.partition(";")
            codigo = codigo.strip().lower()
            rotulo = rest.strip().strip("'").strip()
            if not codigo or codigo in ("mes_referencia", "mes_ano", "nome_unidade"):
                continue
            if codigo in ("id_cras", "id_creas", "id_unidade", "endereco", "municipio", "uf"):
                continue
            if codigo in (
                "coordenador_cras",
                "coordenador_creas",
                "coordenador",
                "cpf",
                "codigoibge",
                "ibge",
            ):
                continue
            rows.append(
                {
                    "tipo_formulario": tipo_formulario,
                    "codigo": codigo,
                    "bloco": _parse_bloco(rotulo, codigo),
                    "rotulo": rotulo,
                    "desagregacao": _parse_desagregacao(codigo, rotulo),
                }
            )
    return rows


def ensure_rma_indicador_catalogo(conn: Connection) -> None:
    conn.execute(text("CREATE SCHEMA IF NOT EXISTS vig"))
    conn.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS vig.{_qi(CATALOGO_TABLE)} (
              tipo_formulario TEXT NOT NULL
                CHECK (tipo_formulario IN ('CRAS', 'CREAS', 'CENTRO_POP')),
              codigo TEXT NOT NULL,
              bloco TEXT,
              rotulo TEXT NOT NULL,
              desagregacao TEXT,
              psr_migrado_centro_pop BOOLEAN NOT NULL DEFAULT FALSE,
              PRIMARY KEY (tipo_formulario, codigo)
            )
            """
        )
    )


@dataclass
class CatalogoRefreshResult:
    inserted: int
    by_tipo: dict[str, int]


def refresh_catalogo_from_dicionarios(
    conn: Connection,
    *,
    data_dir: Path | None = None,
) -> CatalogoRefreshResult:
    ensure_rma_indicador_catalogo(conn)
    base = data_dir or default_rma_data_dir()
    specs = [
        ("CRAS", base / "CRAS" / "dicionario.csv"),
        ("CREAS", base / "CREAS" / "dicionario.csv"),
        ("CENTRO_POP", base / "POP" / "dicionario.csv"),
    ]

    inserted = 0
    by_tipo: dict[str, int] = {}
    for tipo, path in specs:
        if not path.is_file():
            continue
        items = load_dicionario_csv(path, tipo)
        by_tipo[tipo] = len(items)
        for item in items:
            psr = tipo == "CREAS" and is_psr_indicador_creas(item["codigo"])
            conn.execute(
                text(
                    f"""
                    INSERT INTO vig.{_qi(CATALOGO_TABLE)} (
                      tipo_formulario, codigo, bloco, rotulo, desagregacao, psr_migrado_centro_pop
                    ) VALUES (
                      :tipo_formulario, :codigo, :bloco, :rotulo, :desagregacao, :psr
                    )
                    ON CONFLICT (tipo_formulario, codigo) DO UPDATE SET
                      bloco = EXCLUDED.bloco,
                      rotulo = EXCLUDED.rotulo,
                      desagregacao = EXCLUDED.desagregacao,
                      psr_migrado_centro_pop = EXCLUDED.psr_migrado_centro_pop
                    """
                ),
                {**item, "psr": psr},
            )
            inserted += 1

    return CatalogoRefreshResult(inserted=inserted, by_tipo=by_tipo)
