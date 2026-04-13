FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md RULEBOOK.md ARCHITECTURE.md /app/
COPY app /app/app
COPY tests /app/tests
COPY scripts /app/scripts

RUN pip install --upgrade pip && pip install .

ENV DATABASE_URL=postgresql+psycopg://nba:nba@db:5432/nba_pool
ENV SECRET_KEY=dev-secret-change-me
ENV HOST=0.0.0.0
ENV PORT=8000

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host ${HOST:-0.0.0.0} --port ${PORT:-8000}"]
