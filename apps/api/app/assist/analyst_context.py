"""Contexto do Especialista Analítico — IVS, RAG, município e rede."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from ..ivs.catalog import DIMENSOES, DIM_POR_SIGLA
from ..municipio_context import load_context_prompt
from ..vigilance.familia_mview import _table_exists
from .analyst_reflexion import build_playbook_for_pack, is_planning_decision_context
from .evidence import EvidencePack
from .ivs_metrics import build_ivs_assist_hint
from .kb_client import query_knowledge_base

_IVS_TOPIC = re.compile(
    r"\b(?:ivs|ivcad|nc|dpi|dca|tqa|dr|ch|vulnerabilidade|necessidade\s+de\s+cuidados)\b",
    re.I,
)
_PLANNING_TOPIC = re.compile(
    r"\b(?:scfv|conviv|implantar|car[eê]ncia|demanda|planej)\b",
    re.I,
)
_SISC_TOPIC = re.compile(r"\b(?:sisc|matriculad|atendid)\b", re.I)


@dataclass
class AnalystContext:
    municipio_block: str = ""
    rede_block: str = ""
    ivs_domain_block: str = ""
    playbook_block: str = ""
    rag_block: str = ""
    view_availability: str = ""

    def to_system_sections(self) -> str:
        sections: list[str] = []
        if self.playbook_block.strip():
            sections.append(self.playbook_block.strip())
        if self.ivs_domain_block.strip():
            sections.append(self.ivs_domain_block.strip())
        if self.municipio_block.strip():
            sections.append(self.municipio_block.strip())
        if self.rede_block.strip():
            sections.append(self.rede_block.strip())
        if self.view_availability.strip():
            sections.append(self.view_availability.strip())
        if self.rag_block.strip():
            sections.append(
                "### Referências técnicas (RAG — normas e metodologia)\n"
                "Use para **interpretar** e **decidir**, nunca para inventar números.\n\n"
                + self.rag_block.strip()
            )
        return "\n\n".join(sections)


def build_ivs_domain_block() -> str:
    dim_lines = []
    for dim in DIMENSOES:
        inds = ", ".join(f"{i.codigo} ({i.titulo})" for i in dim.indicadores[:4])
        extra = f" … +{len(dim.indicadores) - 4} indicadores" if len(dim.indicadores) > 4 else ""
        dim_lines.append(
            f"- **{dim.sigla}** — {dim.nome} (`{dim.idx_col}`): {inds}{extra}"
        )

    return f"""### Domínio IVS / IVCAD (o que você sabe ler e decidir)

Metodologia **IVCAD v1.0.5 (IN084)** — índice composto de vulnerabilidade familiar.

**Universo elegível:** famílias com `elegivel_ivs = true` (PBF ou TAC ≤ 24 meses + renda per capita ≤ R$ 810,50).

**Escala:** dimensões e índice composto **0 a 1** — quanto **maior**, maior vulnerabilidade naquele eixo.
Indicadores binários (NC1, DPI1…) aparecem agregados como **% de famílias** com o flag.

**Dimensões:**
{chr(10).join(dim_lines)}

**Como decidir (sem inventar número):**
- **NC** (Necessidade de Cuidados): crianças pequenas, idosos, deficiência, composição familiar frágil — **eixo central para SCFV e cuidados**.
- **DPI / DCA**: primeira infância e infância/adolescência (escola, trabalho infantil) — cruze com faixa etária do planejamento.
- **DR**: pobreza/renda — **não confundir** com NC; família pobre nem sempre tem alta NC.
- **TQA / CH**: capacidade adulta e moradia — contexto estrutural, não substitui demanda CADU por idade.

**Território:** IVS **não tem bairro/CRAS** — territorialização sempre via `vig.mvw_familia` no join.

**Comparar CRAS:** só afirmar "maior que X" se o fato trouxer comparação estrita (`>`); empate (0,45 vs 0,45) **não** é maior.

