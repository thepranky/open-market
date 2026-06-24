# ROADMAP

Phased plan from current state to production. Each row is one spec-sized change.
See [`.cursor/rules/meridian.mdc`](.cursor/rules/meridian.mdc) for spec-driven workflow.

| Phase | Step | What | Files / areas | Why | How |
|-------|------|------|---------------|-----|-----|
| **0 Docs** | 0.1 | Doc consolidation | `docs/`, `README.md`, `CLAUDE.md` | Single source of truth for onboarding | Done |
| | 0.2 | Layout spec + DDR-0 | `docs/specs/restructure-layout.md`, `ddr-0-repo-layout.md` | Clear boundaries before deep-dives | Done |
| **1 Restructure** | 1.1 | API packages (`cases/`, `screening/`, `shared/`) | `apps/api/app/` | Learnable module boundaries | Done (PR 1) |
| | 1.2 | Script subdirs | `apps/api/scripts/` | Pipeline discoverability | Done (PR 2) |
| | 1.3 | Web feature folders | `apps/web/src/features/` | Frontend boundaries | PR 3 |
| **2 Understand** | 2.1–2.9 | DDR deep-dives (0, A–I) | `docs/architecture/decisions/` | Defensible understanding | 1 day each; after restructure |
| **3 CI** | 3.1 | Add schema validation to PR CI | `.github/workflows/api-ci.yml` | Canonical YAML breaks silently today | Run `test_schema.py` + `validate_cases.py` on PR |
| | 3.2 | Jurisdiction push tier on PR | `api-ci.yml` | Screening regressions not gated on merge | `run_jurisdiction_verification.py --tier push` |
| | 3.3 | Web lint + build in CI | new `web-ci.yml` | Frontend breaks undetected | `npm run lint && npm run build` |
| | 3.4 | Ruff in CI | `api-ci.yml` | Style/errors only caught locally | `ruff check .` step |
| | 3.5 | Benchmark artifacts | `api-ci.yml` | Eval trends discarded | Upload benchmark JSON as artifact |
| **4 Refine** | 4.1 | Split `jurisdictions.py` router | `app/screening/routers/` | God-router | Spec: screening vs chat vs CRUD |
| | 4.2 | `data_jurisdictions_path` config | `app/shared/core/config.py` | Path derived from cases path | Explicit env var |
| | 4.3 | Rename overloaded symbols | `Juris.tsx`, home stats | Naming collision | `CaseRegulatorBadge`, `case_regulator_count` |
| | 4.4 | Neo4j deprecation decision | `graph/`, `neo4j_client.py` | Legacy noise | DDR-C then spec |
| **5 Product** | 5.1 | Unify branding | `README`, web nav, API title | CompMap vs Meridian | **Meridian** — align web + API title |
| | 5.2 | Document indexed vs canonical | `docs/architecture/case-research.md` | Two case layers confuse users | UX copy + maybe merge long-term |
| | 5.3 | Eval metrics in UI (admin) | new `/admin` or debug panel | Reliability story hidden | Read-only view of benchmark output |
| | 5.4 | Threshold engine unit tests | `tests/test_threshold_engine.py` | Only gold-deal regression today | Direct tests per test type |
| | 5.5 | Embedding search eval | `data/evals/`, scripts | No quality gate on semantic search | Small gold query set + recall@k |
| **6 Deploy** | 6.1 | Production Docker / compose prod | `docker-compose.prod.yml`, Dockerfiles | Dev compose not production-ready | Multi-stage builds, non-root, healthchecks |
| | 6.2 | Managed Postgres + pgvector | env docs, migrations | Local-only DB today | Neon/Supabase/RDS; connection pooling |
| | 6.3 | API deploy (Fly/Railway/ECS) | `apps/api/`, CI | No hosted API | Container deploy + `DATABASE_URL` secrets |
| | 6.4 | Web deploy (Vercel) | `apps/web/`, env | No hosted frontend | `NEXT_PUBLIC_API_URL` to prod API |
| | 6.5 | Embed job as one-shot / cron | `index_embeddings.py`, CI or scheduler | Manual embed step | Post-deploy or nightly re-embed |
| **7 Auth** | 7.1 | Auth provider choice + spec | `docs/specs/auth.md` | Open API not production-safe | Clerk/Auth0; scope read vs write |
| | 7.2 | API middleware | `apps/api/main.py`, deps | Protect write/LLM endpoints | JWT validation on POST routes |
| | 7.3 | Web auth shell | `apps/web/` middleware | Gated routes | Sign-in, session, protected `/screen` |
| | 7.4 | Rate limiting on LLM routes | `jurisdictions` chat/parse | Cost/abuse surface | Per-user or per-IP limits |
| **8 Ops** | 8.1 | Structured logging | `apps/api/app/` | No production debugging | JSON logs, request IDs |
| | 8.2 | Error tracking | Sentry or similar | Silent failures in prod | SDK on API + web |
| | 8.3 | Staleness alerts | jurisdiction nightly CI | Drift undetected until manual | Slack/email on nightly failure |
| | 8.4 | Secrets management | deploy platform | `.env` local only | Platform secrets, no keys in repo |

**After DDRs:** revisit rows marked "spec first" — add rows you discover, remove rows you decide against.
