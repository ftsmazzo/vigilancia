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
from .multi_bairro_metrics import message_has_bairro_list_scope
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
_CRAS_BREAKDOWN = re.compile(
    r"por\s+cras|por\s+cada\s+cras|cada\s+cras|qual\s+cras|cras\s+tem\s+mais|"
    r"divide|divid|detalh|distribu|desdobr|separad\s+por\s+cras|distribu[ií][çc][ãa]o",
    re.I,
)
_CHILD = re.compile(r"\bcrian[cç]as?\b", re.I)
_COHORT_AGE = re.compile(
    r"nessa\s+faixa|faixa\s+et[aá]ria|dess[aeo]s|dest[aeo]s|entre\s+(?:eles|elas)",
    re.I,
)
_SUBJECT_PIVOT = re.compile(
    r"^(?:e\s+)?(?:idosos?|crian[cç]as?|mulheres?|homens?|adolescentes?)\??\.?$",
    re.I,
)
_SIBEC = re.compile(
    r"\bsibec\b|bloqueio|bloquead|cancelamento|manuten[cç][ãa]o|teve_bloqueio",
    re.I,
)
_RACA = re.compile(r"ra[cç]a|etnia|\bcor\b|pard[oa]|pret[oa]|ind[ií]gena|branc[oa]", re.I)


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


