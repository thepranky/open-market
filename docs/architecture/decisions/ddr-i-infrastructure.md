# DDR-I: Infrastructure and deployment

**Status:** draft | **Date:**

## Before you start

Read/trace:
- `docker-compose.yml`, `apps/api/Dockerfile`, `apps/web/Dockerfile`
- `apps/api/app/core/config.py` — all env vars
- `.env.example` if present
- `apps/api/main.py` lifespan, CORS, health endpoint

Sketch: what breaks if Postgres is down? if `GOOGLE_API_KEY` missing?

## Agent prompt

> Explain how to run CompMap locally and in Docker: services, ports, volumes, env vars. What depends on Postgres vs what works offline? Outline a minimal production deploy (API + web + managed Postgres). What's missing for auth, secrets, logging, and embed job scheduling? Compare deploy options (Vercel+Fly vs single VPS).

---

## What it does

## Why this way

## Alternatives considered

## Gaps

## Next steps
