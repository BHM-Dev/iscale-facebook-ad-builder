# Running with Docker

Run the full stack (PostgreSQL, backend API, frontend) with Docker Compose.

## Prerequisites

- Docker and Docker Compose v2
- A `.env` file (copy from `.env.example` and set your values)

## Quick start

```bash
# From project root
cp .env.example .env
# Edit .env with your API keys, SECRET_KEY, etc.

docker compose up --build
```

- **App:** http://localhost:5173  
- **API:** http://localhost:8000  
- **API docs:** http://localhost:8000/api/v1/docs  

PostgreSQL runs in a container on port **5434** (host). The backend runs migrations and `init_db.py` (roles + admin user if `ADMIN_EMAIL` / `ADMIN_PASSWORD` are set) on startup.

## Services

| Service   | Port  | Description                    |
|----------|-------|--------------------------------|
| frontend | 5173  | React app (nginx)              |
| backend  | 8000  | FastAPI + uvicorn              |
| postgres | 5434  | PostgreSQL 15 (host mapping)   |

## Environment

- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` — used by the Postgres container and to build `DATABASE_URL` for the backend.
- Backend gets `DATABASE_URL=postgresql://...@postgres:5432/...` automatically; other vars are read from `.env` via `env_file`.
- Frontend is built with `VITE_API_URL=/api/v1` so the browser hits the same origin; nginx in the frontend container proxies `/api` to the backend.

## Commands

```bash
# Build and start (detached)
docker compose up -d --build

# View logs
docker compose logs -f

# Stop
docker compose down

# Stop and remove volumes (resets DB)
docker compose down -v
```

## Building images only

```bash
# Backend (context: project root)
docker build -f backend/Dockerfile -t ad-builder-backend .

# Frontend (context: project root)
docker build -f frontend/Dockerfile -t ad-builder-frontend .
```