class BreakdownKind(str, Enum):
    NONE = "none"
    CRAS = "cras"


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
    breakdown: BreakdownKind = BreakdownKind.NONE

    def wants_cras_breakdown(self) -> bool:
        return self.breakdown == BreakdownKind.CRAS

    def mentions_sibec(self) -> bool:
        return bool(_SIBEC.search(self.original_question or ""))

    def needs_free_sql(self) -> bool:
        """Cruzamentos arbitrários — AgenteSQL, não executor CADU fixo."""
        msg = self.original_question or ""
        if _RACA.search(msg):
            return True
        if self.mentions_sibec() and (
            self.age_range
            or _CHILD.search(msg)
            or self.person_recorte
            or self.cohort_followup
            or _COHORT_AGE.search(msg)
        ):
            return True
        if self.mentions_sibec() and self.entity == EntityKind.FAMILIA and (
            _CHILD.search(msg) or self.age_range
        ):
            return True
        return False

    def skip_cadu_spec_executor(self) -> bool:
        """Executor composicional só para CADU puro — não SIBEC/raça/cruzamentos."""
        if self.needs_free_sql():
            return True
        if self.mentions_sibec():
            return True
        if _RACA.search(self.original_question or ""):
            return True
        return False

    def is_data_turn(self, ctx: SessionContext | None = None) -> bool:
        """Turno que pede número ou cruzamento — candidato ao pipeline SQL-first."""
        msg = self.original_question or ""
        if _QUANT.search(msg):
            return True
        if self.person_recorte or self.age_range:
            return True
        if self.territory and self.territory.kind != TerritoryKind.MUNICIPIO:
            return True
        if self.wants_cras_breakdown() or self.requires_pbf_folha:
            return True
        if self.mentions_sibec() or _RACA.search(msg):
            return True
        if message_has_bairro_list_scope(msg):
            return True
        if _CRAS_NUM.search(msg) and ctx and ctx.has_data_thread():
            return True
        if ctx and ctx.has_data_thread() and len(msg.strip()) <= 100:
            if _COHORT.search(msg) or _COHORT_AGE.search(msg) or _SUBJECT_PIVOT.match(msg.strip()):
                return True
        return False

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
        if self.wants_cras_breakdown():
            lines.append(
                "- Desdobramento: GROUP BY f.num_cras, f.nom_cras "
                "(lista todos os CRAS do município, ordem numérica 1–12)"
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
            "breakdown": self.breakdown.value,
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


def _parse_age_from_session_ctx(ctx: SessionContext) -> AgeRange | None:
    if ctx.last_age_min is not None and ctx.last_age_max is not None:
        return AgeRange(ctx.last_age_min, ctx.last_age_max)
    return _parse_age_from_session_filters(ctx.filters)


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


def _fixed_age_for_recorte(recorte: PersonRecorte) -> AgeRange | None:
    return {
        "crianca": AgeRange(0, 11),
        "adolescente": AgeRange(12, 17),
        "fora_escola": AgeRange(7, 17),
    }.get(recorte.key)


def _resolve_age_for_turn(
    text_msg: str,
    transcript: list[dict[str, str]] | None,
    ctx: SessionContext,
    recorte: PersonRecorte | None,
) -> AgeRange | None:
    """Faixa explícita > recorte fixo > sessão; pivô de assunto não herda idade anterior."""
    explicit = _parse_age_from_text(text_msg, transcript)
    if explicit:
        return explicit
    if recorte and not _COHORT_AGE.search(text_msg):
        if _SUBJECT_PIVOT.match(text_msg.strip()):
            return _fixed_age_for_recorte(recorte)
        if recorte.key in ("crianca", "adolescente", "fora_escola"):
            return _fixed_age_for_recorte(recorte)
        return None
    if _COHORT_AGE.search(text_msg):
        return _parse_age_from_session_ctx(ctx)
    return _parse_age_from_session_ctx(ctx)


def _parse_breakdown(
    text: str,
    ctx: SessionContext | None,
    transcript: list[dict[str, str]] | None,
) -> BreakdownKind:
    if _CRAS_BREAKDOWN.search(text or ""):
        return BreakdownKind.CRAS
    if ctx and ctx.question_stem and _CRAS_BREAKDOWN.search(ctx.question_stem):
        return BreakdownKind.CRAS
    if re.search(r"por\s+cada\s+cras|cada\s+cras\s+do\s+munic", text or "", re.I):
        return BreakdownKind.CRAS
    if transcript:
        for msg in reversed(transcript):
            if msg.get("role") == "user" and _CRAS_BREAKDOWN.search(msg.get("content", "")):
                return BreakdownKind.CRAS
    return BreakdownKind.NONE


def _resolve_person_recorte_with_age(
    text_msg: str,
    recorte: PersonRecorte | None,
    age_range: AgeRange | None,
) -> PersonRecorte | None:
    """Faixa explícita prevalece sobre recorte fixo (ex.: crianças 0–15 ≠ ≤11)."""
    if not age_range or not recorte:
        return recorte
    if recorte.key == "crianca" and age_range.max_age > 11:
        return None
    if recorte.key == "adolescente" and (
        age_range.min_age < 12 or age_range.max_age > 17
    ):
        return None
    if recorte.key == "idoso" and age_range.max_age < 60:
        return None
    return recorte


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
    elif re.search(
        r"qual\s+cras\s+tem\s+mais|cras\s+com\s+mais|maior\s+concentr",
        text_msg,
        re.I,
    ):
        metric = MetricKind.RANK

    cohort = bool(_COHORT.search(text_msg) or _COHORT_AGE.search(text_msg))
    mentions_sibec = bool(_SIBEC.search(text_msg))
    requires_pbf = bool(
        _PBF.search(text_msg)
        and (
            re.search(r"\bfam[ií]lias?\b", text_msg, re.I)
            or re.search(r"recebendo\s+(?:o\s+)?(?:pbf|bolsa)", text_msg, re.I)
            or ctx.requires_pbf
        )
        and not mentions_sibec
    )

    recorte = detect_person_recorte(text_msg)
    age_range = _resolve_age_for_turn(text_msg, transcript, ctx, recorte)
    recorte = _resolve_person_recorte_with_age(text_msg, recorte, age_range)
    breakdown = _parse_breakdown(text_msg, ctx, transcript)

    if not recorte:
        if ctx.subject == "crianças" or (_CHILD.search(text_msg) and age_range):
            pass
        elif ctx.subject == "idosos" or re.search(r"\bidosos?\b", text_msg, re.I):
            from .cadu_pessoas_metrics import _recorte_idoso
            recorte = _recorte_idoso()
        elif ctx.subject == "mulheres" or _SEX_FEM.search(text_msg) or re.search(r"\bdessas?\s+mulheres\b", text_msg, re.I):
            from .cadu_pessoas_metrics import _recorte_mulher
            recorte = _recorte_mulher()
        elif ctx.subject == "homens" or _SEX_MASC.search(text_msg) or re.search(r"\bdesses?\s+homens\b", text_msg, re.I):
            from .cadu_pessoas_metrics import _recorte_homem
            recorte = _recorte_homem()

    territory = _parse_territory(text_msg, ctx)
    if breakdown == BreakdownKind.CRAS:
        territory = TerritorySpec(TerritoryKind.MUNICIPIO, None)
    entity = EntityKind.FAMILIA if _wants_familia(text_msg) else EntityKind.PESSOA
    if ctx.entity == "famílias" and entity == EntityKind.PESSOA and _FAMILIA.search(ctx.question_stem):
        entity = EntityKind.FAMILIA

    response_mode = infer_response_mode(text_msg)
    if breakdown == BreakdownKind.CRAS and not mentions_sibec:
        response_mode = "ranking"

    filter_labels: list[str] = []
    if _CHILD.search(text_msg) and age_range:
        filter_labels.append(f"crianças de {age_range.label()}")
    elif recorte:
        filter_labels.append(recorte.label_pessoa if entity == EntityKind.PESSOA else recorte.label_familia)
    if age_range and not _CHILD.search(text_msg):
        filter_labels.append(f"idade {age_range.label()}")
    elif age_range and _CHILD.search(text_msg) and f"idade {age_range.label()}" not in filter_labels:
        pass
    if breakdown == BreakdownKind.CRAS:
        filter_labels.append("por CRAS")
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
        breakdown=breakdown,
    )


