# LinguaPath

LinguaPath is a Flask application for adaptive English conversation practice,
CEFR progress tracking, Feedback collection, and Bug Report review.

## Features

- AI tutor chat and saved conversations.
- Grammar, vocabulary, and writing progress.
- Five-question Feedback form; each user has one response that can be updated.
- Administrator Feedback dashboard with summaries and charts.
- Floating Bug Report dialog with technical details and local drafts.
- Administrator Bug Report panel with filters, status changes, notes, and CSV export.
- A consistent dark theme across the site.

The selected LLM provider and model are server configuration only.

## Local setup

Windows with PowerShell:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
flask --app wsgi db upgrade
flask --app wsgi run
```

Open <http://127.0.0.1:5000>.

The app uses `instance/linguapath.db` by default. Keep `.env` local and never
commit secrets.

## Environment

Local demo:

```dotenv
SECRET_KEY=replace-with-a-long-random-local-secret
APP_ENV=development
SESSION_COOKIE_SECURE=false
DEMO_MODE=true
LLM_MODEL=your-local-model-name
ADMIN_SHOW_USER_EMAIL=true
```

Live provider example:

```dotenv
DEMO_MODE=false
LLM_PROVIDER=groq
GROQ_API_KEY=your-groq-api-key
LLM_MODEL=your-supported-model-id
```

OpenAI can be used by setting `LLM_PROVIDER=openai`, `OPENAI_API_KEY`,
`OPENAI_BASE_URL`, and `LLM_MODEL`.

Optional model overrides: `LLM_MODEL_EVALUATOR`, `LLM_MODEL_TITLE`, and
`LLM_MODEL_EXPLAIN`.

## Local demo accounts

For a disposable local database:

| Login | Password | Access |
| --- | --- | --- |
| `admin` | `admin` | Administrator |
| `user` | `user` | Standard user |

Change or remove these accounts before deployment. Administrators can also be
promoted with:

```powershell
flask --app wsgi make-admin
```

## Main routes

| Route | Access |
| --- | --- |
| `/chat` | Logged-in users |
| `/progress` | Logged-in users |
| `/feedback` | Logged-in users |
| `/privacy` | Public |
| `/admin/feedback` | Administrators |
| `/admin/bug-reports` | Administrators |

## Database

Apply migrations:

```powershell
flask --app wsgi db upgrade
```

For PostgreSQL, set `DATABASE_URL` to a PostgreSQL connection URL.

Account deletion removes the user's conversations, ratings, Feedback, Bug
Reports, and settings.

## Validation

```powershell
python -m pytest -q
ruff check .
```

Health check: `GET /healthz`.
