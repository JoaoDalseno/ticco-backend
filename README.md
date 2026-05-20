# Ticco — Backend

> Plataforma de consultoria cafeicultora via WhatsApp + IA.  
> Agrônomos registram visitas técnicas por voz ou texto — o Ticco transcreve, estrutura, gera os documentos e entrega tudo automaticamente.

---

## Visão geral

O Ticco resolve um problema real na agronomia brasileira: o registro de visitas técnicas é feito à mão (caderno, PDF, planilha), demora horas e fica preso no celular do agrônomo. O dono da fazenda nunca sabe o que aconteceu.

**Com o Ticco, o fluxo vira:**

1. Agrônomo chega na lavoura, manda um áudio de 2 minutos pelo WhatsApp descrevendo o que viu
2. Sistema transcreve, identifica pragas/doenças/recomendações e monta o relatório
3. Agrônomo recebe o PDF do relatório e o receituário agronômico assinado — na mesma conversa
4. Dono da fazenda recebe um briefing semanal simples, em linguagem de leigo

---

## Arquitetura

```
┌─────────────────────────────────────────────────────────────┐
│                        WhatsApp (Z-API)                     │
└────────────────────────┬────────────────────────────────────┘
                         │ webhook
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                     FastAPI (Railway)                       │
│                                                             │
│  POST /webhooks/whatsapp                                    │
│       │                                                     │
│       ├─ Rate limit (5/min · 30/hora por número)           │
│       ├─ Security Token (HMAC compare_digest)               │
│       ├─ Número novo     → Onboarding (máquina de estados)  │
│       └─ Agrônomo known  → Background task                  │
│                │                                            │
│                ▼                                            │
│         process_message worker                              │
│           ├─ Comando de texto? → responde direto            │
│           ├─ Áudio? → valida URL (SSRF guard)               │
│           │          → download (byte cap 25 MB)            │
│           │          → Groq Whisper / OpenAI fallback        │
│           ├─ Claude claude-sonnet-4-5 extrai dados          │
│           ├─ Resolve fazenda/talhão (fuzzy match)           │
│           ├─ Persiste Visita no PostgreSQL (Supabase)       │
│           ├─ Gera PDFs (WeasyPrint)                         │
│           ├─ Upload Supabase Storage                        │
│           └─ Envia PDFs ao agrônomo via WhatsApp            │
│                                                             │
│  POST /webhooks/stripe  → 5 eventos de assinatura           │
│  POST /v1/checkout      → cria sessão Stripe Checkout       │
│  POST /v1/fazendas      → cadastra fazenda (JWT)            │
│  GET  /health           → status da API + banco             │
│  POST /admin/*          → dashboard interno (X-Admin-Key)   │
└────────────┬────────────────────────┬───────────────────────┘
             │                        │
             ▼                        ▼
    PostgreSQL (Supabase)    Supabase Storage
    pgvector habilitado      Bucket: ticco-files
```

---

## Funcionalidades

### Pipeline de visita técnica
- Aceita **áudio** (ogg, mp4, webm) e **texto longo**
- Transcrição via **Groq Whisper** com fallback automático para **OpenAI Whisper**
- Extração estruturada por **Claude claude-sonnet-4-5** com tool use: pragas, doenças, recomendações, observações
- Identificação de fazenda e talhão por fuzzy match
- Geração de **PDF de relatório** e **receituário agronômico** (quando há produtos recomendados)
- Upload automático no **Supabase Storage** e envio via WhatsApp

### Comandos de texto (zero custo de API)
Processados localmente, sem acionar Claude ou Whisper:

| Comando | Resposta |
|---|---|
| `ajuda` | Lista todos os comandos disponíveis |
| `histórico` | Últimas 5 visitas com resumo de pragas/recomendações |
| `fazendas` | Fazendas cadastradas com barra de progresso do limite do plano |
| `plano` | Plano atual, features e dias de trial restantes |
| `status` | Contagem de fazendas e visitas totais |
| `oi` / `olá` | Saudação personalizada |

### Onboarding via WhatsApp
Fluxo de cadastro por máquina de estados em memória:
`nome → CPF (com validação dos dígitos verificadores) → CREA → e-mail (opcional)`

