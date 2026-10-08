# 🤖 AI English Tutor

Невеликий Flask-чат, який допомагає вчити англійську. Бот працює через Groq,
підлаштовує складність під користувача (beginner → advanced) і за командою
`/analysis` робить розбір помилок.

## Запуск

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env             # і впиши свій GROQ_API_KEY
python run.py
```

Відкрий http://localhost:5000

## Налаштування (`.env`)

| Змінна         | Опис                                       |
|----------------|--------------------------------------------|
| `GROQ_API_KEY` | Ключ з console.groq.com                    |
| `GROQ_MODEL`   | Мовна модель (напр. `openai/gpt-oss-120b`) |
| `SECRET_KEY`   | Секрет для Flask-сесій                     |
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
│   └── store.py        # історія розмов у пам'яті
├── templates/index.html
└── static/{css,js}
```
