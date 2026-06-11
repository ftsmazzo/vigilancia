"""Estrutura reflexiva do Especialista Analítico — base multi-ótica para decisão territorial.

Documenta COMO pensar (playbook) e COLETA fatos (eixos A–G) a partir das views VigSocial.
Versão evolutiva: incremente REFLEXION_VERSION ao alterar lógica ou eixos.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from ..ivs.catalog import DIMENSOES
from ..municipio_context import get_or_create_context
from ..vigilance.familia_mview import _table_exists
from .evidence import EvidencePack

REFLEXION_VERSION = "2.0"

_PLANNING_METRICS = (
    "planning_carencia",
    "planning_bairro_em_cras",
    "planning_cras_demanda",
    "planning_diagnostico_bairro",
    "planning_reflexion",
)

_CADU_SIM = "btrim(COALESCE({col}::text, '')) IN ('1', '01', 'sim', 's', 'true', 'yes')"


@dataclass(frozen=True)
class ReflexionAxis:
    code: str
    name: str
    question: str
    sources: str


REFLEXION_AXES: tuple[ReflexionAxis, ...] = (
    ReflexionAxis(
        "A",
        "Demanda e população",
        "Quem mora no território e quantos estão na faixa etária do serviço?",
        "vig.mvw_pessoas × vig.mvw_familia",
    ),
    ReflexionAxis(
        "B",
        "Oferta, carência e rede",
        "O que já existe (SISC, serviços cadastrados) e quanto falta atender?",
        "vig.mvw_sisc_qualificado + cadastro municipal",
    ),
    ReflexionAxis(
        "C",
        "Economia, benefícios e cadastro",
        "Qual a concentração de pobreza, PBF e atualização do CADU?",
        "vig.mvw_familia (+ SIBEC via marc_pbf)",
    ),
    ReflexionAxis(
        "D",
        "IVS multidimensional",
        "Qual o perfil de vulnerabilidade estrutural (6 dimensões + composto)?",
        "core.mvw_ivs_familia × vig.mvw_familia",
    ),
    ReflexionAxis(
        "E",
        "Moradia e riscos domiciliares",
        "Há insegurança alimentar, violação de direitos ou riscos de moradia?",
        "vig.mvw_familia_domicilio × vig.mvw_familia",
    ),
    ReflexionAxis(
        "F",
        "Proteção e fragilidades individuais",
        "Trabalho infantil, fora da escola, deficiência, situação de rua?",
        "vig.mvw_pessoas × vig.mvw_familia",
    ),
    ReflexionAxis(
        "G",
        "Território e articulação",
        "CRAS territorial, georreferenciamento, deslocamento SISC × território?",
        "vig.mvw_familia + vig.mvw_sisc_qualificado",
    ),
    ReflexionAxis(
        "H",
        "Síntese reflexiva",
        "Como os eixos se combinam para recomendar, condicionar ou investigar?",
        "playbook + fatos verificados",
    ),
)


@dataclass
class TerritorialReflexion:
    bairro: str
    faixa_etaria: str
    facts: list[dict[str, Any]] = field(default_factory=list)
    synthesis_guide: str = ""
    axes_present: list[str] = field(default_factory=list)

    def to_preview(self) -> list[dict[str, Any]]:
        return self.facts


def is_planning_decision_context(pack: EvidencePack, message: str = "") -> bool:
    blob = f"{message} {pack.metric} {pack.thread_brief}".lower()
    if pack.metric in _PLANNING_METRICS or pack.metric.startswith("planning_"):
        return True
    return bool(
        re.search(
            r"implantar|scfv|car[eê]ncia|demanda|qual\s+cras|qual\s+bairro|"
            r"servi[cç]o\s+de\s+conviv|planej|diagn[oó]stic|prioriz",
            blob,
        )
    )


def build_reflexion_playbook() -> str:
    axes_table = "\n".join(
        f"| **{a.code}** | {a.name} | {a.question} |"
        for a in REFLEXION_AXES[:-1]
    )
    ivs_dims = "; ".join(f"**{d.sigla}** ({d.nome})" for d in DIMENSOES)

    return f"""### Estrutura reflexiva VigIA (v{REFLEXION_VERSION})

