# IVCAD — Dimensão NC (Necessidade de Cuidados)

> **IN078** — dimensão NC · **VD001–VD007** — indicadores binários  
> **Fórmula dimensão:** `idx_nc = (NC1 + NC2 + NC3 + NC4 + NC5 + NC6 + NC7) / 7`  
> **Referência:** [`02-ivcad-processo.md`](./02-ivcad-processo.md) · **[Guia completo IVCAD](./ivcad/GUIA-REFERENCIA.md)** (processo + SQL)

---

## 1. Interpretação (IN078)

A dimensão **NC** identifica famílias com **maior presença de grupos que demandam cuidado** (crianças, PCD, idosos) em relação à **capacidade de cuidado** (proporção de adultos, especialmente mulheres adultas).

O **índice sintético da dimensão** = proporção média dos 7 indicadores binários (0 ou 1) — mesmo grain **família**.

| Metadado | Valor |
|----------|-------|
| Domínio | 0 a 1 |
| Fonte | Cadastro Único |
| Periodicidade | Mensal |
| Desagregação MDS | Municipal |
| Desagregação VigSocial | Municipal + **CRAS** + **bairro** |

---

## 2. Matriz de indicadores (implementável)

| ID | Código VD | Indicador | Valor 1 quando | Campos CECAD (MDS) | VigSocial (`mvw_pessoas`) | Status |
|----|-----------|-----------|----------------|--------------------|---------------------------|--------|
| NC1 | VD001 | Criança 0–3 anos | ∃ membro com idade ≤ 3 | `IDADE` ← `DT_EXTRACAO` − `DT_NASC` | `idade <= 3` | ✅ |
| NC2 | VD002 | Criança 0–6 anos | ∃ membro com idade ≤ 6 | idem | `idade <= 6` | ✅ |
| NC3 | VD003 | Criança/adolescente 0–12 | ∃ membro com idade ≤ 12 | idem | `idade <= 12` | ✅ |
| NC4 | VD004 | Pessoa com deficiência | ∃ membro `CO_DEFICIENCIA_MEMB = 1` | `CO_DEFICIENCIA_MEMB` | `cod_deficiencia` / `tem_deficiencia_expr` | ✅ |
| NC5 | VD005 | Idoso 60+ | ∃ membro com idade ≥ 60 | `IDADE` | `idade >= 60` | ✅ |
| NC6 | VD006 | ≤ 50% adultos (18–59) | `(adultos 18–59) / (total membros) ≤ 0,5` | `IDADE` | agregação por `codigo_familiar` | ✅ |
| NC7 | VD007 | ≤ 50% mulheres adultas + dependente* | ver §3 | `IDADE`, `CO_SEXO_PESSOA`, `CO_DEFICIENCIA_MEMB` | idem | ✅ |

\* Dependente = ∃ membro ≤ 12 **ou** ≥ 60 **ou** PCD (v1.0.5).

### 2.1 SQL conceitual por família (pseudo)

```sql
-- Por codigo_familiar, apenas famílias no universo IVCAD (ver 02-ivcad-processo.md)

NC1 = MAX(CASE WHEN idade <= 3  THEN 1 ELSE 0 END)
NC2 = MAX(CASE WHEN idade <= 6  THEN 1 ELSE 0 END)
NC3 = MAX(CASE WHEN idade <= 12 THEN 1 ELSE 0 END)
NC4 = MAX(CASE WHEN cod_deficiencia = '1' OR tem_deficiencia THEN 1 ELSE 0 END)
NC5 = MAX(CASE WHEN idade >= 60 THEN 1 ELSE 0 END)

NC6 = CASE
  WHEN COUNT(*) FILTER (WHERE idade BETWEEN 18 AND 59)::float
       / NULLIF(COUNT(*), 0) <= 0.5
  THEN 1 ELSE 0 END

NC7 = CASE
  WHEN (
    MAX(CASE WHEN idade <= 12 THEN 1 ELSE 0 END) = 1
    OR MAX(CASE WHEN idade >= 60 THEN 1 ELSE 0 END) = 1
    OR MAX(CASE WHEN tem_deficiencia THEN 1 ELSE 0 END) = 1
  )
  AND (
    COUNT(*) FILTER (WHERE idade BETWEEN 18 AND 59 AND cod_sexo IN ('2','02'))::float
    / NULLIF(COUNT(*), 0) <= 0.5
  )
  THEN 1 ELSE 0 END

idx_nc = (NC1 + NC2 + NC3 + NC4 + NC5 + NC6 + NC7) / 7.0
```

---

## 3. NC7 — regra completa (v1.0.5)

**Pré-condição** (pelo menos uma):

- criança ≤ 12 anos, **ou**
- idoso ≥ 60 anos, **ou**
- pessoa com deficiência

**Condição de vulnerabilidade:**

```
(count mulheres 18–59) / (count total membros família) <= 0,5
```

Onde mulher = `CO_SEXO_PESSOA = 2` (feminino).

> Alteração **v1.0.5** (IN084): NC7 passou a exigir explicitamente a presença de dependente (criança ≤12, idoso ou PCD), não apenas baixa proporção de mulheres adultas.

---

## 4. Painel Observatório (print NC)