def merge_task_spec_with_session(
    spec: QueryTaskSpec,
    ctx: SessionContext,
    transcript: list[dict[str, str]] | None = None,
) -> QueryTaskSpec:
    """Acumula filtros da sessão — pivô de assunto não herda faixa etária anterior."""
    msg = (spec.original_question or "").strip()
    msg_recorte = detect_person_recorte(msg)
    recorte = spec.person_recorte or msg_recorte
    age = _resolve_age_for_turn(msg, transcript, ctx, recorte)
    if age is None and spec.age_range:
        age = spec.age_range

    if not recorte and ctx.subject == "mulheres":
        from .cadu_pessoas_metrics import _recorte_mulher
        recorte = _recorte_mulher()
    elif not recorte and ctx.subject == "homens":
        from .cadu_pessoas_metrics import _recorte_homem
        recorte = _recorte_homem()
    elif not recorte and ctx.subject == "idosos":
        from .cadu_pessoas_metrics import _recorte_idoso
        recorte = _recorte_idoso()

    breakdown = spec.breakdown
    if breakdown == BreakdownKind.NONE:
        breakdown = _parse_breakdown(msg, ctx, transcript)

    recorte = _resolve_person_recorte_with_age(msg, recorte, age)

    requires_pbf = spec.requires_pbf_folha or (
        ctx.requires_pbf
        and not _SIBEC.search(msg)
        and not _PBF.search(msg)
    ) or bool(
        _PBF.search(msg)
        and (
            re.search(r"\bfam[ií]lias?\b", msg, re.I)
            or re.search(r"recebendo\s+(?:o\s+)?(?:pbf|bolsa)", msg, re.I)
        )
        and not _SIBEC.search(msg)
    )

    territory = spec.territory
    if breakdown == BreakdownKind.CRAS:
        territory = TerritorySpec(TerritoryKind.MUNICIPIO, None)
    elif not territory or territory.kind == TerritoryKind.MUNICIPIO:
        if ctx.last_bairro:
            territory = TerritorySpec(TerritoryKind.BAIRRO, ctx.last_bairro)
        elif ctx.last_cras:
            territory = TerritorySpec(TerritoryKind.CRAS, ctx.last_cras)

    filter_labels = list(spec.filter_labels)
    subject_pivot = bool(_SUBJECT_PIVOT.match(msg))
    if not subject_pivot:
        for f in ctx.filters:
            if f not in filter_labels and not f.startswith("cod_sexo"):
                filter_labels.append(f)

    if age and not any(
        f.startswith("idade ") or f.startswith("crianças de ") for f in filter_labels
    ):
        if _CHILD.search(msg) and age:
            filter_labels.append(f"crianças de {age.label()}")
        elif age:
            filter_labels.append(f"idade {age.label()}")

    if requires_pbf and "família na folha PBF" not in filter_labels:
        filter_labels.append("família na folha PBF")

    if breakdown == BreakdownKind.CRAS and "por CRAS" not in filter_labels:
        filter_labels.append("por CRAS")

    stem = ctx.question_stem or spec.original_question
    return replace(
        spec,
        person_recorte=recorte or spec.person_recorte,
        age_range=age,
        territory=territory or spec.territory,
        filter_labels=list(dict.fromkeys(filter_labels)),
        original_question=spec.original_question or stem,
        requires_pbf_folha=requires_pbf,
        cohort_followup=spec.cohort_followup
        or bool(_COHORT.search(msg) or _COHORT_AGE.search(msg)),
        breakdown=breakdown,
    )


def legacy_cadu_recorte_covers_spec(spec: QueryTaskSpec) -> bool:
    """Atalho antigo só quando NÃO há faixa etária extra além do recorte fixo."""
    if spec.wants_cras_breakdown() or spec.requires_pbf_folha or spec.cohort_followup:
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

    if spec.wants_cras_breakdown():
        if "group by" not in low or "num_cras" not in low:
            missing.append("desdobramento por CRAS (GROUP BY num_cras)")

    if spec.mentions_sibec():
        if "sibec" not in low and "teve_bloqueio" not in low and "teve_cancelamento" not in low:
            missing.append("manutenção SIBEC (mvw_sibec_manut_familia_mes / teve_bloqueio)")

    if _RACA.search(spec.original_question or ""):
        if "cod_raca_cor" not in low and "raca" not in low:
            missing.append("raça/cor (cod_raca_cor_pessoa)")

    return len(missing) == 0, missing
