# LinguaPath

**An adaptive AI English tutor with CEFR progress tracking.** LinguaPath is a
Flask web application that combines conversational practice with structured
grammar, vocabulary, and writing assessments. It is a student project and a
prototype for exploring adaptive language learning.

## What you can demonstrate

- Create an account and choose a starting CEFR level (A1–C2).
- Practice English in a chat workspace with saved conversations.
- Review ratings for grammar, vocabulary, and writing on the progress page.
- See rating history and evidence behind level changes.
- Search, pin, archive, duplicate, organize, and export conversations.
- Configure reply length, emoji use, theme, and preferred name.
- Run the app in a deterministic demo mode without sending prompts to an LLM.

## Quick start: local demo

Requires Python 3.12 and PowerShell on Windows. The commands below use the
project's virtual environment and the SQLite database created locally.

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` for a local HTTP demo:

```dotenv
SECRET_KEY=replace-this-with-a-long-random-local-secret
APP_ENV=development
SESSION_COOKIE_SECURE=false
DEMO_MODE=true
```

Apply the database migrations and start the server:

```powershell
flask --app wsgi db upgrade
flask --app wsgi run
```

Open <http://127.0.0.1:5000>, create a demo account, and try the chat and
progress pages. Demo mode returns a fixed example tutor response and assessment;
it does not call Groq or OpenAI. Use it to demonstrate the user flow, not as
evidence of tutor quality or rating accuracy.

The default database is `instance/linguapath.db`. The database and `.env` are
local-only and are excluded from Git.

## Run with a live LLM

Set `DEMO_MODE=false`, then configure one provider in `.env`:

```dotenv
LLM_PROVIDER=groq
GROQ_API_KEY=your-groq-api-key
LLM_MODEL=your-supported-model-id
```

Or use the OpenAI API:

```dotenv
LLM_PROVIDER=openai
OPENAI_API_KEY=your-openai-api-key
OPENAI_BASE_URL=https://api.openai.com/v1
LLM_MODEL=your-supported-model-id
```

Do not commit credentials. The selected provider and model are configured by
the server; users cannot change them from account settings. Optional
`LLM_MODEL_EVALUATOR`, `LLM_MODEL_TITLE`, and `LLM_MODEL_EXPLAIN` values can
select models for individual tasks. Restart the server after changing provider
configuration.

## Database changes

Use Alembic migrations for schema changes:

```powershell
flask --app wsgi db migrate -m "describe the change"
# Review the generated migration before applying it.
flask --app wsgi db upgrade
```

For an existing database, apply pending migrations with `flask --app wsgi db
upgrade`. To make a local backup or reset a disposable development database:

```powershell
python scripts/backup_local_db.py
python scripts/reset_local_db.py --yes
```

**Reset deletes the local SQLite database.** Do not use it with a database you
need to keep. PostgreSQL support is available with the optional `psycopg2`
driver and a `DATABASE_URL`; production setup is described in
[`docs/deploy.md`](docs/deploy.md).

## How the adaptive rating works

The evaluator returns separate CEFR observations for grammar, vocabulary, and
writing. Messages must contain enough English text to be eligible for a rating
update. The adaptive mode accounts for message length and confidence, limits
large single-step changes, and keeps displayed CEFR labels stable near level
boundaries. The first five valid messages have double weight in baseline mode.

The model, constants, worked example, and limitations are documented in
[`docs/level_model.md`](docs/level_model.md). Ratings are learning estimates,
not certified CEFR results. LLM assessments can be wrong; short or unusual
messages provide limited evidence.

## Project structure

| Path | Responsibility |
| --- | --- |
| [`app/`](app) | Flask application, routes, authentication, models, tutor, evaluator, and providers |
| [`app/rating.py`](app/rating.py) | Pure CEFR rating and message-validity logic |
| [`app/templates/`](app/templates) | Server-rendered pages |
| [`app/static/`](app/static) | Chat client and visual styles |
| [`migrations/`](migrations) | Alembic schema migrations |
| [`scripts/`](scripts) | Database utilities, metrics, evaluation, and model replay |
| [`tests/`](tests) | Automated tests for routes, ratings, migrations, and providers |
| [`docs/`](docs) | Architecture, deployment, rating model, and study notes |

## Validation

Run the linter and test suite before presenting changes:

```powershell
ruff check .
python -m pytest -q
```

The app also exposes a lightweight health endpoint at `/healthz`.

## Project limitations

- Demo mode is deterministic and does not measure real model performance.
- Live assessment depends on the configured third-party LLM provider.
- The rating model and pedagogy are prototypes and need evaluation against
  teacher-reviewed examples and user-study data.
- No research findings or user-study results are included unless collected and
  reviewed separately.

## Further reading

- [Architecture](docs/architecture.md)
- [Deployment](docs/deploy.md)
- [Adaptive rating model](docs/level_model.md)
- [User-study protocol](docs/user_study.md)