Você é um **analista socioassistencial reflexivo**. **Pensa** em eixos A–G internamente; **escreve**
de forma **objetiva e proporcional** ao que o gestor perguntou — sem enrolação nem dados a mais.
IVS é **um eixo (D)**, não a resposta inteira, salvo quando a pergunta for especificamente sobre IVS.

#### Mapa de eixos
| Eixo | Nome | Pergunta central |
|------|------|------------------|
{axes_table}

#### Eixo D — IVS sem reducionismo
Dimensões disponíveis: {ivs_dims}. Escala **0 a 1** (maior = mais vulnerável na dimensão).
- **SCFV infância/adolescência:** cruze **A** (demanda faixa) + **B** (carência) + **D.DCA/NC** + **F** (escola, trabalho infantil).
- **SCFV primeira infância:** **D.DPI/NC** + **E** (moradia/alimentação).
- IVS **baixo** modera urgência estrutural; **não anula** carência (**B**) nem pobreza (**C**).

#### Proporcionalidade da resposta (obrigatório)
| Modo | Quando | Como escrever |
|------|--------|---------------|
| **DADO** | "quantos", "qual índice", "qual CRAS" (sem pedir análise) | **1–2 frases** — número + recorte |
| **LISTA** | ranking, comparativo, "quais CRAS" | Lista objetiva; intro de 1 frase no máximo |
| **INTERPRETAÇÃO** | carência, implantar, indicar, "tem serviço?" | **2–4 frases** — só eixos pertinentes + conclusão |
| **OBJETIVO** | demais casos | **1–3 frases** — responda ao pedido, nada extra |

Coletar muitos eixos **não** significa citar todos na resposta. Use o guia reflexivo para **pesar**,
não para **despejar** dados.

#### Ciclo reflexivo (interno — não expor na resposta salvo se pedirem análise)
1. **Observar** — quais eixos têm fatos.
2. **Contrastar** — alinhamentos e conflitos (tabela abaixo).
3. **Decidir** — o que entra na resposta **curta** ao gestor.
4. **Limites** — só mencione se a pergunta for interpretativa e houver ressalva relevante.

#### Matriz de contrastes (decisão)
| Padrão | Leitura reflexiva |
|--------|-------------------|
| A↑ demanda + B↑ carência + D↓ IVS | Prioridade operacional (**atender quem não está**); IVS baixo modera, não veta |
| A↑ + B↓ cobertura SISC (>70%) | Foco em **ampliação/qualidade**, não implantação do zero |
| C↑ pobreza + E↑ riscos domiciliares | Reforço de proteção social; SCFV pode ser insuficiente sozinho — sinalize |
| F↑ trabalho infantil / fora da escola | Adiciona urgência de proteção além da contagem etária |
| G: SISC em CRAS ≠ CRAS territorial | Articulação territorial relevante — mencione se constar nos fatos |
| C: CADU desatualizado (TAC alto) | Ressalva: demanda pode estar subestimada — mencione se fato presente |
| Eixo sem fato | Não invente; diga que aquele eixo ficou indeterminado |

#### Roteiro quando o gestor pede INTERPRETAÇÃO (não use inteiro em pergunta só de dado)
1. Recorte breve (bairro/faixa/CRAS).
2. Fatos centrais à pergunta (ex.: carência → A+B).
3. Um contraste relevante se houver (ex.: IVS baixo + carência alta).
4. Conclusão em **uma frase**.

#### Hierarquia de verdade
1. Fatos verificados (campos `Lente` / `Eixo` nos fatos).
2. Playbook + panorama rede/município.
3. RAG técnico (SUAS, metodologia).
4. **Proibido:** inventar número, misturar demanda CADU com matrícula SISC, fechar só no IVS.

