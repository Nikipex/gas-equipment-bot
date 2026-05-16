# GAS EQUIPMENT BOT — DEPLOY GUIDE

## Stack

- Python 3.12
- Aiogram 3
- PostgreSQL
- Docker
- Docker Compose

---

# 1. Clone repository

```bash
git clone https://github.com/Nikipex/gas-equipment-bot.git
cd gas-equipment-bot
```

---

# 2. Create .env

```bash
cp .env.example .env
```

Open `.env` and fill values:

```env
BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN

DATABASE_URL=postgresql+asyncpg://bot:bot_password@localhost:5432/gas_equipment

PROCUREMENT_DATABASE_URL=postgresql+psycopg2://USER:PASSWORD@HOST:5432/torg_full

LOG_LEVEL=INFO
```

---

# 3. Build Docker container

```bash
docker compose -f docker-compose.prod.yml build --no-cache
```

---

# 4. Start bot

```bash
docker compose -f docker-compose.prod.yml up -d
```

Check running containers:

```bash
docker ps
```

Watch logs:

```bash
docker logs -f gas-equipment-bot-bot-1
```

---

# 5. Restart bot

```bash
docker compose -f docker-compose.prod.yml restart
```

---

# 6. Stop bot

```bash
docker compose -f docker-compose.prod.yml down
```

---

# 7. Update project

```bash
git pull

docker compose -f docker-compose.prod.yml build

docker compose -f docker-compose.prod.yml up -d
```

---

# 8. Important directories

## Supplier price cache

```text
data/supplier_prices/
```

## Logs

```text
logs/
```

---

# 9. Features

- Supplier Excel ingestion
- Multi-warehouse stock parsing
- Smart supplier search
- Dynamic pricing
- Supplier comparison
- Best offer detection
- Rounding logic
- Procurement calculations
- PostgreSQL catalog search

---

# 10. Production notes

- Use readonly PostgreSQL credentials for 1C DB
- Never expose `.env` publicly
- Mount persistent Docker volumes for `data/` and `logs/`
- Regularly backup supplier cache
- Use reverse proxy if exposing externally

---

# 11. Quick production commands

## Rebuild and restart

```bash
docker compose -f docker-compose.prod.yml down

docker compose -f docker-compose.prod.yml build --no-cache

docker compose -f docker-compose.prod.yml up -d
```

## Open container shell

```bash
docker exec -it gas-equipment-bot-bot-1 bash
```

## Check environment inside container

```bash
docker exec -it gas-equipment-bot-bot-1 printenv
```
