"""Modelo de dados VigIA — tronco CADU e ramificações de Vigilância."""

from __future__ import annotations

from sqlalchemy.engine import Connection

from ..vigilance.familia_mview import _table_exists
from .ivs_metrics import build_ivs_assist_hint
from .cadu_pessoas_metrics import build_cadu_pessoas_assist_hint

CADU_TRUNK = """
## Tronco CADU (fonte de verdade — tudo parte daqui)

| Visão | Granularidade | Chaves |
|-------|---------------|--------|
| vig.mvw_familia f | 1 linha / família | codigo_familiar |
| vig.mvw_pessoas p | 1 linha / pessoa | codigo_familiar, num_nis, num_cpf |
| vig.mvw_familia_domicilio d | 1 linha / família | codigo_familiar |

**Regra central:** família e território (CRAS, bairro, geo) vivem em `f`.
Pessoa → família: `p.codigo_familiar = f.codigo_familiar`.
Busca por CPF: `p.num_cpf` → join em `f` pelo codigo_familiar.
Busca por NIS: `p.num_nis` ou `s.nis_norm` (SISC).
"""

VIGILANCIA_LAYERS = """
## Camadas de Vigilância (ramificações do CADU — não são agentes separados)

Tudo que é ingerido e consolidado no sistema alimenta **Vigilância** e se liga ao tronco CADU:

| Camada | Visão | Junção | O que mede |
|--------|-------|--------|------------|
| Território / geo | f.* (bairro, num_cras, cep, tem_geo) | nativa em f | CRAS/bairro via CEP × geo |
| Moradia / CH | vig.mvw_familia_domicilio d | d.codigo_familiar = f.codigo_familiar | piso, banheiro, insegurança alimentar |
| IVS / IVCAD | core.mvw_ivs_familia i | i.codigo_familiar = f.codigo_familiar | vulnerabilidade IN084 |
| Convivência (SISC) | vig.mvw_sisc_qualificado s | s.codigo_familiar = f.codigo_familiar **ou** s.nis_norm = p.num_nis | matrícula no serviço |
| Folha PBF | f.marc_pbf (+ raw SIBEC folha) | codigo_familiar | quem recebe pagamento |
| Manutenções PBF (SIBEC) | vig.mvw_sibec_manut_familia_mes m | m.codigo_familiar = f.codigo_familiar | bloqueio, cancelamento, reversão por competência |

**SIBEC manutenções ≠ folha PBF.** Denominador = famílias distintas com evento no mês (nível 00), não COUNT(*) bruto.
Território em manutenções: m.num_cras / m.bairro já vêm de vig.mvw_familia na MV.
"""

