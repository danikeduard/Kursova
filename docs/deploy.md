# Deployment

1. Create a Supabase or Neon PostgreSQL database and copy its pooled
   `DATABASE_URL` connection string, including `sslmode=require`.
2. Set `APP_ENV=production`, a random `SECRET_KEY` with at least 32 characters,
   `DATABASE_URL`, provider credentials, `LLM_MODEL`, `DAILY_MESSAGE_CAP`,
   `RATE_LIMIT_CHAT`, and a shared Redis `RATELIMIT_STORAGE_URI` in Render/Fly.io.
   Set `TRUSTED_PROXY_COUNT` only to the number of trusted proxies in front of
   the app. Configure `SESSION_COOKIE_SECURE=true` when HTTPS is enabled.
3. Promote administrators with `flask --app wsgi:app make-admin`; registration
   never grants admin access from an email address. Use the release command
   `flask --app wsgi:app db upgrade` and a start command
   `gunicorn --bind 0.0.0.0:$PORT wsgi:app`.
4. Configure the custom domain and enable the platform's managed HTTPS.
5. Verify `/healthz`, registration, and a mocked/staging chat before opening
   the application to users.