#### Sinais nos fatos (campo `signal` quando presente)
- `reforça_prioridade` — pesa a favor de implantar/priorizar.
- `modera` — reduz urgência estrutural (ex.: IVS baixo).
- `alerta` — risco/proteção (trabalho infantil, violação direitos).
- `ressalva` — limitação metodológica (CADU desatualizado, sem geo).
- `neutro` — descritivo, sem peso decisório isolado.
"""


def build_playbook_for_pack(pack: EvidencePack, message: str = "") -> str:
    if not is_planning_decision_context(pack, message):
        return ""
    return build_reflexion_playbook()


def build_planning_playbook() -> str:
    """Alias retrocompatível."""
    return build_reflexion_playbook()


# --- Coleta de fatos ---------------------------------------------------------

def _fmt_int(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _fmt_idx(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(c for c in normalized if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", stripped.lower().strip())


def _fact(
    axis: str,
    label: str,
    value: str,
    source: str,
    detail: str = "",
    *,
    signal: str = "neutro",
) -> dict[str, Any]:
    return {
        "axis": axis,
        "label": label,
        "value": value,
        "source": source,
        "detail": detail,
        "signal": signal,
    }


def _match_servicos_bairro(db: Session, bairro: str) -> list[str]:
    ctx = get_or_create_context(db)
    servicos = ctx.servicos or []
    if not isinstance(servicos, list):
        return []
    b_fold = _fold(bairro)
    hits: list[str] = []
    for s in servicos:
        if not isinstance(s, dict):
            continue
        blob = _fold(
            " ".join(str(s.get(k) or "") for k in ("nome", "tipo", "publico", "observacao"))
        )
        if b_fold and b_fold in blob:
            nome = s.get("nome") or "Serviço"
            tipo = s.get("tipo") or ""
            pub = s.get("publico") or ""
            line = nome + (f" ({tipo})" if tipo else "")
            if pub:
                line += f" — {pub}"
            hits.append(line)
    return hits[:6]


def _ivs_nivel(v: float) -> str:
    if v >= 0.45:
        return "elevado"
    if v >= 0.25:
        return "moderado"
    return "baixo"


def _ivs_tendencia(v: float, ref: float | None) -> str:
    if ref is None:
        return ""
    diff = v - ref
    tend = "acima" if diff > 0.02 else ("abaixo" if diff < -0.02 else "próximo")
    return f"; município {_fmt_idx(ref)} ({tend} da média)"


def build_synthesis_guide(facts: list[dict[str, Any]], *, bairro: str, faixa: str) -> str:
    axes = sorted({str(f.get("axis", "")) for f in facts if f.get("axis")})
    signals: dict[str, list[str]] = {}
    for f in facts:
        sig = str(f.get("signal") or "neutro")
        if sig != "neutro":
            signals.setdefault(sig, []).append(str(f.get("label", ""))[:60])

    lines = [
        f"Guia de síntese reflexiva — **{bairro}**, faixa **{faixa}**.",
        f"Eixos com dados: {', '.join(axes) or 'nenhum'}.",
    ]
    if signals.get("reforça_prioridade"):
        lines.append(
            "Sinais que **reforçam prioridade**: "
            + "; ".join(signals["reforça_prioridade"][:4])
            + "."
        )
    if signals.get("modera"):
        lines.append(
            "Sinais que **moderam** urgência estrutural: "
            + "; ".join(signals["modera"][:3])
            + "."
        )
    if signals.get("alerta"):
        lines.append(
            "Sinais de **alerta** (proteção): "
            + "; ".join(signals["alerta"][:3])
            + "."
        )
    if signals.get("ressalva"):
        lines.append("Ressalvas: " + "; ".join(signals["ressalva"][:2]) + ".")
    lines.append(
        "Na resposta ao gestor: cite só fatos pertinentes à pergunta — modo proporcional."
    )
    return " ".join(lines)


def collect_territorial_reflexion(
    conn: Connection,
    db: Session,
    *,
    bairro: str,
    age_min: int,
    age_max: int,
    num_cras: str | None = None,
    demanda: int | None = None,
    sisc: int | None = None,
) -> TerritorialReflexion:
    """Coleta fatos multi-eixo para o Especialista — máximo disponível nas views."""
    faixa = f"{age_min} a {age_max} anos"
    b = bairro.strip()
    facts: list[dict[str, Any]] = []
    axes_present: set[str] = set()
    terr: dict[str, Any] = {}

    # --- G / contexto territorial ---
    if num_cras:
        facts.append(
            _fact(
                "G",
                "CRAS territorial de referência",
                num_cras,
                "vig.mvw_familia / conversa",
                "unidade que territorializa o bairro via geo",
                signal="neutro",
            )
        )
        axes_present.add("G")

    if _table_exists(conn, "vig", "mvw_familia"):
        terr = conn.execute(
            text(
                """
                SELECT
                  COUNT(DISTINCT f.codigo_familiar)::bigint AS familias,
                  COUNT(DISTINCT f.codigo_familiar) FILTER (
                    WHERE COALESCE(f.tem_geo, FALSE)
                  )::bigint AS com_geo,
                  MAX(btrim(f.num_cras::text)) AS num_cras_geo
                FROM vig.mvw_familia f
                WHERE btrim(f.bairro::text) = :bairro
                """
            ),
            {"bairro": b},
        ).mappings().first() or {}
        terr = dict(terr)
        fam_total = int(terr.get("familias") or 0)
        com_geo = int(terr.get("com_geo") or 0)
        if fam_total:
            sem_geo = fam_total - com_geo
            pct_geo = round(100.0 * com_geo / fam_total, 1)
            facts.append(
                _fact(
                    "G",
                    f"Famílias no bairro {b}",
                    _fmt_int(fam_total),
                    "vig.mvw_familia",
                    f"{pct_geo:.1f}% com geo (CEP); {_fmt_int(sem_geo)} sem referência geo",
                    signal="ressalva" if sem_geo > fam_total * 0.15 else "neutro",
                )
            )
            if not num_cras and terr.get("num_cras_geo"):
                facts.append(
                    _fact(
                        "G",
                        "CRAS territorial (geo)",
                        str(terr["num_cras_geo"]),
                        "vig.mvw_familia",
                        "CRAS predominante no recorte",
                    )
                )
            axes_present.add("G")

    # --- A — demanda ---
    if demanda is None and _table_exists(conn, "vig", "mvw_pessoas"):
        row = conn.execute(
            text(
                """
                SELECT COUNT(p.cadu_row_id)::bigint AS n
                FROM vig.mvw_pessoas p
                INNER JOIN vig.mvw_familia f ON f.codigo_familiar = p.codigo_familiar
                WHERE p.idade >= :age_min AND p.idade <= :age_max AND p.idade IS NOT NULL
                  AND btrim(f.bairro::text) = :bairro
                """
            ),
            {"age_min": age_min, "age_max": age_max, "bairro": b},
        ).mappings().first()
        demanda = int((row or {}).get("n") or 0)

    dem = demanda or 0
    sig_a = "reforça_prioridade" if dem >= 100 else ("neutro" if dem >= 30 else "modera")
    facts.append(
        _fact(
            "A",
            f"Demanda CADU ({faixa}) — {b}",
            str(dem),
            "vig.mvw_pessoas × vig.mvw_familia",
            "público potencial com residência territorial no bairro",
            signal=sig_a,
        )
    )
    axes_present.add("A")

    if _table_exists(conn, "vig", "mvw_pessoas"):
        pop = conn.execute(
            text(
                """
                SELECT COUNT(p.cadu_row_id)::bigint AS total
                FROM vig.mvw_pessoas p
                INNER JOIN vig.mvw_familia f ON f.codigo_familiar = p.codigo_familiar
                WHERE btrim(f.bairro::text) = :bairro
                """
            ),
            {"bairro": b},
        ).scalar()
        facts.append(
            _fact(
                "A",
                f"Total de pessoas CADU — {b}",
                _fmt_int(int(pop or 0)),
                "vig.mvw_pessoas",
                "universo territorial de referência",
            )
        )

    # --- B — oferta / carência ---
    if sisc is None and _table_exists(conn, "vig", "mvw_sisc_qualificado"):
        row = conn.execute(
            text(
                """
                SELECT COUNT(DISTINCT s.nis_norm)::bigint AS n
                FROM vig.mvw_sisc_qualificado s
                INNER JOIN vig.mvw_familia f ON f.codigo_familiar = s.codigo_familiar
                WHERE s.classificacao_vinculo = 'vinculado_cadu'
                  AND s.cadu_idade >= :age_min AND s.cadu_idade <= :age_max
                  AND btrim(f.bairro::text) = :bairro
                """
            ),
            {"age_min": age_min, "age_max": age_max, "bairro": b},
        ).mappings().first()
        sisc = int((row or {}).get("n") or 0)
    elif sisc is None:
        facts.append(
            _fact(
                "B",
                f"Matriculados SISC ({faixa}) — {b}",
                "indisponível",
                "vig.mvw_sisc_qualificado",
                "qualificar SISC em Convivência",
                signal="ressalva",
            )
        )

    if sisc is not None:
        carencia = max(dem - sisc, 0)
        cobertura = round(100.0 * sisc / dem, 1) if dem > 0 else 0.0
        sig_b = (
            "reforça_prioridade"
            if dem > 0 and cobertura < 30
            else ("modera" if cobertura >= 70 else "neutro")
        )
        facts.append(
            _fact(
                "B",
                f"Matriculados SISC ({faixa}) — {b}",
                str(sisc),
                "vig.mvw_sisc_qualificado × vig.mvw_familia",
                f"cobertura estimada {cobertura:.1f}% da demanda CADU",
                signal=sig_b,
            )
        )
        facts.append(
            _fact(
                "B",
                "Carência (demanda − SISC)",
                str(carencia),
                "cruzamento CADU × SISC",
                "público na faixa sem matrícula no bairro",
                signal="reforça_prioridade" if carencia > 50 else "neutro",
            )
        )
        axes_present.add("B")

        if _table_exists(conn, "vig", "mvw_sisc_qualificado"):
            prio = conn.execute(
                text(
                    """
                    SELECT COUNT(DISTINCT s.nis_norm)::bigint AS n
                    FROM vig.mvw_sisc_qualificado s
                    INNER JOIN vig.mvw_familia f ON f.codigo_familiar = s.codigo_familiar
                    WHERE s.classificacao_vinculo = 'vinculado_cadu'
                      AND s.classificacao_atendimento = 'prioritario'
                      AND s.cadu_idade >= :age_min AND s.cadu_idade <= :age_max
                      AND btrim(f.bairro::text) = :bairro
                    """
                ),
                {"age_min": age_min, "age_max": age_max, "bairro": b},
            ).scalar()
            if int(prio or 0):
                facts.append(
                    _fact(
                        "B",
                        "SISC prioritário no bairro (faixa)",
                        str(int(prio)),
                        "vig.mvw_sisc_qualificado",
                        "matrículas com situação prioritária no SISC",
                    )
                )

            cras_sisc = conn.execute(
                text(
                    """
                    SELECT
                      COALESCE(NULLIF(btrim(s.cras_codigo::text), ''), '?') AS cod,
                      COALESCE(NULLIF(btrim(s.cras_nome::text), ''), '(sem nome)') AS nome,
                      COUNT(DISTINCT s.nis_norm)::bigint AS n
                    FROM vig.mvw_sisc_qualificado s
                    INNER JOIN vig.mvw_familia f ON f.codigo_familiar = s.codigo_familiar
                    WHERE s.classificacao_vinculo = 'vinculado_cadu'
                      AND s.cadu_idade >= :age_min AND s.cadu_idade <= :age_max
                      AND btrim(f.bairro::text) = :bairro
                    GROUP BY 1, 2
                    ORDER BY n DESC
                    LIMIT 3
                    """
                ),
                {"age_min": age_min, "age_max": age_max, "bairro": b},
            ).mappings().all()
            if cras_sisc:
                top = cras_sisc[0]
                cras_ter = num_cras or (terr.get("num_cras_geo") if _table_exists(conn, "vig", "mvw_familia") else None)
                mismatch = cras_ter and str(top["cod"]) != str(cras_ter)
                facts.append(
                    _fact(
                        "G",
                        "CRAS da matrícula SISC (principal)",
                        f"{top['nome']} (cód. {top['cod']}) — {_fmt_int(int(top['n']))} NIS",
                        "vig.mvw_sisc_qualificado",
                        "CRAS da matrícula ≠ CRAS territorial" if mismatch else "coincide ou sem CRAS territorial",
                        signal="alerta" if mismatch else "neutro",
                    )
                )
                axes_present.add("G")

    servicos = _match_servicos_bairro(db, bairro)
    facts.append(
        _fact(
            "B",
            "Serviços cadastrados (menção ao bairro)",
            "; ".join(servicos) if servicos else "nenhum registrado",
            "cadastro municipal VigSocial",
            "rede declarada — não prova ausência física de equipamento",
            signal="modera" if servicos else "neutro",
        )
    )
    axes_present.add("B")

    # --- C — economia e cadastro ---
    if _table_exists(conn, "vig", "mvw_familia"):
        renda = conn.execute(
            text(
                f"""
                SELECT
                  COUNT(DISTINCT f.codigo_familiar)::bigint AS total,
                  COUNT(DISTINCT f.codigo_familiar) FILTER (
                    WHERE f.renda_per_capita IS NOT NULL AND f.renda_per_capita <= 218
                  )::bigint AS extrema,
                  COUNT(DISTINCT f.codigo_familiar) FILTER (
                    WHERE f.renda_per_capita IS NOT NULL AND f.renda_per_capita <= 706
                  )::bigint AS pobreza,
                  COUNT(DISTINCT f.codigo_familiar) FILTER (
                    WHERE COALESCE(f.marc_pbf, FALSE)
                  )::bigint AS pbf,
                  ROUND(AVG(f.meses_desatualizado) FILTER (
                    WHERE f.meses_desatualizado IS NOT NULL
                  )::numeric, 1) AS tac_medio
                FROM vig.mvw_familia f
                WHERE btrim(f.bairro::text) = :bairro
                """
            ),
            {"bairro": b},
        ).mappings().first() or {}
        total_f = int(renda.get("total") or 0)
        if total_f:
            ext = int(renda.get("extrema") or 0)
            pob = int(renda.get("pobreza") or 0)
            pct_ext = round(100.0 * ext / total_f, 1)
            facts.append(
                _fact(
                    "C",
                    f"Extrema pobreza (≤ R$ 218 p.c.) — {b}",
                    f"{_fmt_int(ext)} ({pct_ext:.1f}%)",
                    "vig.mvw_familia",
                    f"de {_fmt_int(total_f)} famílias no bairro",
                    signal="reforça_prioridade" if pct_ext >= 25 else "neutro",
                )
            )
            facts.append(
                _fact(
                    "C",
                    f"Pobreza (≤ R$ 706 p.c.) — {b}",
                    f"{_fmt_int(pob)} ({round(100.0 * pob / total_f, 1):.1f}%)",
                    "vig.mvw_familia",
                    "vulnerabilidade econômica CADU",
                    signal="reforça_prioridade" if pob / total_f >= 0.4 else "neutro",
                )
            )
            facts.append(
                _fact(
                    "C",
                    f"Famílias na folha PBF — {b}",
                    _fmt_int(int(renda.get("pbf") or 0)),
                    "vig.mvw_familia",
                    "interseção CADU × folha SIBEC",
                )
            )
            tac = renda.get("tac_medio")
            if tac is not None:
                tac_f = float(tac)
                facts.append(
                    _fact(
                        "C",
                        f"TAC médio (meses desatualização CADU) — {b}",
                        f"{tac_f:.1f} meses",
                        "vig.mvw_familia",
                        "cadastro desatualizado pode subestimar demanda",
                        signal="ressalva" if tac_f > 24 else "neutro",
                    )
                )
            axes_present.add("C")

    # --- D — IVS completo ---
    if _table_exists(conn, "core", "mvw_ivs_familia"):
        ivs_b = conn.execute(
            text(
                """
                SELECT
                  ROUND(AVG(i.ivs) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS ivs,
                  ROUND(AVG(i.idx_nc) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS idx_nc,
                  ROUND(AVG(i.idx_dpi) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS idx_dpi,
                  ROUND(AVG(i.idx_dca) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS idx_dca,
                  ROUND(AVG(i.idx_tqa) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS idx_tqa,
                  ROUND(AVG(i.idx_dr) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS idx_dr,
                  ROUND(AVG(i.idx_ch) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS idx_ch,
                  COUNT(*) FILTER (WHERE i.elegivel_ivs)::bigint AS fam
                FROM core.mvw_ivs_familia i
                INNER JOIN vig.mvw_familia f ON f.codigo_familiar = i.codigo_familiar
                WHERE btrim(f.bairro::text) = :bairro
                """
            ),
            {"bairro": b},
        ).mappings().first()
        ivs_m = conn.execute(
            text(
                """
                SELECT
                  ROUND(AVG(i.ivs) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS ivs,
                  ROUND(AVG(i.idx_nc) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS idx_nc,
                  ROUND(AVG(i.idx_dpi) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS idx_dpi,
                  ROUND(AVG(i.idx_dca) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS idx_dca,
                  ROUND(AVG(i.idx_tqa) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS idx_tqa,
                  ROUND(AVG(i.idx_dr) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS idx_dr,
                  ROUND(AVG(i.idx_ch) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS idx_ch
                FROM core.mvw_ivs_familia i
                INNER JOIN vig.mvw_familia f ON f.codigo_familiar = i.codigo_familiar
                """
            )
        ).mappings().first()

        if ivs_b and int(ivs_b.get("fam") or 0):
            fam_ivs = int(ivs_b["fam"])
            dim_map = [
                ("ivs", "IVS", "Índice composto"),
                ("idx_nc", "NC", "Necessidade de Cuidados"),
                ("idx_dpi", "DPI", "Primeira Infância"),
                ("idx_dca", "DCA", "Crianças e Adolescentes"),
                ("idx_tqa", "TQA", "Trabalho e Qualificação"),
                ("idx_dr", "DR", "Disponibilidade de Recursos"),
                ("idx_ch", "CH", "Condições Habitacionais"),
            ]
            for col, sigla, nome in dim_map:
                val = ivs_b.get(col)
                if val is None:
                    continue
                v = float(val)
                ref = float(ivs_m[col]) if ivs_m and ivs_m.get(col) is not None else None
                nivel = _ivs_nivel(v)
                sig = (
                    "reforça_prioridade"
                    if v >= 0.45 and sigla in ("NC", "DCA", "DPI")
                    else ("modera" if v < 0.25 else "neutro")
                )
                facts.append(
                    _fact(
                        "D",
                        f"IVS {sigla} ({nome}) — {b}",
                        _fmt_idx(v),
                        "core.mvw_ivs_familia",
                        f"{nivel}; {_fmt_int(fam_ivs)} fam. elegíveis{_ivs_tendencia(v, ref)}",
                        signal=sig,
                    )
                )
            axes_present.add("D")
        else:
            facts.append(
                _fact(
                    "D",
                    f"IVS — {b}",
                    "sem famílias elegíveis ou indisponível",
                    "core.mvw_ivs_familia",
                    "decidir com eixos A, B, C, E, F",
                    signal="ressalva",
                )
            )

    # --- E — moradia / riscos ---
    if _table_exists(conn, "vig", "mvw_familia_domicilio"):
        dom = conn.execute(
            text(
                f"""
                SELECT
                  COUNT(DISTINCT d.codigo_familiar)::bigint AS total,
                  COUNT(DISTINCT d.codigo_familiar) FILTER (
                    WHERE {_CADU_SIM.format(col="d.inseguranca_alimentar")}
                  )::bigint AS inseg_alim,
                  COUNT(DISTINCT d.codigo_familiar) FILTER (
                    WHERE {_CADU_SIM.format(col="d.risco_violacao_direitos")}
                  )::bigint AS risco_viol,
                  COUNT(DISTINCT d.codigo_familiar) FILTER (
                    WHERE {_CADU_SIM.format(col="d.gpte")}
                  )::bigint AS gpte
                FROM vig.mvw_familia_domicilio d
                INNER JOIN vig.mvw_familia f ON f.codigo_familiar = d.codigo_familiar
                WHERE btrim(f.bairro::text) = :bairro
                """
            ),
            {"bairro": b},
        ).mappings().first() or {}
        dtot = int(dom.get("total") or 0)
        if dtot:
            for key, label, sig in (
                ("inseg_alim", "Insegurança alimentar (famílias)", "alerta"),
                ("risco_viol", "Risco violação de direitos (famílias)", "alerta"),
                ("gpte", "GPTE — grupo pop. tradicional (famílias)", "neutro"),
            ):
                n = int(dom.get(key) or 0)
                if n:
                    facts.append(
                        _fact(
                            "E",
                            f"{label} — {b}",
                            _fmt_int(n),
                            "vig.mvw_familia_domicilio",
                            f"de {_fmt_int(dtot)} famílias com domicílio",
                            signal=sig,
                        )
                    )
            axes_present.add("E")

    # --- F — proteção individual (faixa etária) ---
    if _table_exists(conn, "vig", "mvw_pessoas"):
        prot = conn.execute(
            text(
                f"""
                SELECT
                  COUNT(p.cadu_row_id) FILTER (
                    WHERE {_CADU_SIM.format(col="p.ind_trabalho_infantil")}
                  )::bigint AS trab_inf,
                  COUNT(p.cadu_row_id) FILTER (
                    WHERE btrim(COALESCE(p.ind_frequenta_escola::text, '')) IN (
                      '0', '00', '2', '02', 'nao', 'não', 'n', 'nao frequenta'
                    )
                  )::bigint AS fora_escola,
                  COUNT(p.cadu_row_id) FILTER (
                    WHERE btrim(COALESCE(p.cod_deficiencia::text, '')) NOT IN (
                      '', '0', '00', 'none', 'nan'
                    )
                  )::bigint AS com_def,
                  COUNT(p.cadu_row_id) FILTER (
                    WHERE {_CADU_SIM.format(col="p.marc_sit_rua")}
                  )::bigint AS sit_rua,
                  COUNT(p.cadu_row_id) FILTER (
                    WHERE {_CADU_SIM.format(col="p.ind_atend_cras")}
                  )::bigint AS atend_cras_cadu
                FROM vig.mvw_pessoas p
                INNER JOIN vig.mvw_familia f ON f.codigo_familiar = p.codigo_familiar
                WHERE btrim(f.bairro::text) = :bairro
                  AND p.idade >= :age_min AND p.idade <= :age_max AND p.idade IS NOT NULL
                """
            ),
            {"bairro": b, "age_min": age_min, "age_max": age_max},
        ).mappings().first() or {}
        for key, label, sig in (
            ("trab_inf", f"Trabalho infantil ({faixa})", "alerta"),
            ("fora_escola", f"Fora da escola ({faixa})", "alerta"),
            ("com_def", f"Com deficiência ({faixa})", "reforça_prioridade"),
            ("sit_rua", f"Situação de rua ({faixa})", "alerta"),
            ("atend_cras_cadu", f"Ind. atend. CRAS no CADU ({faixa})", "neutro"),
        ):
            n = int(prot.get(key) or 0)
            if n:
                facts.append(
                    _fact(
                        "F",
                        f"{label} — {b}",
                        str(n),
                        "vig.mvw_pessoas",
                        "ind_atend_cras = marcador CADU, ≠ matrícula SISC"
                        if key == "atend_cras_cadu"
                        else "pessoas na faixa etária no território",
                        signal=sig,
                    )
                )
        if any(int(prot.get(k) or 0) for k in ("trab_inf", "fora_escola", "sit_rua", "com_def")):
            axes_present.add("F")

    guide = build_synthesis_guide(facts, bairro=b, faixa=faixa)
    return TerritorialReflexion(
        bairro=b,
        faixa_etaria=faixa,
        facts=facts,
        synthesis_guide=guide,
        axes_present=sorted(axes_present),
    )


def build_bairro_diagnostico_facts(
    conn: Connection,
    db: Session,
    *,
    bairro: str,
    age_min: int,
    age_max: int,
    num_cras: str | None = None,
    demanda: int | None = None,
    sisc: int | None = None,
) -> list[dict[str, Any]]:
    """Retrocompatível — retorna fatos da reflexão territorial."""
    reflexion = collect_territorial_reflexion(
        conn,
        db,
        bairro=bairro,
        age_min=age_min,
        age_max=age_max,
        num_cras=num_cras,
        demanda=demanda,
        sisc=sisc,
    )
    return reflexion.facts


def collect_reflexion_result(
    conn: Connection,
    db: Session,
    *,
    bairro: str,
    age_min: int,
    age_max: int,
    num_cras: str | None = None,
    demanda: int | None = None,
    sisc: int | None = None,
) -> dict[str, Any]:
    """Pacote completo para o orquestrador (fatos + guia + metadados)."""
    reflexion = collect_territorial_reflexion(
        conn,
        db,
        bairro=bairro,
        age_min=age_min,
        age_max=age_max,
        num_cras=num_cras,
        demanda=demanda,
        sisc=sisc,
    )
    return {
        "preview": reflexion.facts,
        "reflexion_guide": reflexion.synthesis_guide,
        "reflexion_axes": reflexion.axes_present,
        "reflexion_version": REFLEXION_VERSION,
    }
