"""Modelo de dados VigIA — chaves de junção e receitas SQL entre views."""

from __future__ import annotations

from sqlalchemy.engine import Connection

from ..vigilance.familia_mview import _table_exists
from .ivs_metrics import build_ivs_assist_hint

JOIN_CATALOG = """
## Chaves de junção (sempre use estas relações)

| De | Para | Chave | Uso |
|----|------|-------|-----|
| vig.mvw_pessoas p | vig.mvw_familia f | p.codigo_familiar = f.codigo_familiar | pessoa → território CRAS/bairro |
| vig.mvw_familia_domicilio d | vig.mvw_familia f | d.codigo_familiar = f.codigo_familiar | moradia / dimensão CH |
| core.mvw_ivs_familia i | vig.mvw_familia f | i.codigo_familiar = f.codigo_familiar | IVS + território |
| vig.mvw_sisc_qualificado s | vig.mvw_familia f | s.codigo_familiar = f.codigo_familiar (quando vinculado) | SISC × CADU |
| vig.mvw_sisc_qualificado s | vig.mvw_pessoas p | s.nis_norm = p.num_nis (via NIS) | atendido SISC × pessoa |

## Território (sempre via vig.mvw_familia)
- CRAS territorial: f.num_cras, f.nom_cras (geo via CEP — NÃO confundir com s.cras_codigo do SISC)
- Bairro territorial: btrim(f.bairro::text)
- IVS não tem bairro — join com f

## Receitas SQL (copie e adapte)

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

### Bairro com maior demanda dentro de um CRAS
```sql
SELECT btrim(f.bairro::text) AS bairro,
       COUNT(p.cadu_row_id)::bigint AS total
FROM vig.mvw_pessoas p
INNER JOIN vig.mvw_familia f ON f.codigo_familiar = p.codigo_familiar
WHERE p.idade BETWEEN 12 AND 15
  AND btrim(f.num_cras::text) = '6'
  AND btrim(COALESCE(f.bairro::text, '')) <> ''
GROUP BY btrim(f.bairro::text)
ORDER BY total DESC
LIMIT 1
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
- **Quem já está matriculado no SISC** → mvw_sisc_qualificado
- **IVS / IVCAD** → core.mvw_ivs_familia i JOIN f; filtro i.elegivel_ivs
"""


def build_data_agent_context(conn: Connection, *, thread_brief: str = "") -> str:
    parts = [JOIN_CATALOG.strip()]

    availability = []
    for schema, view in (
        ("vig", "mvw_familia"),
        ("vig", "mvw_pessoas"),
        ("vig", "mvw_familia_domicilio"),
        ("vig", "mvw_sisc_qualificado"),
        ("core", "mvw_ivs_familia"),
    ):
        ok = _table_exists(conn, schema, view)
        availability.append(f"- {schema}.{view}: {'OK' if ok else 'AUSENTE — refresh necessário'}")
    parts.append("## Views disponíveis agora\n" + "\n".join(availability))
    parts.append(build_ivs_assist_hint())

    if thread_brief.strip():
        parts.append("## Contexto desta conversa\n" + thread_brief.strip())

    return "\n\n".join(parts)
