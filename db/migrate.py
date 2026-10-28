from pathlib import Path
import os

import psycopg
from dotenv import load_dotenv


def main() -> None:
    load_dotenv()
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL не задано. Заповніть .env перед міграцією.")
    with psycopg.connect(url, sslmode="require", connect_timeout=5) as connection:
        connection.execute((Path(__file__).with_name("schema.sql")).read_text(encoding="utf-8"))
    print("Neon schema ibot успішно застосовано.")


if __name__ == "__main__":
    main()
