"""QueryTaskSpec — contrato estruturado entre Maestro, executores e AgenteSQL.

Arquitetura autônoma sem LangChain/CrewAI: intenção tipada → planejamento →
execução verificada → resposta proporcional. LLM só onde a spec não cobre.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any

from .bairro_resolver import extract_location_term
from .cadu_pessoas_metrics import PersonRecorte, detect_person_recorte
from .response_mode import infer_response_mode
from .session_context import SessionContext

_AGE_IN_FILTER = re.compile(r"idade\s+(\d{1,3})\s+a\s+(\d{1,3})\s+anos", re.I)
_AGE_RANGE = re.compile(r"(\d{1,3})\s*(?:a|-|á)\s*(\d{1,3})\s*(?:anos)?", re.I)
_QUANT = re.compile(
    r"quantas?|quantos?|total|n[uú]mero|qtd|conte|existem|h[aá]\s+(?:quantas?)?",
    re.I,
)
_FAMILIA = re.compile(r"\bfam[ií]lias?\b", re.I)
_PESSOA = re.compile(
    r"\bpessoas?\b|\bmulheres?\b|\bhomens?\b|\bcrian[cç]as?\b|\bidosos?\b|\badolesc",
    re.I,
)
_SEX_FEM = re.compile(r"\bmulheres?\b|\bfeminino\b", re.I)
_SEX_MASC = re.compile(r"\bhomens?\b|\bmasculino\b", re.I)
_CRAS_NUM = re.compile(r"\bcras\s*(\d{1,2})\b", re.I)
_VALIDATION = re.compile(
    r"como\s+pedi|conforme\s+pedi|est[aá]\s+correto|aplicou|filtros?\s+aplic|"
    r"n[aã]o\s+entendeu|vc\s+n[aã]o\s+entendeu",
    re.I,
)
_COHORT = re.compile(
    r"\b(?:dess[aeo]s?|dest[aeo]s?|dessas?|desses?|"
    r"entre\s+(?:eles|elas|ess[aeo]s?))\b",
    re.I,
)
_PBF = re.compile(
    r"\b(?:pbf|bolsa\s+fam[ií]lia|programa\s+bolsa|"
    r"benef[ií]cio\s+bolsa|recebe[m]?\s+(?:o\s+)?(?:pbf|bolsa))\b",
    re.I,
)


class MetricKind(str, Enum):
    COUNT = "count"
    COMPARE = "compare"
    RANK = "rank"
    LIST = "list"
    EXISTS = "exists"
    VALIDATE = "validate"


class EntityKind(str, Enum):
    PESSOA = "pessoa"
    FAMILIA = "familia"


class TerritoryKind(str, Enum):
    BAIRRO = "bairro"
    CRAS = "cras"
    MUNICIPIO = "municipio"


@dataclass(frozen=True)
class AgeRange:
    min_age: int
    max_age: int

    def label(self) -> str:
        return f"{self.min_age} a {self.max_age} anos"

    def sql_between(self, alias: str = "p") -> str:
        return (
            f"{alias}.idade IS NOT NULL AND {alias}.idade "
            f"BETWEEN {self.min_age} AND {self.max_age}"
        )


@dataclass(frozen=True)
class TerritorySpec:
    kind: TerritoryKind
    value: str | None = None


@dataclass
class QueryTaskSpec:
    """Pedido de dado estruturado — artefato central do pipeline autônomo."""

    metric: MetricKind = MetricKind.COUNT
    entity: EntityKind = EntityKind.PESSOA
    person_recorte: PersonRecorte | None = None
    age_range: AgeRange | None = None
    territory: TerritorySpec | None = None
    response_mode: str = "data"
    original_question: str = ""
    filter_labels: list[str] = field(default_factory=list)
    requires_pbf_folha: bool = False
    cohort_followup: bool = False

    def is_cadu_person_query(self) -> bool:
        if self.metric not in (MetricKind.COUNT, MetricKind.EXISTS, MetricKind.VALIDATE):
            return False
        return bool(
            self.person_recorte
            or self.age_range
            or _SEX_FEM.search(self.original_question)
            or _SEX_MASC.search(self.original_question)
            or _PESSOA.search(self.original_question)
        )

    def is_simple_data_response(self) -> bool:
        return self.response_mode in ("data", "balanced") and self.metric in (
            MetricKind.COUNT,
            MetricKind.EXISTS,
        )

    def applied_filters_summary(self) -> str:
        parts = list(self.filter_labels)
        if self.person_recorte:
            parts.append(self.person_recorte.label_pessoa)
        if self.age_range:
            parts.append(f"idade {self.age_range.label()}")
        if self.territory and self.territory.kind != TerritoryKind.MUNICIPIO:
            if self.territory.kind == TerritoryKind.BAIRRO:
                parts.append(f"bairro {self.territory.value}")
            elif self.territory.kind == TerritoryKind.CRAS:
                parts.append(f"CRAS {self.territory.value}")
        return "; ".join(dict.fromkeys(p for p in parts if p))

    def to_sql_agent_block(self) -> str:
        """Requisitos explícitos que o AgenteSQL DEVE satisfazer."""
        lines = ["### Especificação da consulta (obrigatória)"]
        lines.append(f"- Objetivo: {self.metric.value}")
        lines.append(f"- Entidade: {self.entity.value}")
        if self.person_recorte:
            lines.append(f"- Recorte de pessoa: {self.person_recorte.label_pessoa}")
            lines.append(f"- Predicado SQL: {self.person_recorte.sql_predicate}")
        if self.age_range:
            lines.append(f"- Faixa etária: {self.age_range.label()}")
            lines.append(f"- SQL idade: {self.age_range.sql_between()}")
        if self.territory:
            if self.territory.kind == TerritoryKind.BAIRRO and self.territory.value:
                b = self.territory.value.replace("'", "''")
                lines.append(
                    f"- Território: bairro **{self.territory.value}** "
                    f"(lower(btrim(f.bairro::text)) = lower('{b}'))"
                )
            elif self.territory.kind == TerritoryKind.CRAS and self.territory.value:
                lines.append(
                    f"- Território: CRAS {self.territory.value} "
                    f"(btrim(f.num_cras::text) = '{self.territory.value}')"
                )
        if self.filter_labels:
            lines.append(f"- Filtros declarados: {', '.join(self.filter_labels)}")
        if self.requires_pbf_folha:
            lines.append(
                "- Família na folha PBF: COALESCE(f.marc_pbf, false) = true "
                "(família recebe Bolsa Família)"
            )
        lines.append(
            "- A consulta DEVE incluir TODOS os filtros acima. "
            "Não omita faixa etária nem território."
        )
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric.value,
            "entity": self.entity.value,
            "recorte": self.person_recorte.key if self.person_recorte else None,
            "age_min": self.age_range.min_age if self.age_range else None,
            "age_max": self.age_range.max_age if self.age_range else None,
            "territory": (
                {"kind": self.territory.kind.value, "value": self.territory.value}
                if self.territory
                else None
            ),
            "response_mode": self.response_mode,
            "filters": self.filter_labels,
            "requires_pbf_folha": self.requires_pbf_folha,
            "cohort_followup": self.cohort_followup,
        }


def _parse_age_from_text(text: str, transcript: list[dict[str, str]] | None) -> AgeRange | None:
    match = _AGE_RANGE.search(text or "")
    if match:
        lo, hi = int(match.group(1)), int(match.group(2))
        if lo > hi:
            lo, hi = hi, lo
        return AgeRange(lo, hi)
    if transcript:
        for msg in reversed(transcript):
            if msg.get("role") != "user":
                continue
            match = _AGE_RANGE.search(msg.get("content", ""))
            if match:
                lo, hi = int(match.group(1)), int(match.group(2))
                if lo > hi:
                    lo, hi = hi, lo
                return AgeRange(lo, hi)
    return None


def _parse_age_from_session_filters(filters: list[str]) -> AgeRange | None:
    for f in filters:
        m = _AGE_IN_FILTER.search(f)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            if lo > hi:
                lo, hi = hi, lo
            return AgeRange(lo, hi)
    return None


def _parse_territory(text: str, ctx: SessionContext | None) -> TerritorySpec | None:
    from .territory_guard import familia_as_data_entity, should_skip_bairro_resolution

    if should_skip_bairro_resolution(text) or familia_as_data_entity(text):
        if ctx and ctx.last_bairro:
            return TerritorySpec(TerritoryKind.BAIRRO, ctx.last_bairro)
        if ctx and ctx.last_cras:
            return TerritorySpec(TerritoryKind.CRAS, ctx.last_cras)
        return None

    cras_m = _CRAS_NUM.search(text)
    if cras_m:
        raw = cras_m.group(1).lstrip("0") or cras_m.group(1)
        return TerritorySpec(TerritoryKind.CRAS, raw)

    term = extract_location_term(text)
    if term:
        return TerritorySpec(TerritoryKind.BAIRRO, term)

    if ctx and ctx.last_bairro:
        return TerritorySpec(TerritoryKind.BAIRRO, ctx.last_bairro)
    if ctx and ctx.last_cras:
        return TerritorySpec(TerritoryKind.CRAS, ctx.last_cras)

    if re.search(r"\bmunic[ií]pio\b", text, re.I):
        return TerritorySpec(TerritoryKind.MUNICIPIO, None)
    return None


def _wants_familia(text: str) -> bool:
    from .territory_guard import familia_as_data_entity, has_pbf_cross_filter

    if familia_as_data_entity(text) or (has_pbf_cross_filter(text) and _COHORT.search(text)):
        return False
    if not _FAMILIA.search(text):
        return False
    if _PESSOA.search(text) and not re.search(r"\bfam[ií]lias?\s+com\b", text, re.I):
        return False
    return True


def extract_task_spec(
    message: str,
    transcript: list[dict[str, str]] | None = None,
    *,
    session_context: SessionContext | None = None,
) -> QueryTaskSpec:
    """Extrai spec da pergunta + histórico (heurística determinística)."""
    text_msg = (message or "").strip()
    ctx = session_context or SessionContext()

    metric = MetricKind.COUNT
    if _VALIDATION.search(text_msg):
        metric = MetricKind.VALIDATE

    cohort = bool(_COHORT.search(text_msg))
    requires_pbf = bool(_PBF.search(text_msg) and re.search(r"\bfam[ií]lias?\b", text_msg, re.I))

    recorte = detect_person_recorte(text_msg)
    age_range = _parse_age_from_text(text_msg, transcript) or _parse_age_from_session_filters(
        ctx.filters
    )

    if age_range and recorte and recorte.key in ("idoso", "crianca", "adolescente", "fora_escola"):
        recorte = _SEX_FEM.search(text_msg) and detect_person_recorte(text_msg) or recorte
        if recorte.key in ("idoso", "crianca", "adolescente"):
            recorte = None
            if _SEX_FEM.search(text_msg):
                from .cadu_pessoas_metrics import _recorte_mulher
                recorte = _recorte_mulher()
            elif _SEX_MASC.search(text_msg):
                from .cadu_pessoas_metrics import _recorte_homem
                recorte = _recorte_homem()

    if not recorte:
        if ctx.subject == "mulheres" or _SEX_FEM.search(text_msg) or re.search(r"\bdessas?\s+mulheres\b", text_msg, re.I):
            from .cadu_pessoas_metrics import _recorte_mulher
            recorte = _recorte_mulher()
        elif ctx.subject == "homens" or _SEX_MASC.search(text_msg) or re.search(r"\bdesses?\s+homens\b", text_msg, re.I):
            from .cadu_pessoas_metrics import _recorte_homem
            recorte = _recorte_homem()

    territory = _parse_territory(text_msg, ctx)
    entity = EntityKind.FAMILIA if _wants_familia(text_msg) else EntityKind.PESSOA
    if ctx.entity == "famílias" and entity == EntityKind.PESSOA and _FAMILIA.search(ctx.question_stem):
        entity = EntityKind.FAMILIA

    response_mode = infer_response_mode(text_msg)
    filter_labels: list[str] = []
    if recorte:
        filter_labels.append(recorte.label_pessoa if entity == EntityKind.PESSOA else recorte.label_familia)
    if age_range:
        filter_labels.append(f"idade {age_range.label()}")
    if territory and territory.kind == TerritoryKind.BAIRRO and territory.value:
        filter_labels.append(f"bairro {territory.value}")
    elif territory and territory.kind == TerritoryKind.CRAS and territory.value:
        filter_labels.append(f"CRAS {territory.value}")

    if requires_pbf:
        filter_labels.append("família na folha PBF")

    return QueryTaskSpec(
        metric=metric,
        entity=entity,
        person_recorte=recorte,
        age_range=age_range,
        territory=territory,
        response_mode=response_mode,
        original_question=text_msg,
        filter_labels=filter_labels,
        requires_pbf_folha=requires_pbf,
        cohort_followup=cohort,
    )


def merge_task_spec_with_session(
    spec: QueryTaskSpec,
    ctx: SessionContext,
    transcript: list[dict[str, str]] | None = None,
) -> QueryTaskSpec:
    """Acumula filtros da sessão — não descarta faixa etária ao mudar território."""
    age = spec.age_range or _parse_age_from_session_filters(ctx.filters)
    if not age and ctx.question_stem:
        age = _parse_age_from_text(ctx.question_stem, transcript)

    recorte = spec.person_recorte
    if not recorte and ctx.subject == "mulheres":
        from .cadu_pessoas_metrics import _recorte_mulher
        recorte = _recorte_mulher()
    elif not recorte and ctx.subject == "homens":
        from .cadu_pessoas_metrics import _recorte_homem
        recorte = _recorte_homem()

    requires_pbf = spec.requires_pbf_folha or bool(_PBF.search(spec.original_question or ""))

    territory = spec.territory
    if not territory or territory.kind == TerritoryKind.MUNICIPIO:
        if ctx.last_bairro:
            territory = TerritorySpec(TerritoryKind.BAIRRO, ctx.last_bairro)
        elif ctx.last_cras:
            territory = TerritorySpec(TerritoryKind.CRAS, ctx.last_cras)

    filter_labels = list(spec.filter_labels)
    for f in ctx.filters:
        if f not in filter_labels and not f.startswith("cod_sexo"):
            filter_labels.append(f)

    if age and not spec.age_range:
        filter_labels.append(f"idade {age.label()}")

    stem = ctx.question_stem or spec.original_question
    return replace(
        spec,
        person_recorte=recorte or spec.person_recorte,
        age_range=age or spec.age_range,
        territory=territory or spec.territory,
        filter_labels=list(dict.fromkeys(filter_labels)),
        original_question=spec.original_question or stem,
        requires_pbf_folha=requires_pbf or spec.requires_pbf_folha,
        cohort_followup=spec.cohort_followup or bool(_COHORT.search(spec.original_question or "")),
    )


def legacy_cadu_recorte_covers_spec(spec: QueryTaskSpec) -> bool:
    """Atalho antigo só quando NÃO há faixa etária extra além do recorte fixo."""
    if spec.requires_pbf_folha or spec.cohort_followup:
        return False
    if not spec.person_recorte or not spec.is_cadu_person_query():
        return False
    if spec.age_range:
        fixed = {
            "idoso": AgeRange(60, 120),
            "crianca": AgeRange(0, 11),
            "adolescente": AgeRange(12, 17),
            "fora_escola": AgeRange(7, 17),
        }
        expected = fixed.get(spec.person_recorte.key)
        if expected != spec.age_range:
            return False
    if spec.entity == EntityKind.FAMILIA and spec.person_recorte.key == "fora_escola":
        return True
    return spec.age_range is None or spec.person_recorte.key in (
        "idoso",
        "crianca",
        "adolescente",
        "fora_escola",
    )


def verify_sql_covers_spec(sql: str, spec: QueryTaskSpec) -> tuple[bool, list[str]]:
    """Verificador pós-execução — garante que SQL reflete a spec."""
    if not sql or not sql.strip():
        return False, ["sql vazio"]
    low = sql.lower()
    missing: list[str] = []

    if spec.age_range:
        has_age = bool(
            re.search(rf"idade\s+between\s+{spec.age_range.min_age}\s+and\s+{spec.age_range.max_age}", low)
            or (
                re.search(r"idade\s+between", low)
                and str(spec.age_range.min_age) in low
                and str(spec.age_range.max_age) in low
            )
        )
        if not has_age:
            missing.append(f"faixa etária {spec.age_range.label()}")

    if spec.person_recorte and spec.person_recorte.key == "mulher":
        if "cod_sexo" not in low and "'2'" not in low:
            missing.append("sexo feminino")
    if spec.person_recorte and spec.person_recorte.key == "homem":
        if "cod_sexo" not in low and "'1'" not in low:
            missing.append("sexo masculino")

    if spec.territory and spec.territory.kind == TerritoryKind.BAIRRO and spec.territory.value:
        if "bairro" not in low:
            missing.append(f"bairro {spec.territory.value}")

    if spec.territory and spec.territory.kind == TerritoryKind.CRAS and spec.territory.value:
        if "num_cras" not in low and f"cras {spec.territory.value}" not in low:
            missing.append(f"CRAS {spec.territory.value}")

    if spec.requires_pbf_folha:
        if "marc_pbf" not in low:
            missing.append("família na folha PBF (marc_pbf)")

    return len(missing) == 0, missing