### Módulo dono de fazenda
- Dono recebe **briefing semanal toda segunda às 8h (Brasília)** via WhatsApp
- Resumo gerado por **Claude Haiku** em linguagem simples, sem jargão técnico
- Disparado por cron no Railway (`0 11 * * 1` UTC)
- Endpoint `POST /admin/briefing/executar` para teste manual

### Assinaturas e pagamentos (Stripe)
- `POST /v1/checkout` — cria sessão Stripe Checkout (requer JWT)
- Webhook trata 5 eventos:
  - `customer.subscription.created` → ativa plano
  - `customer.subscription.deleted` → cancela
  - `invoice.payment_succeeded` → reativa conta inadimplente
  - `invoice.payment_failed` → marca como `past_due` + avisa agrônomo
  - `customer.subscription.trial_will_end` → avisa 3 dias antes

### Planos e limites

| Plano | Fazendas | Preço |
|---|---|---|
| `free` (trial) | 1 | Gratuito por 14 dias |
| `basico` | 10 | R$ 199/mês |
| `completo` | 20 | R$ 349/mês |

### Segurança
- JWT HS256 para autenticação dos endpoints REST
- `hmac.compare_digest` em todos os tokens fixos (Stripe, Z-API, Admin) — sem timing attacks
- Validação SSRF nas URLs de áudio antes do download
- Download de áudio com byte cap (25 MB) — streaming com abort
- Rate limiting por telefone: **5 msgs/min e 30 msgs/hora** (janela deslizante, thread-safe)
- Lock pessimista (`SELECT … FOR UPDATE`) ao criar fazendas — sem race condition
- `/docs` e `/redoc` ocultos em produção (`APP_ENV != development`)
- CPF validado com algoritmo dos dígitos verificadores

### Monitoramento operacional
O fundador recebe notificações via WhatsApp (`FOUNDER_PHONE`) em 4 eventos:
- **Erro no pipeline** — com nome do agrônomo, telefone e descrição do erro (truncada em 200 chars)
- **Novo cadastro** — nome, CREA, cidade e telefone
- **Novo pagamento** — cliente, plano e valor
- **Trial expirado** — nome, telefone e dias sem pagar *(disponível para uso em cron externo)*

---

## Stack tecnológica

| Categoria | Tecnologia |
|---|---|
| Runtime | Python 3.11 |
| Framework | FastAPI + Uvicorn |
| ORM | SQLAlchemy 2.0 async + asyncpg |
| Banco | PostgreSQL via Supabase (pgvector habilitado) |
| Migrações | Alembic |
| IA — estruturação | Anthropic Claude claude-sonnet-4-5 (tool use) |
| IA — transcrição | Groq Whisper (primário) · OpenAI Whisper (fallback) |
| IA — briefing | Anthropic Claude Haiku |
| PDFs | WeasyPrint |
| Storage | Supabase Storage |
| WhatsApp | Z-API |
| Pagamentos | Stripe |
| Auth | PyJWT (HS256) |
| Rate limiting | slowapi (por IP) + sliding window em memória (por telefone) |
| Deploy | Railway (API + cron como serviços separados) |
| Testes | pytest + pytest-asyncio |

---

## Estrutura do projeto