{build_ivs_assist_hint()}"""


def _fmt_int(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _fetch_rede_snapshot(conn: Connection) -> str:
    lines: list[str] = ["### Rede territorial e oferta (dados operacionais do município)"]

    if _table_exists(conn, "vig", "mvw_familia"):
        rows = conn.execute(
            text(
                """
                SELECT
                  btrim(f.num_cras::text) AS num_cras,
                  MAX(btrim(f.nom_cras::text)) AS nom_cras,
                  COUNT(DISTINCT f.codigo_familiar)::bigint AS familias
                FROM vig.mvw_familia f
                WHERE btrim(COALESCE(f.num_cras::text, '')) <> ''
                GROUP BY btrim(f.num_cras::text)
                ORDER BY
                  NULLIF(regexp_replace(btrim(f.num_cras::text), '[^0-9].*', ''), '')::int NULLS LAST,
                  num_cras
                """
            )
        ).mappings().all()
        if rows:
            lines.append("**CRAS territorial (CADU — famílias por unidade):**")
            for r in rows[:14]:
                nome = r.get("nom_cras") or ""
                rotulo = f"CRAS {r['num_cras']}" + (f" — {nome}" if nome else "")
                lines.append(f"- {rotulo}: {_fmt_int(int(r['familias'] or 0))} famílias")
    else:
        lines.append("- CADU territorial: visão `vig.mvw_familia` indisponível.")

    if _table_exists(conn, "vig", "mvw_sisc_qualificado"):
        sisc_rows = conn.execute(
            text(
                """
                SELECT
                  COALESCE(NULLIF(btrim(s.cras_codigo::text), ''), '?') AS cras_codigo,
                  COALESCE(NULLIF(btrim(s.cras_nome::text), ''), '(sem nome)') AS cras_nome,
                  COUNT(DISTINCT s.nis_norm)::bigint AS atendidos
                FROM vig.mvw_sisc_qualificado s
                WHERE s.classificacao_vinculo = 'vinculado_cadu'
                GROUP BY 1, 2
                ORDER BY atendidos DESC
                LIMIT 12
                """
            )
        ).mappings().all()
        if sisc_rows:
            lines.append(
                "\n**Oferta SISC (matrícula — CRAS da matrícula, não territorial):**"
            )
            for r in sisc_rows:
                lines.append(
                    f"- {r['cras_nome']} (cód. {r['cras_codigo']}): "
                    f"{_fmt_int(int(r['atendidos'] or 0))} atendidos (NIS)"
                )
    else:
        lines.append("- SISC qualificado: indisponível (qualificar em Convivência).")

    if _table_exists(conn, "core", "mvw_ivs_familia") and _table_exists(conn, "vig", "mvw_familia"):
        ivs_row = conn.execute(
            text(
                """
                SELECT
                  ROUND(AVG(i.ivs) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS ivs,
                  ROUND(AVG(i.idx_nc) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS idx_nc,
                  COUNT(*) FILTER (WHERE i.elegivel_ivs)::bigint AS familias_elegiveis
                FROM core.mvw_ivs_familia i
                INNER JOIN vig.mvw_familia f ON f.codigo_familiar = i.codigo_familiar
                """
            )
        ).mappings().first()
        if ivs_row and ivs_row.get("familias_elegiveis"):
            ivs = float(ivs_row["ivs"] or 0)
            nc = float(ivs_row["idx_nc"] or 0)
            fam = int(ivs_row["familias_elegiveis"] or 0)
            lines.append(
                f"\n**Panorama IVS municipal:** IVS **{ivs:.2f}**, NC **{nc:.2f}** "
                f"({_fmt_int(fam)} famílias elegíveis — escala 0 a 1)."
            )

    if len(lines) <= 1:
        return ""
    lines.append(
        "\nUse a rede para **situar** decisões (onde há famílias, onde há matrícula SISC). "
        "Números da pergunta atual vêm dos **Fatos verificados**, não deste panorama."
    )
    return "\n".join(lines)


def _view_availability_block(conn: Connection) -> str:
    items = []
    for schema, view in (
        ("vig", "mvw_familia"),
        ("vig", "mvw_pessoas"),
        ("vig", "mvw_sisc_qualificado"),
        ("core", "mvw_ivs_familia"),
    ):
        ok = _table_exists(conn, schema, view)
        items.append(f"- `{schema}.{view}`: {'disponível' if ok else 'ausente'}")
    return "### Bases acessíveis agora\n" + "\n".join(items)


def enrich_kb_query(message: str, pack: EvidencePack) -> str:
    blob = f"{message} {pack.thread_brief} {pack.metric}"
    parts = [message.strip()]
    if _IVS_TOPIC.search(blob) or pack.metric.startswith("ivs"):
        parts.append(
            "IVS IVCAD IN084 vulnerabilidade familiar necessidade de cuidados "
            "dimensões NC DPI DCA metodologia elegibilidade"
        )
    if _PLANNING_TOPIC.search(blob) or pack.metric.startswith("planning"):
        parts.append(
            "SCFV serviço de convivência SUAS faixa etária 6-15 12-17 "
            "planejamento territorial carência oferta"
        )
    if _SISC_TOPIC.search(blob) or "sisc" in pack.metric:
        parts.append("SISC matrícula serviço de convivência cruzamento CADU")
    if "carência" in message.lower() or pack.metric == "planning_carencia":
        parts.append(
            "carência socioassistencial demanda potencial matrícula existente "
            "cobertura rede SUAS"
        )
    return " ".join(dict.fromkeys(p.strip() for p in parts if p.strip()))


def build_analyst_context(
    conn: Connection,
    db: Session,
    *,
    message: str,
    pack: EvidencePack,
    municipio_block: str = "",
    rag_block: str = "",
) -> AnalystContext:
    blob = f"{message} {pack.metric} {pack.thread_brief}"
    planning = is_planning_decision_context(pack, message)
    needs_ivs = bool(_IVS_TOPIC.search(blob) or pack.metric.startswith("ivs") or planning)

    municipio = municipio_block.strip() or load_context_prompt(db)
    rede = _fetch_rede_snapshot(conn)
    views = _view_availability_block(conn)
    playbook = build_playbook_for_pack(pack, message)

    rag = rag_block.strip()
    if not rag:
        rag = query_knowledge_base(enrich_kb_query(message, pack))

    return AnalystContext(
        municipio_block=municipio,
        rede_block=rede,
        ivs_domain_block=build_ivs_domain_block() if needs_ivs and not planning else (
            _ivs_reading_brief() if needs_ivs else ""
        ),
        playbook_block=playbook,
        rag_block=rag[:8000] if rag else "",
        view_availability=views,
    )


def _ivs_reading_brief() -> str:
    """Referência mínima IVS mesmo fora de perguntas explícitas (planejamento × vulnerabilidade)."""
    nc = DIM_POR_SIGLA["NC"]
    return (
        "### Leitura IVS (referência rápida)\n"
        f"- **{nc.sigla}** — {nc.nome}: escala 0 a 1; maior = mais vulnerabilidade na dimensão.\n"
        "- Demanda CADU por idade ≠ IVS; matrícula SISC ≠ demanda potencial.\n"
        "- Para cruzar planejamento SCFV com vulnerabilidade, cite NC/DCA dos **Fatos** quando houver."
    )