| Elemento UI | Conteúdo |
|-------------|----------|
| Roda 6 dimensões | Navegação NC ↔ DPI ↔ DCA ↔ TQA ↔ DR ↔ CH |
| Barra índice NC | Ex.: Brasil **0,354** |
| Barras por indicador | % famílias com NC1…NC7 = 1 (universo IVCAD) |
| Informações gerais | IVCAD-NC, famílias analisadas (ex.: 26,3 mi = 62,1% do CADU) |

**Agregação territorial:** `AVG(idx_nc)` ou `% famílias com flag=1` sobre famílias **elegíveis ao universo IVCAD**.

---

## 5. Pontos de atenção (clareza × implementação)

### ✅ Documentação clara

- Fórmula da dimensão explícita (média de 7 flags).  
- Cada VD001–VD007 tem regra binária implementável.  
- NC7 detalhado na metodologia VD007 (condicional composta).  
- Print alinha com IN078 (lista NC1–NC7 + percentuais).

### ⚠️ Ajustes VigSocial (demais temas)

| Tema | MDS | VigSocial | Ação |
|------|-----|-----------|------|
| **Cálculo de idade** | `DT_EXTRACAO_DADOS − DT_NASC` | Ver **decisão D10** abaixo | Dois modos: operacional vs conciliação MDS |
| **Denominador NC6/NC7** | “total de pessoas da família” | todos os membros no CADU | Contar linhas `mvw_pessoas` por `codigo_familiar` |
| **Deficiência NC4** | `CO_DEFICIENCIA_MEMB = 1` | `cod_deficiencia` + flags `ind_def_*` | Alinhar ao MDS ou documentar diferença — **decidir** |
| **Universo** | PBF ou (≤24m e renda ≤ ½ SM) | ainda não aplicado no cálculo | Filtrar **antes** de NC1–NC7 |
| **Sobreposição NC1⊂NC2⊂NC3** | intencional | — | Família com bebê marca 1 em NC1, NC2 e NC3; índice NC sobe por design |

### Decisão D10 — data de referência para idade

O CECAD municipal é um **snapshot estático** na ingestão; na prática a base pode chegar com **atraso de ~2 meses**. Usar só a data de extração do arquivo deixaria faixas etárias (NC1–NC3, NC5, NC6, NC7) **defasadas** em relação à realidade que a equipe de vigilância precisa enxergar.

| Modo | Data de referência | Uso |
|------|-------------------|-----|
| **Operacional (padrão VigSocial)** | `CURRENT_DATE` | Painéis, CRAS, bairro, agente, tomada de decisão |
| **Conciliação IVCAD / Observatório MDS** | `DT_EXTRACAO` do CECAD importado (metadado da ingestão / `LEIAME`) | Validar número contra Observatório na mesma competência |

**Regra:** idade dinâmica é **intencional** para vigilância; divergência em relação ao MDS deve constar na ficha do indicador, não ser tratada como bug.

Implementação futura sugerida:

- `idade_operacional` → `age(CURRENT_DATE, data_nascimento)` — coluna ou cálculo padrão em `mvw_pessoas` / mart IVCAD;  
- `idade_ivcad` → `age(dt_extracao_cecado, data_nascimento)` — modo auditoria e comparativo com IN078/VD00x.

O Observatório MDS publica IVCAD com idade na **competência mensal da extração**; o VigSocial prioriza **vigilância em tempo presente** quando a base está defasada.

### ❓ Ambiguidade menor (não bloqueia)

- **IN078 descrição NC7** resume só “metade ou menos mulheres adultas”; **VD007** traz a pré-condição de dependente — **priorizar VD007** na implementação.  
- Membros com **idade NULL**: MDS não detalha; definir política VigSocial (ex.: excluir do numerador/denominador ou tratar como não-adulto).

---

## 6. Cobertura VigSocial

| Requisito NC | Campo / expressão | Disponível |
|--------------|-------------------|------------|
| Idade (operacional) | `mvw_pessoas.idade` (`CURRENT_DATE`) | ✅ padrão D10 |
| Idade (conciliação MDS) | `age(dt_extracao_cecado, data_nascimento)` | 🔶 a materializar |
| Sexo | `mvw_pessoas.cod_sexo` ('1' M, '2' F) | ✅ |
| Deficiência | `cod_deficiencia`, `ind_def_*`, `tem_deficiencia_expr()` | ✅ |
| Agregação familiar | `codigo_familiar` | ✅ |
| Território CRAS | `mvw_familia.num_cras` | ✅ |
| Bairro | GEO / `bairro` | ✅ |

**Conclusão:** dimensão **NC implementável** com tronco atual; idade operacional via **D10**; filtro de universo IVCAD pendente.

---

## 8. Decisões registradas (NC)

| ID | Decisão |
|----|---------|
| D10 | Idade **dinâmica** (`CURRENT_DATE`) como padrão de vigilância; idade na **data de extração CECAD** só no modo conciliação Observatório MDS |

---

## 9. Progresso IVCAD

Todas as dimensões documentadas — ver [`ivcad/README.md`](./ivcad/README.md). **40 / 40** indicadores ✅

Próximo passo de implementação: `core.ivcad_familia`, validação vs Observatório.

---

*Documentação NC validada a partir de IN078, VD001–VD007 e print Observatório MDS.*