JOIN_CATALOG = """
## Chaves de junção (sempre use estas relações)

| De | Para | Chave | Uso |
|----|------|-------|-----|
| vig.mvw_pessoas p | vig.mvw_familia f | p.codigo_familiar = f.codigo_familiar | pessoa → território CRAS/bairro |
| vig.mvw_familia_domicilio d | vig.mvw_familia f | d.codigo_familiar = f.codigo_familiar | moradia / dimensão CH |
| core.mvw_ivs_familia i | vig.mvw_familia f | i.codigo_familiar = f.codigo_familiar | IVS + território |
| vig.mvw_sisc_qualificado s | vig.mvw_familia f | s.codigo_familiar = f.codigo_familiar | SISC × CADU (família) |
| vig.mvw_sisc_qualificado s | vig.mvw_pessoas p | s.nis_norm = p.num_nis | atendido SISC × pessoa |
| vig.mvw_sibec_manut_familia_mes m | vig.mvw_familia f | m.codigo_familiar = f.codigo_familiar | manutenção × território CADU |

## Território (sempre via vig.mvw_familia)
- CRAS territorial: f.num_cras, f.nom_cras (geo via CEP — NÃO confundir com s.cras_codigo do SISC)
- Bairro territorial: btrim(f.bairro::text)
- IVS e SIBEC manutenções não têm bairro próprio — join com f quando precisar cruzar

## Receitas SQL (copie e adapte)

### Pessoa por CPF → família + CRAS
```sql
SELECT f.codigo_familiar, f.num_cras, f.nom_cras, f.bairro, p.nome
FROM vig.mvw_pessoas p
INNER JOIN vig.mvw_familia f ON f.codigo_familiar = p.codigo_familiar
WHERE regexp_replace(btrim(p.num_cpf::text), '[^0-9]', '', 'g') = :cpf_digits
LIMIT 5
```

### Demanda CADU — crianças por faixa etária por CRAS territorial (planejamento SCFV)
```sql
SELECT btrim(f.num_cras::text) AS num_cras,
       MAX(btrim(f.nom_cras::text)) AS nom_cras,
       COUNT(p.cadu_row_id)::bigint AS total
FROM vig.mvw_pessoas p
INNER JOIN vig.mvw_familia f ON f.codigo_familiar = p.codigo_familiar
WHERE p.idade BETWEEN 12 AND 15 AND p.idade IS NOT NULL
  AND btrim(COALESCE(f.num_cras::text, '')) <> ''
GROUP BY btrim(f.num_cras::text)
ORDER BY total DESC
```

### Bloqueios SIBEC × território (famílias distintas no mês)
```sql
SELECT COUNT(*)::bigint AS familias
FROM vig.mvw_sibec_manut_familia_mes m
WHERE m.competencia = :comp
  AND m.teve_bloqueio
  AND btrim(COALESCE(m.num_cras::text, '')) = :num_cras
```

### IVS dimensão NC por bairro
```sql
SELECT ROUND(AVG(i.idx_nc) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS idx_nc,
       COUNT(*) FILTER (WHERE i.elegivel_ivs)::bigint AS familias
FROM core.mvw_ivs_familia i
INNER JOIN vig.mvw_familia f ON f.codigo_familiar = i.codigo_familiar
WHERE i.elegivel_ivs AND lower(btrim(f.bairro::text)) = lower('Campos Elíseos')
```

### Matrícula SISC existente por CRAS da matrícula (NÃO usar para planejar novo SCFV)
```sql
SELECT s.cras_codigo, s.cras_nome, COUNT(DISTINCT s.nis_norm)::bigint AS atendidos
FROM vig.mvw_sisc_qualificado s
WHERE s.classificacao_vinculo = 'vinculado_cadu'
GROUP BY s.cras_codigo, s.cras_nome
ORDER BY atendidos DESC
```

## Regras de roteamento de dados
- **Planejar novo SCFV / implantar serviço / qual CRAS indicar** → receita CADU (p×f), NUNCA mvw_sisc_qualificado
- **Ação desbloqueio PBF / bloqueio Bolsa Família por bairro** → vig.mvw_sibec_manut_familia_mes (teve_bloqueio, competência); ranking territorial por bairro
- **Quem já está matriculado no SISC** → mvw_sisc_qualificado
- **IVS / IVCAD** → core.mvw_ivs_familia i JOIN f; filtro i.elegivel_ivs
- **Manutenções PBF (bloqueio/cancelamento/reversão)** → vig.mvw_sibec_manut_familia_mes; COUNT famílias distintas; competencia AAAAMM
- **Folha PBF** → f.marc_pbf ou raw SIBEC folha — denominador diferente de manutenções
"""


def build_data_agent_context(conn: Connection, *, thread_brief: str = "") -> str:
    parts = [
        CADU_TRUNK.strip(),
        VIGILANCIA_LAYERS.strip(),
        JOIN_CATALOG.strip(),
    ]

    availability = []
    for schema, view in (
        ("vig", "mvw_familia"),
        ("vig", "mvw_pessoas"),
        ("vig", "mvw_familia_domicilio"),
        ("vig", "mvw_sisc_qualificado"),
        ("vig", "mvw_sibec_manut_familia_mes"),
        ("core", "mvw_ivs_familia"),
    ):
        ok = _table_exists(conn, schema, view)
        availability.append(f"- {schema}.{view}: {'OK' if ok else 'AUSENTE — refresh necessário'}")
    parts.append("## Views disponíveis agora\n" + "\n".join(availability))
    parts.append(build_ivs_assist_hint())
    parts.append(build_cadu_pessoas_assist_hint())

    if thread_brief.strip():
        parts.append("## Contexto desta conversa\n" + thread_brief.strip())

    return "\n\n".join(parts)