```
ticco-backend/
├── app/
│   ├── api/
│   │   ├── admin.py              # Dashboard interno — X-Admin-Key
│   │   ├── deps.py               # get_db, get_current_agronomo
│   │   ├── health.py             # GET /health
│   │   ├── v1/
│   │   │   ├── auth.py           # POST /v1/auth/issue-token
│   │   │   ├── checkout.py       # POST /v1/checkout (Stripe)
│   │   │   └── fazendas.py       # POST /v1/fazendas
│   │   └── webhooks/
│   │       ├── stripe.py         # POST /webhooks/stripe
│   │       └── whatsapp.py       # POST /webhooks/whatsapp
│   ├── core/
│   │   ├── ontologia/            # Ontologia cafeicultora (YAML)
│   │   ├── prompts/              # System prompts do Claude
│   │   ├── rate_limiter.py       # slowapi + sliding window por telefone
│   │   └── security.py           # JWT: criar_access_token / decodificar
│   ├── models/                   # SQLAlchemy ORM
│   │   ├── agronomo.py           # Agronomo, PlanoEnum, StatusPagamentoEnum
│   │   ├── fazenda.py            # Fazenda (modulo_dono_ativo)
│   │   ├── mensagem.py           # Mensagem (recebida/enviada)
│   │   ├── receituario.py        # Receituário agronômico
│   │   ├── talhao.py             # Talhão da fazenda
│   │   └── visita.py             # Visita técnica estruturada
│   ├── schemas/                  # Pydantic v2
│   ├── services/
│   │   ├── ai_processor.py       # Claude: extract_visita_data + gerar_resumo_whatsapp
│   │   ├── comando_handler.py    # Handlers dos comandos de texto (sem API)
│   │   ├── comando_parser.py     # Identificação de comandos (regex-free, sliding window)
│   │   ├── icp_brasil.py         # Número de série ICP-Brasil para receituário
│   │   ├── notificacao_fundador.py # Alertas WhatsApp pro fundador
│   │   ├── pdf_generator.py      # Relatório + receituário (WeasyPrint)
│   │   ├── plano.py              # Regras de limite por plano
│   │   ├── storage.py            # Supabase Storage (client cacheado com lru_cache)
│   │   ├── transcription.py      # Groq / OpenAI Whisper + validação SSRF
│   │   └── whatsapp/
│   │       ├── onboarding.py     # Máquina de estados: nome→CPF→CREA→email
│   │       └── zapi.py           # Cliente Z-API (send_text, send_document)
│   ├── utils/
│   │   └── logger.py             # setup_logger com formatação padronizada
│   ├── workers/
│   │   ├── briefing_semanal.py   # Cron de briefing semanal (dono de fazenda)
│   │   └── process_message.py    # Pipeline completo: mensagem → visita → PDFs
│   ├── config.py                 # Settings (pydantic-settings + .env)
│   ├── database.py               # AsyncEngine + AsyncSessionLocal
│   └── main.py                   # App FastAPI + middlewares + routers
├── alembic/
│   ├── env.py
│   └── versions/
│       └── 0001_initial_schema.py  # Schema completo + CREATE EXTENSION vector
├── scripts/
│   └── issue_token.py           # CLI: emite JWT por UUID ou telefone
├── tests/
│   ├── test_briefing_semanal.py
│   ├── test_checkout.py
│   ├── test_comando_parser.py
│   ├── test_notificacao_fundador.py
│   ├── test_onboarding.py
│   ├── test_rate_limiter.py
│   └── test_security.py
├── .env.example
├── Dockerfile
├── railway.toml                  # API + cron como [[services]]
└── requirements.txt
```

---

## Endpoints

### Infra

| Método | Rota | Auth | Descrição |
|---|---|---|---|
| `GET` | `/health` | — | Status da API e do banco (`database: connected / error`) |

### Webhooks

| Método | Rota | Auth | Descrição |
|---|---|---|---|
| `POST` | `/webhooks/whatsapp` | Client-Token (opcional) | Recebe mensagens do WhatsApp via Z-API |
| `POST` | `/webhooks/stripe` | Stripe-Signature (HMAC) | Recebe eventos de assinatura |

### API REST (v1)

| Método | Rota | Auth | Descrição |
|---|---|---|---|
| `POST` | `/v1/auth/issue-token` | X-Admin-Key | Emite JWT para um agrônomo (uso interno) |
| `POST` | `/v1/checkout` | Bearer JWT | Cria sessão Stripe Checkout para assinatura |
| `POST` | `/v1/fazendas` | Bearer JWT | Cadastra fazenda (respeitando limite do plano) |

### Admin (dashboard interno)

| Método | Rota | Auth | Descrição |
|---|---|---|---|
| `GET` | `/admin/overview` | X-Admin-Key | Métricas gerais: agrônomos, visitas, limites |
| `GET` | `/admin/agronomos` | X-Admin-Key | Lista agrônomos (paginado, máx 200) |
| `GET` | `/admin/visitas` | X-Admin-Key | Lista visitas (paginado, máx 200) |
| `PATCH` | `/admin/agronomos/{id}/status` | X-Admin-Key | Altera status de pagamento manualmente |
| `POST` | `/admin/briefing/executar` | X-Admin-Key | Dispara briefing semanal manualmente |

---

## Variáveis de ambiente

Copie `.env.example` para `.env` e preencha:

```bash
cp .env.example .env
```

