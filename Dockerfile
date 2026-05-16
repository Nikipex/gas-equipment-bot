FROM python:3.12-slim

LABEL maintainer="gas-equipment-bot"

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/opt/app

WORKDIR /opt/app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app
COPY data ./data
COPY sql ./sql
COPY scripts ./scripts
COPY alembic.ini ./

RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir \
        aiogram \
        pandas \
        openpyxl \
        xlrd \
        sqlalchemy \
        psycopg2-binary \
        asyncpg \
        python-dotenv \
        pydantic-settings \
        loguru \
        rapidfuzz

RUN groupadd -r bot && useradd -r -g bot bot \
    && mkdir -p /opt/app/data /opt/app/logs \
    && chown -R bot:bot /opt/app

USER bot

CMD ["python", "-m", "app.main"]
