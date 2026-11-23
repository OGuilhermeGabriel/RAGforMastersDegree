# Sistema Distribuído de Consulta a Documentos via RAG na AWS

Projeto Final da disciplina de **Sistemas Distribuídos (UFERSA)**.

Aplicação web distribuída em **três camadas** que permite a usuários autenticados fazer upload de documentos PDF (com texto selecionável) para seu acervo privado e realizar consultas em linguagem natural com respostas fundamentadas (*grounding*) via **Lean RAG** (*Retrieval-Augmented Generation*).

- **Frontend:** `https://guilhermegabriel.grupo-05.sd.ufersa.dev.br`
- **API RESTful:** `https://api.guilhermegabriel.grupo-05.sd.ufersa.dev.br`

---

## Arquitetura em Três Camadas

| Camada | Tecnologias | Serviços AWS Academy |
| --- | --- | --- |
| **1. Apresentação (Frontend)** | HTML5, CSS3, JavaScript Vanilla | Servido via Nginx na EC2 com HTTPS (Certbot) |
| **2. Negócios (Backend / API)** | Python 3.11, Django REST Framework, Gunicorn, `pypdf`, `boto3`, `google-genai`, `bcrypt`, `PyJWT`, Docker | Amazon EC2 (`t3.small`) + Elastic IP + Route 53 |
| **3. Dados (Persistência)** | PostgreSQL 15+ com `pgvector` (`vector(768)`) | Amazon RDS (`db.t3.micro`) + Amazon S3 (bucket privado) |

### Pipeline *Lean RAG*
1. **Ingestão:** upload do PDF → persistência no S3 privado (ou disco local em dev) → extração de texto com `pypdf` → *chunking* (~1.000 caracteres, *overlap* de 150) → *embeddings* de 768 dimensões (`gemini-embedding-001`) → gravação no PostgreSQL + `pgvector`.
2. **Consulta:** *embedding* da pergunta → busca vetorial por distância de cosseno (`<=>`) filtrada por `document_id` e `user_id` (`top-k = 3`) → geração fundamentada com fallback automático contra indisponibilidade transitória → persistência no histórico (`queries`).

---

## Endpoints RESTful (`/api/v1`)

| Endpoint | Método | Acesso | Descrição |
| --- | --- | --- | --- |
| `/api/v1/health` | `GET` | Público | Verifica conectividade com PostgreSQL e extensão `pgvector` (`200`). |
| `/api/v1/users` | `POST` | Público | Cadastro de usuário com senha protegida por hash `bcrypt` (`201`). |
| `/api/v1/auth/login` | `POST` | Público | Autenticação e emissão de token JWT `HS256` (`200`). |
| `/api/v1/documents` | `POST` | Privado | Upload de PDF, indexação vetorial e persistência (`201`). |
| `/api/v1/documents` | `GET` | Privado | Lista documentos do usuário autenticado (`200`). |
| `/api/v1/documents/{id}` | `GET` | Privado | Metadados de um documento do usuário (`200`, `403` para terceiros). |
| `/api/v1/documents/{id}` | `DELETE` | Privado | Remove PDF do armazenamento e exclui documento/vetores/histórico (`204`). |
| `/api/v1/documents/{id}/queries` | `POST` | Privado | Busca semântica (`top-k = 3`) + resposta fundamentada do LLM (`200`). |
| `/api/v1/documents/{id}/queries` | `GET` | Privado | Histórico de perguntas e respostas do documento (`200`). |

---

## Execução Local (Docker Compose)

1. Copie `.env.example` para `.env` e informe sua `GEMINI_API_KEY`:
   ```bash
   cp .env.example .env
   ```
2. Suba PostgreSQL (`pgvector`), API Django REST e Frontend (Nginx):
   ```bash
   docker compose up -d --build
   docker compose exec api python manage.py migrate
   ```
3. Acesse:
   - **Frontend:** `http://localhost:8080`
   - **API Healthcheck:** `http://localhost:8000/api/v1/health`

---

## Deploy na AWS EC2 (Resumo)

Consulte os arquivos de produção prontos no repositório:
- `docker-compose.prod.yml` (API em `127.0.0.1:8000` com `restart: always`)
- `deploy/env.prod.example` (template do `.env` para RDS + S3 + CORS em produção)
- `deploy/nginx/rag-ufersa.conf` (Nginx para frontend estático + proxy reverso da API, pronto para Certbot)
