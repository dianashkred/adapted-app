# AdaptED

Adaptive AI tutor that teaches strictly from a student's own course materials, detects knowledge gaps per topic and adapts explanations, check questions and reviews. Diploma project 2026/27 — Diana Shkred.

| Part | Technology | State |
| --- | --- | --- |
| Database | PostgreSQL 16 + pgvector, SQLAlchemy 2, Alembic | **stage 1 — done** ([docs/database.md](docs/database.md)) |
| Backend API | Python, FastAPI | health check; API of epics E1–E8 in stage 2 |
| Frontend | React + TypeScript + Vite | stage 3 |

## For the database review

| What | Where |
| --- | --- |
| Database documentation (start here) | [docs/database.md](docs/database.md) |
| Data dictionary: tables, columns, types, keys | [docs/data-dictionary.md](docs/data-dictionary.md) |
| Logical schema (ER diagram) | [docs/er-diagram.png](docs/er-diagram.png) |
| DDL script (generated from the migrations) | [db/schema.sql](db/schema.sql) |
| Migrations — the schema is built only by them | [backend/alembic/versions/](backend/alembic/versions/) |
| Roles and databases | [db/init/01-roles-and-databases.sh](db/init/01-roles-and-databases.sh) |
| Tests on a real PostgreSQL | [backend/tests/](backend/tests/) |
| How to run | section "Quick start" below |

## Quick start (Docker Desktop must be running)

```bash
cp .env.example .env            # Windows PowerShell: copy .env.example .env  — then fill in the values
docker compose up -d db         # PostgreSQL + pgvector; creates roles and the databases adapted / adapted_test
docker compose up --build backend   # applies the migrations, API on http://localhost:8000/health
```

## Working on your computer (Python 3.12+)

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head            # schema, rights, business logic, reference data, views
python -m scripts.seed_demo     # demo data with edge cases
pytest --cov=app                # 109 integration tests on a real PostgreSQL (database adapted_test)
```

Regenerate the documentation after a schema change:

```bash
python -m scripts.generate_data_dictionary   # docs/data-dictionary.md
python -m scripts.generate_er                # docs/er-diagram.* (needs Graphviz)
bash ../db/export_schema.sh                  # db/schema.sql (Git Bash on Windows)
```

## Structure

```
backend/app/core/          settings, protection of e-mail addresses
backend/app/db/models/     22 ORM models in 7 blocks
backend/app/db/sql/        reference data
backend/alembic/versions/  0001 schema · 0002 roles · 0003 business logic · 0004 reference data · 0005 views · 0006 confidence, review list, topic/revision quizzes, simulated profiles
backend/scripts/           seeds, generators of the data dictionary and the ER diagram
backend/tests/             integration tests
db/init/                   roles and databases (first start of the container)
db/schema.sql              DDL, generated from the migrations
docs/                      database documentation, data dictionary, logical schema
```

## Security

No secrets in the repository: credentials come from `.env` (ignored by Git). The application connects as a non-superuser role. E-mail addresses are encrypted; learning data is linked only to a pseudonymous learner id. AdaptED stores no passwords (Supabase Auth).