| Variável | Obrigatória | Descrição |
|---|---|---|
| `DATABASE_URL` | ✅ | `postgresql+asyncpg://user:pass@host:6543/db` (Supabase Transaction Pooler) |
| `SUPABASE_URL` | ✅ | `https://[ref].supabase.co` |
| `SUPABASE_SERVICE_ROLE_KEY` | ✅ | Chave service role (não a anon key) |
| `SUPABASE_BUCKET` | ✅ | Nome do bucket — padrão `ticco-files` |
| `ANTHROPIC_API_KEY` | ✅ | Chave Anthropic (Claude) |
| `GROQ_API_KEY` | ✅ | Chave Groq (Whisper primário) |
| `OPENAI_API_KEY` | ✅ | Chave OpenAI (Whisper fallback) |
| `ZAPI_INSTANCE_ID` | ✅ | ID da instância Z-API |
| `ZAPI_TOKEN` | ✅ | Token Z-API |
| `ZAPI_SECURITY_TOKEN` | — | Security token do webhook Z-API (recomendado) |
| `STRIPE_SECRET_KEY` | ✅ | Chave secreta Stripe (`sk_live_...`) |
| `STRIPE_WEBHOOK_SECRET` | ✅ prod | Secret do webhook Stripe (`whsec_...`) |
| `STRIPE_PRICE_BASICO` | ✅ | Price ID do plano básico (`price_...`) |
| `STRIPE_PRICE_COMPLETO` | ✅ | Price ID do plano completo (`price_...`) |
| `JWT_SECRET` | ✅ | String aleatória ≥ 32 chars — `python -c "import secrets; print(secrets.token_hex(32))"` |
| `JWT_ALGORITHM` | — | Padrão: `HS256` |
| `JWT_EXPIRE_MINUTES` | — | Padrão: `10080` (7 dias) |
| `ADMIN_SECRET_KEY` | ✅ prod | Chave do dashboard admin — `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `FOUNDER_PHONE` | — | Telefone E.164 do fundador para notificações (`+5516...`) |
| `FRONTEND_URL` | — | URL do frontend para redirects do Stripe (padrão: `http://localhost:3000`) |
| `APP_ENV` | — | `development` ou `production`. Em produção oculta /docs e exige STRIPE_WEBHOOK_SECRET |
| `APP_BASE_URL` | — | URL pública da API |
| `LOG_LEVEL` | — | `INFO` (padrão), `DEBUG`, `WARNING` |

---

## Desenvolvimento local

### Pré-requisitos

- Python 3.11+
- PostgreSQL acessível (ou conta Supabase)
- Variáveis de ambiente configuradas no `.env`

### Instalação

```bash
# Clone
git clone https://github.com/JoaoDalseno/ticco-backend.git
cd ticco-backend

# Ambiente virtual
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Dependências
pip install -r requirements.txt

# Copiar e preencher .env
cp .env.example .env
```

### Banco de dados

```bash
# Habilita pgvector e cria todas as tabelas
alembic upgrade head
```

A migration `0001_initial_schema.py` roda `CREATE EXTENSION IF NOT EXISTS vector` automaticamente — é idempotente no Supabase.

### Iniciar o servidor

```bash
uvicorn app.main:app --reload
```

- API: `http://localhost:8000`
- Swagger (somente em `APP_ENV=development`): `http://localhost:8000/docs`

### Emitir JWT para testes

```bash
# Listar agrônomos cadastrados
python scripts/issue_token.py --listar

# Por UUID
python scripts/issue_token.py <uuid>

# Por telefone
python scripts/issue_token.py --telefone +5516999990001
```

---

## Testes

```bash
# Rodar todos os testes
pytest

# Com verbosidade
pytest -v

# Módulo específico
pytest tests/test_comando_parser.py -v
```

**68 testes** cobrindo:

| Módulo | Testes |
|---|---|
| `test_comando_parser.py` | Identificação de comandos (ajuda, histórico, fazendas, etc.) |
| `test_security.py` | JWT: emissão, validação, expiração, assinatura inválida |
| `test_onboarding.py` | Máquina de estados, validação CPF (dígitos verificadores), CREA |
| `test_rate_limiter.py` | Sliding window por telefone (limite minuto/hora, expiração) |
| `test_notificacao_fundador.py` | 4 tipos de alerta, FOUNDER_PHONE vazio, falha silenciosa |
| `test_briefing_semanal.py` | Worker de briefing (sem visitas, com visitas, isolamento de erros) |
| `test_checkout.py` | Checkout Stripe, price IDs, payment_succeeded, 5 eventos registrados |

