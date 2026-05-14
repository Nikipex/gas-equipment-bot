# ---------- build stage ----------
FROM python:3.12-slim AS builder

WORKDIR /opt/app

COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

# ---------- runtime stage ----------
FROM python:3.12-slim

LABEL maintainer="gas-equipment-bot"

RUN groupadd -r bot && useradd -r -g bot bot

WORKDIR /opt/app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY . .

RUN chown -R bot:bot /opt/app
USER bot

CMD ["python", "-m", "app.main"]
