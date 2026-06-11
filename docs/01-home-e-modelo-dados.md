# VigSocial — Home e modelo de dados (discussão inicial)

> **Status:** rascunho de arquitetura · **Referência:** Observatório MDS (painel IVCAD)  
> **Decisão D1:** tronco dorsal = **Cadastro Único (CADU/CECAD)**  
> **Objetivo:** organizar dados e indicadores no mesmo espírito do Observatório, enriquecido com fontes que o MDS não cruza no painel municipal.

---

## 1. O que o Observatório faz bem (Home IVCAD)

A home do Observatório MDS combina quatro ideias que devemos replicar:

| Bloco | Função | Exemplo (nacional) |
|-------|--------|---------------------|
| **KPIs de universo** | Tamanho da base | Famílias, Pessoas |
| **KPIs de satélite** | Benefício / programa | Famílias com PBF, Pessoas com PBF |
| **Indicador sintético** | Índice ou score com metodologia explícita | IVCAD 0,283 + texto da fórmula/universo |
| **Distribuições** | Retratos transversais (barras) | Meses desde atualização; faixa de renda per capita |

Além disso, a **navegação por abas** define painéis temáticos sobre o **mesmo tronco CADU**:

- Identificação e controle  
- Características dos domicílios  
- Família e GPTEs  
- Pop Rua  
- Benefícios sociais  
- Características das pessoas  
- Pessoas com deficiência  
- Escolaridade  
- Trabalho  
- Mapa / Tabela  

**Princípio:** uma fonte verdade (CADU) + dimensões de corte + indicadores documentados (valor, fonte, cruzamento, grain).

---

## 2. Nossa primeira decisão — tronco e satélites

```
                    ┌─────────────────────────────────────┐
                    │     CADU (CECAD) — TRONCO           │
                    │  vig.mvw_familia                    │
                    │  vig.mvw_pessoas                    │
                    │  vig.mvw_familia_domicilio          │
                    └──────────────┬──────────────────────┘
                                   │
         chave: codigo_familiar ───┼─── chave: num_nis / nis_norm
                                   │
     ┌─────────────┬───────────────┼───────────────┬─────────────┐
     ▼             ▼               ▼               ▼             ▼
 Folha PBF     Folha BPC      Manutenções      SISC         GEO/bairro
 (SIBEC)       (SIBEC)        SIBEC            qualificado   tbl_geo
 raw.sibec__   raw.sibec__    raw.sibec__      vig.mvw_      → bairro
 programa_     bpc…           manutencoes      sisc_         territorial
 bolsa_…                                        qualificado
```

| Satélite | Grain principal | Chave de ligação | Competência / tempo |
|----------|-----------------|------------------|---------------------|
| Folha PBF | família (folha) | `codigo_familiar` normalizado | `competencia` AAAAMM |
| Folha BPC | beneficiário / família | NIS / código familiar | `competencia` |
| Manutenções SIBEC | evento × família | `codigo_familiar` | `competencia` + tipo ação |
| SISC | pessoa (NIS) matriculada | `nis_norm` → CADU; `codigo_familiar` | snapshot ingestão |
| Território | família | `codigo_familiar` + CEP → GEO | referência CRAS no CADU |

**Regra:** painéis, agente e exportações usam **as mesmas visões e o mesmo catálogo de métricas**.

---

## 3. Home VigSocial — layout alvo (caminho Observatório + enriquecimentos)

### 3.1 Faixa superior — universo (como Observatório)

| Card | Indicador | Fonte | Grain | Status VigSocial |
|------|-----------|-------|-------|------------------|
| 1 | Total de **famílias** | `vig.mvw_familia` | família | ✅ Início |
| 2 | Total de **pessoas** | `vig.mvw_pessoas` | pessoa | ✅ Início |
| 3 | Famílias na **folha PBF** | `raw.sibec__programa_bolsa_familia` (última competência) | família | ✅ Início |
| 4 | Pessoas com **PBF** (opcional Observatório) | cruzamento folha × pessoas CADU ou marcador | pessoa | 🔶 parcial (`marc_pbf`) |

### 3.2 Bloco central — indicador sintético municipal

| Item | Observatório | VigSocial (proposta) |
|------|--------------|----------------------|
| Score | **IVCAD** (6 dimensões, 40 indicadores, universo PBF ou renda ≤ ½ SM + atualizado 24m) | **Fase 2:** replicar IVCAD municipal se dados permitirem; **Fase 1:** proxy municipal (TAC, % atualizados 24m, renda extrema pobreza) |
| Visual | Velocímetro + média nacional | Gauge ou card comparativo (município vs UF / Brasil quando houver referência) |
| Metodologia | Texto fixo ao lado | Painel `<details>` ou link “Como calculamos” (fonte + SQL + filtros) |

> **Nota:** IVCAD exige implementação metodológica MDS v1.0.5. Documentar universo e indicadores antes de prometer o número oficial.

### 3.3 Coluna direita — distribuições (barras, filtros CRAS/bairro)

Espelhar Observatório com recortes **interativos** (dimensões conformadas):

| Gráfico | Eixo / categorias | Fonte | Status |
|---------|-------------------|-------|--------|
| Famílias por **meses desde atualização** | Até 12 / 12–18 / 18–24 / 24–36 / 37–48 / 48+ | `vig.mvw_familia.meses_desatualizado` | 🔶 calcular faixas |
| Famílias por **faixa renda per capita** | Pobreza / baixa renda / acima ½ SM (ou faixas VigSocial 218/706) | `vig.mvw_familia.faixa_renda` ou `renda_per_capita` | ✅ parcial Início |
| *(extensão)* Atendidos **SISC** por faixa etária | 0–11 / 12–17 / 18+ | `vig.mvw_sisc_qualificado` | ✅ Convivência |
| *(extensão)* **Manutenções** no mês por ação | Cancelar / Bloquear / Suspender… | `raw.sibec__manutencoes` | ✅ Início |

