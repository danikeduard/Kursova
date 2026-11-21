# Database migrations

Run `flask --app wsgi db init` once for a new checkout, then use
`flask --app wsgi db migrate -m "describe change"` and
`flask --app wsgi db upgrade`. Production deployments should run `db upgrade`
as a release step before starting Gunicorn.
