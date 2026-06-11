"""Pacote de evidências — fatos estruturados antes da interpretação."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _fmt_idx(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


@dataclass
class EvidenceFact:
    label: str
    value: str
    source: str
    detail: str = ""
    axis: str = ""
    signal: str = ""


@dataclass
class EvidencePack:
    question: str
    thread_brief: str = ""
    facts: list[EvidenceFact] = field(default_factory=list)
    sql: str | None = None
    preview: list[dict[str, Any]] = field(default_factory=list)
    metric: str = ""
    mode: str = "data"
    reflexion_guide: str = ""

    def to_prompt_block(self) -> str:
        lines = [f"Pergunta: {self.question}"]
        if self.thread_brief.strip():
            lines.append(f"Contexto: {self.thread_brief.strip()}")
        if self.reflexion_guide.strip():
            lines.append(f"Guia reflexivo: {self.reflexion_guide.strip()}")
        if not self.facts:
            lines.append("Fatos: (nenhum dado estruturado)")
        else:
            lines.append("Fatos verificados (use SOMENTE estes números e critérios):")
            for fact in self.facts:
                prefix = f"[Eixo {fact.axis}] " if fact.axis else ""
                sig = f" ({fact.signal})" if fact.signal and fact.signal != "neutro" else ""
                line = f"- {prefix}{fact.label}: {fact.value}{sig} [{fact.source}]"
                if fact.detail:
                    line += f" — {fact.detail}"
                lines.append(line)
        if self.preview:
            lines.append(f"Preview tabular ({len(self.preview)} linha(s)): {self.preview[:8]}")
        return "\n".join(lines)


def pack_from_canonical(question: str, result: dict[str, Any], *, thread_brief: str = "") -> EvidencePack:
    facts: list[EvidenceFact] = []
    preview = result.get("preview") or []
    metric = str(result.get("metric") or "")

    if metric.startswith("ivs_"):
        for row in preview[:1]:
            if isinstance(row, dict):
                val = row.get("valor")
                dim = row.get("dimensao") or "IVS"
                fam = row.get("familias_elegiveis")
                bairro = row.get("bairro")
                cras = row.get("num_cras")
                loc = f"CRAS {cras}" if cras else (bairro or "município")
                if val is not None:
                    facts.append(
                        EvidenceFact(
                            label=f"Índice {dim} em {loc}",
                            value=f"{float(val):.2f}".replace(".", ","),
                            source="core.mvw_ivs_familia × vig.mvw_familia",
                            detail="escala 0 a 1; universo elegivel_ivs (IN084)",
                        )
                    )
                if fam is not None:
                    facts.append(
                        EvidenceFact(
                            label="Famílias elegíveis IVS",
                            value=str(fam),
                            source="core.mvw_ivs_familia",
                        )
                    )
    elif metric in ("planning_carencia", "planning_bairro_em_cras", "planning_diagnostico_bairro", "planning_reflexion"):
        for row in preview:
            if isinstance(row, dict) and row.get("label"):
                facts.append(
                    EvidenceFact(
                        label=str(row.get("label", "Indicador")),
                        value=str(row.get("value", "")),
                        source=str(row.get("source", "consulta")),
                        detail=str(row.get("detail", "")),
                        axis=str(row.get("axis", "")),
                        signal=str(row.get("signal", "")),
                    )
                )
    elif metric.startswith("planning_"):
        for row in preview[:3]:
            if not isinstance(row, dict):
                continue
            if row.get("bairro"):
                facts.append(
                    EvidenceFact(
                        label=f"Bairro {row.get('bairro')} (CRAS {row.get('num_cras', '?')})",
                        value=f"{row.get('total', 0)} crianças/adolescentes",
                        source="vig.mvw_pessoas × vig.mvw_familia",
                        detail="demanda potencial no CADU territorial; faixa etária da conversa",
                    )
                )
            elif row.get("num_cras"):
                facts.append(
                    EvidenceFact(
                        label=f"CRAS {row.get('num_cras')}",
                        value=f"{row.get('total', 0)} na faixa etária",
                        source="vig.mvw_pessoas × vig.mvw_familia",
                        detail="demanda territorial CADU",
                    )
                )
    elif metric == "ivs_cras_compare":
        threshold = None
        dim = "NC"
        for row in preview:
            if isinstance(row, dict):
                if row.get("threshold") is not None:
                    threshold = row["threshold"]
                if row.get("dimensao"):
                    dim = str(row["dimensao"])
                if row.get("num_cras") and row.get("valor") is not None:
                    facts.append(
                        EvidenceFact(
                            label=f"CRAS {row['num_cras']} — {dim}",
                            value=_fmt_idx(float(row["valor"])),
                            source="core.mvw_ivs_familia × vig.mvw_familia",
                            detail=f"estritamente acima de {_fmt_idx(float(threshold)) if threshold is not None else '?'} (0 a 1)",
                        )
                    )
        if threshold is not None and not any(f.label.startswith("Referência") for f in facts):
            facts.insert(
                0,
                EvidenceFact(
                    label="Referência comparativa",
                    value=_fmt_idx(float(threshold)),
                    source="histórico da conversa",
                    detail=f"limiar {dim}; listar apenas CRAS com índice > referência",
                ),
            )

    if not facts and preview:
        for row in preview[:5]:
            if isinstance(row, dict):
                facts.append(
                    EvidenceFact(
                        label="Resultado",
                        value=str(row),
                        source=metric or "consulta",
                    )
                )

    return EvidencePack(
        question=question,
        thread_brief=thread_brief,
        facts=facts,
        sql=result.get("sql"),
        preview=preview,
        metric=metric,
        mode=str(result.get("mode", "canonical")),
        reflexion_guide=str(result.get("reflexion_guide") or ""),
    )


def pack_from_sql(question: str, sql_result, *, thread_brief: str = "") -> EvidencePack:
    facts: list[EvidenceFact] = []
    for row in (sql_result.preview or [])[:8]:
        if isinstance(row, dict):
            facts.append(
                EvidenceFact(
                    label="Linha de resultado",
                    value=", ".join(f"{k}={v}" for k, v in row.items()),
                    source="AgenteSQL",
                )
            )
    if not facts and sql_result.summary:
        facts.append(
            EvidenceFact(
                label="Resumo SQL",
                value=sql_result.summary[:500],
                source="AgenteSQL",
            )
        )
    return EvidencePack(
        question=question,
        thread_brief=thread_brief,
        facts=facts,
        sql=sql_result.sql,
        preview=sql_result.preview or [],
        metric="sql_agent",
        mode="data",
    )
