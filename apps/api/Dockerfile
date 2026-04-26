FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[dev]"

COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
COPY app ./app
COPY tests ./tests

EXPOSE 8000
