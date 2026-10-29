# ArbiterForge

Case file for commercial arbitration (третейское разбирательство) involving Russian companies: the ICAC and the MAC at the Chamber of Commerce and Industry of the Russian Federation, other permanent arbitration institutions, and ad hoc tribunals. The core is a PostgreSQL event journal and a procedural-deadline engine computed from Закон РФ № 5338-I, Федеральный закон № 382-ФЗ, the Arbitration Procedure Code and the Civil Code.

State courts and the commercial-court case file live in [Court-Hub](https://github.com/d1g-1t/Court-Hub). This repository is arbitration only.

---

## What this is

Arbitration deadlines are spread across three or four acts and counted under different rules: "days" in the Arbitration Procedure Code are working days only (ст. 113–114 АПК РФ), while months and days under the Civil Code are calendar periods shifted to a working day (ст. 191–193 ГК РФ). Domestic or international regime changes both the periods and the requirements for the tribunal. One wrong period — the three months to set an award aside — costs the client the right to challenge. A spreadsheet does not remember why a period is what it is, and it does not keep a history of changes.

- **Case aggregate with an event journal.** 27 commands (from `open_case` to `close_case`). A stale `If-Match` returns 409 Conflict. Projections are a pure function of the case history; a full rebuild produces the same result.
- **Legal engine.**
  - Production calendar for 2025–2027 (ТК РФ ст. 112 plus the transfer decrees).
  - Periods under the Arbitration Procedure Code (working days) and the Civil Code (calendar days, end shifted to a working day).
  - Regime under п. 1, 3 ст. 1 Закона РФ № 5338-I.
  - Arbitrability matrix (ч. 2 ст. 33 АПК, ч. 6 ст. 27 АПК, ст. 248.1 АПК).
  - Tribunal check: number of arbitrators, odd count, higher legal education under ч. 3 ст. 11 Федерального закона № 382-ФЗ.
  - Automatic case periods: appointment of an arbitrator, challenge, recourse to a state court, correction and an additional award, setting aside (ч. 4 ст. 230 АПК / п. 3 ст. 34 Закона РФ № 5338-I), deposit of the file (ст. 39 Федерального закона № 382-ФЗ).
  - Every engine response contains a quotation and a source reference.
- **Event store used as the outbox.** There is no separate outbox table. The relay reads `domain_events` by `(tx_id, global_seq)` below `pg_snapshot_xmin`, so events of unfinished transactions are neither lost nor reordered. Publication goes to a Redis Stream with the idempotent id `{tx_id}-{global_seq}`. Retries are Celery `autoretry_for` / `retry_backoff`, not a hand-rolled reliability layer.
- **Audit log.** An HMAC chain with a sequence number inside the organisation, covering the payload. Verify with `GET /api/v1/admin/audit/verify`.
- **Ollama assistant.** It drafts a summary of a procedural order and marks it as requiring human review. Accepting the draft is a separate action with the `po:accept` permission; author and time are recorded.
- **Multi-tenancy and RBAC.** PASETO v4.local, bcrypt, roles `ADMIN`, `CASE_MANAGER`, `COUNSEL`, `ARBITRATOR_READONLY`, `AUDITOR_READONLY`. Another tenant's case answers 404.

Stack: Python 3.14, FastAPI 0.143, Pydantic 2.14, SQLAlchemy 2.1 (asyncpg), Alembic 1.20, Celery 5.6, Redis 8, PostgreSQL 17, structlog, prometheus-client, uv. Ollama is reached at `ARBITERFORGE_OLLAMA_BASE_URL` (default `http://host.docker.internal:11434`, model `qwen2.5:7b`). It is not a Compose service.

### Overlap with neighbouring projects

Normalised source lines that also appear elsewhere:

| Project | Matching lines | Share of ArbiterForge | What is shared |
|---|---|---|---|
| Edo-Adapter-Enterprise | 87 | 5.8% | FastAPI / structlog / settings template |
| WebhookRelay | 30 | 2.0% | Redis wiring |
| MyArbitrBridge | 41 | 2.7% | Application template |

None of those projects has its own reliability layer or outbox, so the outbox stub here was replaced by the event store used as an outbox plus Celery's built-in retries.

---

## Architecture at a glance

```
src/arbiterforge/
  domain/          calendar, deadlines, regime, arbitrability, tribunal, aggregate, audit, norm registry
  application/     command service (audit, tenant), queries, legal service
  infrastructure/  event store, projections, Redis Stream relay, Celery, export, Ollama
  presentation/    FastAPI v1, RBAC, error handling, request id and metrics
  seed.py          fictitious demo data
alembic/           0001 — initial schema; 0002 — xid8, audit sequence, drop outbox_events
```

Command flow:

```
POST /api/v1/cases/{id}/commands/...   (If-Match: version)
  → aggregate.decide() → INSERT domain_events (UNIQUE(aggregate_id, version))
  → status, tribunal, calendar and deadline projections (same transaction)
  → audit row (HMAC chain)
Celery beat → relay_events → XADD arbiterforge:events
```

---

## Quick start

### Prerequisites

- Docker + Docker Compose v2
- `make`
- `curl`

### Go

```bash
git clone <this-repo> ArbiterForge && cd ArbiterForge
make setup
```

| What | URL |
|------|-----|
| API | http://127.0.0.1:20100 |
| Docs | http://127.0.0.1:20100/docs |
| Health | http://127.0.0.1:20100/api/v1/health/live |
| Ready | http://127.0.0.1:20100/api/v1/health/ready |
| Metrics | http://127.0.0.1:20100/metrics |

Demo login after `make seed`: `admin@arbiterforge.local` / `ChangeMe123!`.

Demo data is fictitious: organisation АО «Демо Логистик», ИНН 0000123450, one ICAC case taken through receipt of the award, and one domestic ad hoc case.

Concurrent writes: `make demo-concurrency`.

---

## Non-standard ports (intentional)

| Service | Host port | Notes |
|---------|-----------|-------|
| API | **20100** | published on `127.0.0.1` (container listens on 8023) |
| PostgreSQL | **20101** | only via `docker-compose.debug.yml` |
| Redis | **20102** | only via `docker-compose.debug.yml` |

Postgres and Redis are not published by default, so this stack can sit next to other portfolio projects. Override via `*_HOST_PORT` in `.env`.

```bash
docker compose -f docker-compose.yml -f docker-compose.debug.yml up -d
```

---

## Make targets

| Target | Purpose |
|--------|---------|
| `make setup` | Full install from a fresh clone |
| `make up` / `make down` | Start / stop the stack |
| `make logs` / `make ps` | Tail logs (`make logs s=api`) / show status |
| `make migrate` / `make seed` | Migrations / demo data |
| `make check-migrations` | `alembic check` |
| `make demo-concurrency` | Concurrent-write demonstration |
| `make test` / `make lint` | Containerised pytest on Postgres + Redis / ruff |
| `make fmt` | `ruff format` and `ruff check --fix` |
| `make shell` | Shell in the API container |
| `make clean` | Remove containers, volumes and local images for this project |
| `make local-install` / `local-test` / `local-lint` | Host-side uv workflow |

---

## API overview

Auth: `Authorization: Bearer <paseto>`. Commands require `If-Match`. OpenAPI is at `/docs`.

| Area | Paths under `/api/v1` |
|------|------------------------|
| Auth and org | `auth/login`, `auth/logout`, `orgs/me` |
| Health | `health/live`, `health/ready` |
| Cases | list, create, card with legal basis, `timeline`, `tribunal`, `deadlines` |
| Commands | `cases/{id}/commands/`: `file`, `register-rfa`, `add-party`, `nominate-arbitrator`, `constitute-tribunal`, `challenge-arbitrator`, `decide-challenge`, `replace-arbitrator`, `rule-on-jurisdiction`, `adopt-timetable`, `extend-milestone`, `open-submission-round`, `file-submission`, `issue-procedural-order`, `schedule-hearing`, `mark-hearing-held`, `start-deliberation`, `draft-award`, `issue-award`, `receive-award`, `request-correction`, `decide-correction`, `file-set-aside`, `resolve-set-aside`, `close`, `terminate` |
| Legal engine | `legal/norms`, `legal/working-days/{year}`, `legal/deadlines/compute`, `legal/regime`, `legal/arbitrability`, `legal/tribunal-check` |
| Calendar and export | `calendar`, `exports/timeline-packs/{id}` (HTML) |
| Procedural orders | `procedural-orders/{id}/summarize-suggest`, `procedural-orders/{id}/accept` |
| Admin | `admin/projections/rebuild`, `admin/outbox/lag`, `admin/audit/verify` |

Prometheus metrics are at `/metrics` (outside `/api/v1`).

---

## Testing

```bash
make test
make lint
uv run ruff check . && uv run ruff format --check .
uv run pytest tests/unit
uv run alembic check
```

A full host run, including integration tests:

```bash
ARBITERFORGE_TEST_DATABASE_URL=postgresql+asyncpg://arbiterforge:change-me@127.0.0.1:20101/arbiterforge_test \
ARBITERFORGE_TEST_REDIS_URL=redis://:change-me@127.0.0.1:20102/1 \
uv run pytest --cov
```

Those host ports are the debug overlay (`POSTGRES_HOST_PORT` **20101**, `REDIS_HOST_PORT` **20102**). Without `ARBITERFORGE_TEST_DATABASE_URL` and `ARBITERFORGE_TEST_REDIS_URL`, integration tests are skipped. `make test` runs them inside Compose, where `.env.example` points the same variables at the internal `postgres` and `redis` hostnames (Redis database `1`).

- Unit tests: calendar and deadlines, including Hypothesis properties; rules; the aggregate over random command sequences; audit; projections; adapters.
- Integration tests on real PostgreSQL and Redis: migrations and `alembic check`; concurrent writers; projection-rebuild equivalence; a forged audit chain; relay idempotency, unfinished transactions and `SKIP LOCKED`; a full scenario through the API, tenant isolation, RBAC and Celery tasks.

---

## Limitations

- The calendar covers 2025–2027. For any other year the engine returns no date and the mark `calendar_not_covered:YEAR`. A new year is added in `domain/calendar.py` after the government decree is published.
- Audit rows created under schema 0001 fail chain verification: the old hash did not cover the payload.
- Adding a foreign party after the case is opened does not recompute the regime.
- The ICAC and MAC rules, and the status of particular permanent arbitration institutions (for example the Russian Arbitration Center), were not checked in full text. The API returns a warning only. Periods set by institutional rules are entered by hand through `adopt_timetable` / `extend_milestone`.
- Case law is neither used nor cited.
- The engine is a control tool, not a legal opinion. A lawyer checks the results.
- The Docker image and Compose file were not built in the development environment of this version (Docker was not available). The application, migrations and Celery were checked locally.

---

## Legal basis

Norms, quotations and links live in `domain/legal_basis.py` and are served by `GET /api/v1/legal/norms`. Editions checked on 16.10.2026.

| Act | Edition | Norms used |
|---|---|---|
| Закон РФ от 07.07.1993 № 5338-I «О международном коммерческом арбитраже» | ред. от 30.12.2021 | п. 1, 3 ст. 1; ст. 10; п. 3 ст. 11; п. 2–3 ст. 13; п. 3 ст. 16; п. 1, 3 ст. 33; п. 1, 3 ст. 34; п. 6 Положения о МАК |
| Федеральный закон от 29.12.2015 № 382-ФЗ «Об арбитраже (третейском разбирательстве) в РФ» | ред. от 08.08.2024 | ст. 10; ч. 3, 6–7 ст. 11; ч. 2–3 ст. 13; ч. 3 ст. 16; ч. 1 ст. 24; ч. 1–2, 4 ст. 37; ч. 1–2 ст. 39; ст. 40; ч. 1 ст. 44; ч. 7, 7.1, 10 ст. 45 |
| Арбитражный процессуальный кодекс РФ | ред. от 15.12.2025, в силе с 01.01.2026 | ч. 6 ст. 27; ч. 1–2 ст. 33; ст. 113–114; ч. 2–3 ст. 225.1; ч. 4 ст. 230; ч. 3 ст. 236; ст. 248.1 |
| Гражданский кодекс РФ, ч. 1 | ред. от 10.06.2026 | ст. 191–193 |
| Трудовой кодекс РФ | ред. от 25.05.2026 | ст. 112 |
| Постановления Правительства РФ о переносе выходных | № 1335 от 04.10.2024 (2025), № 1466 от 24.09.2025 (2026), № 1187 от 17.09.2026 (2027) | production calendar |
| Информация ТПП РФ от 23.10.2024 | — | ICAC rule changes (warning only) |

Sources: ips.pravo.gov.ru (official legal-information portal), consultant.ru, base.garant.ru.

---

## License

MIT
