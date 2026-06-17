# VigSocial - Arquitetura Inicial

Aplicacao web para Vigilancia Socioassistencial com frontend e backend separados.

## Stack inicial

- Frontend: React + Vite
- Backend: FastAPI
- Banco de dados: PostgreSQL
- Fila/cache: Redis
- Orquestracao local: Docker Compose

## Perfis de acesso (RBAC)

- `superadmin`
- `gestor`
- `admin_local`
- `tecnico`
- `consultivo`

## Bootstrap do SuperAdmin

No primeiro deploy, defina no EasyPanel:

- `BOOTSTRAP_SUPERADMIN_EMAIL`
- `BOOTSTRAP_SUPERADMIN_PASSWORD`
- `BOOTSTRAP_SUPERADMIN_NAME`
- `BOOTSTRAP_SUPERADMIN_SYNC_PASSWORD` (opcional, `true` para **atualizar** a senha se o usuario ja existir)

Ao iniciar a API, se esse email ainda nao existir no banco, o usuario `superadmin` e criado automaticamente.

**Login falha?** Abra `GET /api/v1/auth/bootstrap-status` na URL da API. Se o usuario ja existia com outra senha, defina `BOOTSTRAP_SUPERADMIN_SYNC_PASSWORD=true`, reinicie a API, faca login e volte para `false`.

## Estrutura do projeto

- `apps/api`: codigo da API FastAPI
- `apps/web`: codigo do frontend React + Vite
- `backend/Dockerfile`: imagem de producao da API (contexto = raiz do repo)
- `frontend/Dockerfile`: imagem de producao do frontend (build estatico + nginx)
- `DadosBrutos`: fontes iniciais de dados para ingestao

## Git — repositorio canonico

O remote **`origin`** (`github.com/ftsmazzo/vigilanciasuas`) esta **descontinuado**. Nao faca push nele.

| Remote | URL | Uso |
|--------|-----|-----|
| **`vigilancia`** | `https://github.com/ftsmazzo/vigilancia.git` | **Producao e desenvolvimento ativos** — unico destino de push |
| `origin-descontinuado` | `https://github.com/ftsmazzo/vigilanciasuas.git` | Legado; mantido apenas como referencia local |

Clone novo ou configuracao local:

```bash
git remote add vigilancia https://github.com/ftsmazzo/vigilancia.git
git fetch vigilancia
git branch --set-upstream-to=vigilancia/main main
```

Push padrao:

```bash
git push vigilancia main
```

## EasyPanel (deploy)

Configure **Build Path** como `/` (raiz) e aponte o Dockerfile de cada servico:

| Servico  | Arquivo Dockerfile   |
|----------|----------------------|
| Backend  | `backend/Dockerfile` |
| Frontend | `frontend/Dockerfile` |

### Backend — variaveis de ambiente (runtime)

| Variavel | Obrigatoria | Descricao |
|----------|-------------|-----------|
| `DATABASE_URL` | Sim | URL do PostgreSQL. Aceita `postgresql+psycopg://...` **ou** `postgresql://...` (a API normaliza automaticamente para psycopg v3). |
| `JWT_SECRET_KEY` | Sim | Chave secreta forte (nao reutilize a senha do banco). |
| `CORS_ORIGINS` | Recomendado | URLs do frontend, separadas por virgula. Ex.: `https://app.seudominio.gov.br`. Em dev local o padrao ja cobre `localhost:3000`. |
| `JWT_ALGORITHM` | Nao | Padrao: `HS256` |
| `JWT_EXPIRE_MINUTES` | Nao | Padrao: `60` |
| `REDIS_URL` | Nao por enquanto | Ex.: `redis://host-interno:6379/0` (reservado para filas de ingestao). |
| `ASSIST_LLM_API_KEY` | Assistente IA | Chave xAI/Grok ou OpenAI-compatível. Sem ela, `/assistente` retorna 503. |
| `ASSIST_LLM_BASE_URL` | Nao | Padrao: `https://api.x.ai/v1` (OpenAI, Ollama, etc.). |
| `ASSIST_LLM_MODEL` | Nao | Padrao: `grok-4-1-fast-reasoning`. |
| `ASSIST_ORCH_MODEL` | Nao | Modelo do Orquestrador VigIA (padrao = ASSIST_LLM_MODEL). |
| `ASSIST_SQL_MODEL` | Nao | Modelo do AgenteSQL (padrao = ASSIST_LLM_MODEL). |
| `KB_API_URL` | RAG SUAS | URL POST da base de conhecimento (ex.: `https://.../api/kb/5/query`). |
| `KB_API_KEY` | RAG SUAS | Bearer token da API de KB. |
| `KB_TOP_K` | Nao | Trechos RAG por consulta; padrao: 3. |
| `BOOTSTRAP_SUPERADMIN_EMAIL` | Primeiro deploy | Email do primeiro SuperAdmin. |
| `BOOTSTRAP_SUPERADMIN_PASSWORD` | Primeiro deploy | Senha inicial (troque apos o primeiro login se desejar). |
| `BOOTSTRAP_SUPERADMIN_NAME` | Nao | Nome exibido; padrao: `Super Admin`. |
| `BOOTSTRAP_SUPERADMIN_SYNC_PASSWORD` | Nao | `true` atualiza senha do e-mail de bootstrap no restart (use uma vez apos mudar senha no painel). |

**Dica:** no EasyPanel, use o hostname **interno** do servico PostgreSQL que o painel fornece (nao `localhost` dentro do container da API).

### Frontend — build args

O Vite embute `VITE_API_URL` no build. Defina como **build argument** no servico do frontend:

| Build arg | Exemplo | Descricao |
|-----------|---------|-----------|
| `VITE_API_URL` | `https://api.seudominio.gov.br` | URL **publica** onde a API estara acessivel (sem barra no final). |

### MinIO e N8N

Nao sao obrigatorios nesta fase. Quando houver upload de arquivos para RAW, o MinIO podera guardar os originais e o N8N pode orquestrar fluxos externos, se fizer sentido para voces.

## Rodando local com Docker

1. Copie `.env.example` para `.env`
2. Execute:
   - `docker compose up --build`
3. URLs:
   - Frontend: `http://localhost:3000`
   - Ingestão RAW: `http://localhost:3000/ingestao` (após login)
   - API: `http://localhost:8000`
   - Docs API: `http://localhost:8000/docs`

## Endpoints iniciais

- `GET /health`
- `POST /api/v1/auth/login`
- `GET /api/v1/users/me`
- `GET /api/v1/users` (apenas `superadmin`)
- `POST /api/v1/users` (apenas `superadmin`)
- `POST /api/v1/ingestion/import` (autenticado, cria/popula tabela `raw` com estratégia `replace|append`; aceita `competencia=AAAAMM` e controle de sobrescrita mensal)
- `GET /api/v1/ingestion/runs` (histórico das últimas ingestões, exibido na página `/ingestao`)

## Proximos passos

- Implementar migracoes versionadas (Alembic)
- Criar modulo de upload CSV/XLSX e jobs assicronos
- Criar tabelas RAW e mapeamento inicial de `DadosBrutos/CECAD/tudo.csv`
- Definir views analiticas e cruzamentos da dashboard