**Filtros globais da home (não no Observatório nacional):**

- CRAS (territorial CADU: `f.num_cras`)  
- CREAS (quando cadastrado na rede)  
- Bairro (GEO → `tbl_geo`, fallback bairro CADU)  

---

## 4. Navegação temática (abas → painéis VigSocial)

| Aba Observatório MDS | Painel VigSocial | Tronco | Satélites |
|----------------------|------------------|--------|-----------|
| IVCAD | **Início** (home cockpit) | CADU | PBF, TAC, renda |
| Identificação e controle | Vigilância / futuro | CADU | atualização, situação cadastral |
| Características dos domicílios | Caracterização (domicílio) | `mvw_familia_domicilio` | — |
| Família e GPTEs | Caracterização / Início | CADU | GPTE flags |
| Pop Rua | Painel temático (futuro) | `marc_sit_rua` | — |
| Benefícios sociais | **Início** + futuro BPC/PBF detalhe | CADU | SIBEC folha + **manutenções** |
| Características das pessoas | **Caracterização** | `mvw_pessoas` | — |
| Pessoas com deficiência | Caracterização | `mvw_pessoas` | — |
| Escolaridade / Trabalho | Caracterização | `mvw_pessoas` | — |
| Mapa / Tabela | GEO + export (futuro) | CADU + bairro | — |
| *(não existe no MDS)* | **Convivência (SISC)** | CADU × NIS | `mvw_sisc_qualificado` |
| *(não existe no MDS)* | **CRAS territorial** | CADU família | SISC CRAS matrícula |

---

## 5. Ficha de indicador (padrão Observatório / IVCAD)

Todo KPI exposto na UI ou no agente deve ter ficha:

```yaml
id: familias_folha_pbf
titulo: Famílias na folha do Programa Bolsa Família
valor: <calculado>
grain: familia
universo: município (IBGE configurado)
fontes:
  - raw.sibec__programa_bolsa_familia
competencia: "202505"  # última importada
cruzamentos:
  - normalização codigo_familiar (zeros à esquerda, somente dígitos)
  - DISTINCT codigo_familiar na competência
nao_confundir_com:
  - marc_pbf_cadu (marcador no CADU)
  - marc_pbf (presença na folha entre famílias do CADU local)
sql_ou_regra: "<referência código ou view>"
painel: Início
agente: canonical_metrics / catálogo
filtros_suportados: [cras, bairro]
```

Este formato evita divergência painel × chat e permite documentação pública estilo Observatório.

---

## 6. O que já temos vs o que falta

### Implementado (base sólida)

- Tronco CADU materializado (`mvw_familia`, `mvw_pessoas`, `mvw_familia_domicilio`)
- Home com famílias, pessoas, sexo, PBF folha, TAC, renda, BPC, **manutenções SIBEC**
- Painéis Caracterização, CRAS, Convivência (SISC)
- Ingestão CADU, PBF, BPC, SIBEC manutenções, SISC, GEO
- Agente com métricas canônicas (em expansão)

### Próximos passos de dados (prioridade)

1. **Catálogo de indicadores** (YAML/JSON) — fonte única painel + agente  
2. **Faixas de desatualização** alinhadas ao Observatório (meses desde atualização)  
3. **Dimensões conformadas** `dim_cras`, `dim_bairro`, `dim_competencia`  
4. **IVCAD municipal** — estudo de viabilidade (indicadores + universo MDS)  
5. **CREAS** na rede de serviços e como dimensão de filtro  
6. **Metodologia visível** na UI (tooltip / “Como calculamos” em cada card)

### Próximos passos de produto (home)

1. Reorganizar **Início** no layout Observatório: 4 KPIs + 2 barras + bloco sintético  
2. Barra de **filtros** persistente (CRAS / bairro / competência SIBEC)  
3. Abas ou menu espelhando temas MDS + Convivência + CRAS  

---

## 7. Perguntas abertas (para próxima rodada de discussão)

1. **IVCAD:** replicar oficialmente (v1.0.5) ou usar proxies municipais na Fase 1?  
2. **Pessoas com PBF:** contar por NIS na folha ou por família com integrante beneficiário?  
3. **Faixas de renda:** manter cortes VigSocial (218/706) ou alinhar aos rótulos Observatório (pobreza / baixa renda / acima ½ SM)?  
4. **Competência padrão:** home sempre na última folha/manutenção importada — confirmar?  
5. **Referência externa:** exibir comparação com média UF/Brasil (requer dados externos ou API MDS)?  

---

## 8. Histórico de decisões

| ID | Decisão | Data |
|----|---------|------|
| D1 | Tronco dorsal = Cadastro Único | discussão inicial |
| D2 | Satélites: SIBEC (folha + manutenções), SISC, GEO; ligação por chaves documentadas | discussão inicial |
| D3 | Indicadores seguem ficha Observatório (valor + fonte + cruzamento + grain) | discussão inicial |
| D4 | Home organizada no **caminho Observatório**, enriquecida com SISC e manutenções | discussão inicial |
| D5 | **IVCAD** = primeiro processo grande; grain família; agregação **município + CRAS + bairro** | discussão IVCAD |
| D6 | Metodologia MDS **v1.0.5** fiel antes de índices alternativos | discussão IVCAD |
| D7 | Universo IVCAD (PBF ou 24m + ½ SM) aplicado antes dos 40 indicadores | discussão IVCAD |

Ver detalhamento: [`02-ivcad-processo.md`](./02-ivcad-processo.md)

---

*Documento vivo — atualizar conforme novos painéis MDS forem trazidos à discussão.*
