# 🤖 AI English Tutor

Невеликий Flask-чат, який допомагає вчити англійську. Бот працює через Groq,
підлаштовує складність під користувача (beginner → advanced) і за командою
`/analysis` робить розбір помилок.

## Запуск

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env             # Windows: copy .env.example .env
# впиши GROQ_API_KEY і DATABASE_URL у .env
python run.py
```

Відкрий http://localhost:5000

## Налаштування (`.env`)

| Змінна         | Опис                                       |
|----------------|--------------------------------------------|
| `GROQ_API_KEY` | Ключ з console.groq.com                    |
| `GROQ_MODEL`   | Мовна модель (напр. `openai/gpt-oss-120b`) |
| `DATABASE_URL`  | Рядок підключення PostgreSQL              |
| `SECRET_KEY`    | Секрет для Flask-сесій                    |
| `HISTORY_LIMIT`| Скільки останніх повідомлень йде в модель  |
| `FLASK_DEBUG`  | `1` — режим розробки                       |
| `PORT`         | Порт сервера                               |

## Структура

```
run.py                  # точка входу
app/
├── __init__.py         # create_app (application factory)
├── config.py           # читає .env
├── routes.py           # /, /chat, /reset
├── services/
│   ├── llm.py          # обгортка над Groq
│   ├── adaptive.py     # оцінка рівня користувача
│   ├── prompts.py      # системні промпти
│   └── store.py        # історія розмов у PostgreSQL
├── templates/index.html
└── static/{css,js}
```

Під час запуску застосунок автоматично створює таблицю `conversations`.
Якщо PostgreSQL недоступний, запити `/chat` і `/reset` повертають `503`
з повідомленням про проблему з підключенням, а технічні деталі записуються
в журнал сервера.

## Open WebUI iBot filter

`ibot_filter.py` is a separate Open WebUI Filter for the iBot tutor. It does
not change the Flask application above. The database schema must already exist
in PostgreSQL under `ibot`; the filter never creates or modifies tables.

### Install

In Open WebUI, open **Admin Panel -> Functions -> Add Function**, paste
`ibot_filter.py`, save and enable it. Apply it to the iBot model, or enable it
globally. Open WebUI installs `psycopg2-binary` from the function frontmatter.

Set these Valve values (or environment variables where noted):

* `DATABASE_URL`: Neon PostgreSQL DSN; it must be available to the Open WebUI
  container. The filter adds `sslmode=require` and a short connect timeout.
* `LLM_API_KEY`: defaults to `OPENAI_API_KEY`; use a Groq OpenAI-compatible key.
* `LLM_BASE_URL`: defaults to `https://api.groq.com/openai/v1`.
* `ANALYZER_MODEL`, `JUDGE_MODEL`, `JUDGE_EVERY`, and `JUDGE_RUNS`.
* `ENABLE_ANALYSIS`, `INJECT_PROFILE`, `STORE_MESSAGE_TEXT`, and
  `REQUIRE_CONSENT` as privacy/operation switches.

### Verify

After sending several English messages, inspect the results using the Neon
SQL console:

```sql
SELECT * FROM ibot.skill_state WHERE learner_id = '<user-id>';
SELECT * FROM ibot.skill_history WHERE learner_id = '<user-id>' ORDER BY created_at DESC;
SELECT * FROM ibot.mistake_weights WHERE learner_id = '<user-id>' ORDER BY weight DESC;
SELECT * FROM ibot.v_cost_summary WHERE learner_id = '<user-id>';
```

The filter injects one `[LEARNER PROFILE]` system message per request, strips
`<analytics>` blocks, and performs analysis in a background thread. Database
or analyzer failures are logged and do not fail the chat.

Known limitations: the supplied database schema must match the column names
used by the filter; streaming redaction cannot recover text already delivered
by a provider; the periodic judge requires message text to be stored if it
must assess more than the current message; and Open WebUI must allow outbound
requests to Groq and Neon.