> **Nota:** testes que dependem de Groq, Anthropic ou do banco completo (ex: `test_health.py`) requerem as dependências instaladas e variáveis configuradas. Os módulos listados acima rodam sem conexão externa (todos os I/Os são mockados).

---

## Docker

```bash
# Build
docker build -t ticco-backend .

# Run
docker run --env-file .env -p 8000:8000 ticco-backend
```

A imagem base (`python:3.11-slim`) inclui as dependências do sistema necessárias para o WeasyPrint (Pango, Cairo, etc.).

---

## Deploy no Railway

### 1. Configurar serviços

O `railway.toml` define **dois serviços** no mesmo repositório:

```toml
[[services]]
name = "api"
startCommand = "uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 2"

[[services]]
name = "briefing-cron"
cronSchedule = "0 11 * * 1"   # Segunda 8h Brasília = 11h UTC
startCommand = "python -m app.workers.briefing_semanal"
```

### 2. Variáveis de ambiente no Railway

Configure todas as variáveis da seção anterior em **Railway → Variables**. As críticas em produção:

```
APP_ENV=production
DATABASE_URL=postgresql+asyncpg://postgres:SENHA@db.REF.supabase.co:6543/postgres
JWT_SECRET=<gerado com secrets.token_hex(32)>
ADMIN_SECRET_KEY=<gerado com secrets.token_urlsafe(32)>
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_BASICO=price_...
STRIPE_PRICE_COMPLETO=price_...
FOUNDER_PHONE=+5516...
FRONTEND_URL=https://ticco.com.br
```

### 3. Banco — rodar migrations

```bash
# Via Railway CLI
railway run alembic upgrade head

# Ou configurar como Release Command no Railway
```

### 4. Supabase Storage

Criar o bucket `ticco-files` como **público**:
`Supabase Dashboard → Storage → New bucket → ticco-files → Public: SIM`

### 5. Z-API — configurar webhook

No painel Z-API, apontar o webhook para:
```
https://SEU-APP.railway.app/webhooks/whatsapp
```
Header: `Client-Token: <ZAPI_SECURITY_TOKEN>`

### 6. Stripe — configurar webhook

No Stripe Dashboard → Developers → Webhooks → Add endpoint:

```
URL: https://SEU-APP.railway.app/webhooks/stripe
```

Eventos a selecionar:
- `customer.subscription.created`
- `customer.subscription.deleted`
- `invoice.payment_succeeded`
- `invoice.payment_failed`
- `customer.subscription.trial_will_end`

Copiar o **Signing secret** (`whsec_...`) para `STRIPE_WEBHOOK_SECRET`.

### 7. Verificar deploy

```bash
curl https://SEU-APP.railway.app/health
# Esperado: {"status": "ok", "database": "connected", "env": "production"}
```

---

## Fluxo de pagamento

```
Frontend
  └─ POST /v1/checkout {"plano": "basico"}   (Bearer JWT)
        │
        ├─ Cria/reutiliza Stripe Customer
        ├─ Cria Checkout Session (mode: subscription)
        └─ Retorna {"checkout_url": "https://checkout.stripe.com/..."}

Usuário paga no Stripe
  └─ Stripe → POST /webhooks/stripe
        └─ customer.subscription.created
              ├─ Ativa agronomo.status_pagamento = active
              ├─ Envia WhatsApp "Pagamento confirmado 🎉"
              └─ Notifica fundador via WhatsApp
```

---

## Segurança

| Proteção | Implementação |
|---|---|
| Timing attacks em tokens | `hmac.compare_digest` em todos os headers fixos |
| SSRF em URLs de áudio | Validação de host/scheme antes do download |
| Flood de mensagens | Rate limit por telefone: 5/min · 30/hora (sliding window thread-safe) |
| Race condition em fazendas | `SELECT … FOR UPDATE` no agrônomo antes do INSERT |
| Download ilimitado | Streaming com byte cap de 25 MB — abort imediato se exceder |
| Exposição de PII nos logs | Mascaramento do telefone: `+55****0001` |
| Fail-closed no Stripe | Sem `STRIPE_WEBHOOK_SECRET` em produção → rejeita silenciosamente |
| Documentação em produção | `/docs` e `/redoc` desabilitados (`APP_ENV=production`) |

---

## Licença

Proprietário — © 2025 Ticco. Todos os direitos reservados.
