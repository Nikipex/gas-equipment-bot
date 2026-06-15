from __future__ import annotations

import asyncio
import json
import os
import socket
from urllib.parse import urlparse
from dataclasses import dataclass
from datetime import datetime

import redis
from aiogram import Bot
from loguru import logger
from sqlalchemy import create_engine, text


@dataclass
class CheckResult:
    name: str
    ok: bool
    message: str


class HealthcheckService:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self.admin_chat_id = os.getenv("TELEGRAM_ADMIN_CHAT_ID")
        self.interval_seconds = int(os.getenv("HEALTHCHECK_INTERVAL_SECONDS", "300"))

        self.database_url = os.getenv("PROCUREMENT_DATABASE_URL")
        self.redis_url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
        self.telegram_proxy_url = os.getenv("TELEGRAM_PROXY_URL", "").strip()

        self.tunnel_host = os.getenv("POSTGRES_TUNNEL_HOST", "127.0.0.1")
        self.tunnel_port = int(os.getenv("POSTGRES_TUNNEL_PORT", "15433"))

        self.state_path = os.getenv("HEALTHCHECK_STATE_PATH", "/tmp/gas_bot_health_state.json")
        self._last_status: dict[str, bool] = self._load_state()

    async def run_forever(self) -> None:
        if not self.admin_chat_id:
            logger.warning("TELEGRAM_ADMIN_CHAT_ID is not set, healthcheck notifications disabled")
            return

        logger.info(
            f"Healthcheck started: interval={self.interval_seconds}s "
            f"admin_chat_id={self.admin_chat_id}"
        )

        while True:
            try:
                await self._run_once()
            except Exception as exc:
                logger.exception(f"Healthcheck loop failed: {exc}")

            await asyncio.sleep(self.interval_seconds)

    async def _run_once(self) -> None:
        tunnel = await asyncio.to_thread(self._check_tunnel)
        redis_check = await asyncio.to_thread(self._check_redis)
        proxy_check = await asyncio.to_thread(self._check_telegram_proxy)

        checks = [tunnel, redis_check, proxy_check]

        # If tunnel is down, PostgreSQL will obviously be down too.
        # Avoid duplicate alerts for the same root cause.
        if tunnel.ok:
            checks.append(await asyncio.to_thread(self._check_postgres))

        for check in checks:
            prev = self._last_status.get(check.name)
            self._last_status[check.name] = check.ok
            self._save_state()

            if prev is None:
                if not check.ok:
                    await self._notify_down(check)
                continue

            if prev is True and check.ok is False:
                await self._notify_down(check)

            if prev is False and check.ok is True:
                await self._notify_up(check)

    def _check_telegram_proxy(self) -> CheckResult:
        if not self.telegram_proxy_url:
            return CheckResult(
                name="telegram_proxy",
                ok=True,
                message="TELEGRAM_PROXY_URL не задан, прокси не используется",
            )

        try:
            parsed = urlparse(self.telegram_proxy_url)
            host = parsed.hostname
            port = parsed.port

            if not host or not port:
                return CheckResult(
                    name="telegram_proxy",
                    ok=False,
                    message="TELEGRAM_PROXY_URL задан некорректно: host/port не найдены",
                )

            with socket.create_connection((host, port), timeout=10):
                return CheckResult(
                    name="telegram_proxy",
                    ok=True,
                    message=f"Telegram proxy {host}:{port} доступен",
                )

        except Exception as exc:
            return CheckResult(
                name="telegram_proxy",
                ok=False,
                message=f"Telegram proxy недоступен: {type(exc).__name__}: {exc}",
            )

    def _check_tunnel(self) -> CheckResult:
        try:
            with socket.create_connection(
                (self.tunnel_host, self.tunnel_port),
                timeout=3,
            ):
                return CheckResult(
                    name="postgres_tunnel",
                    ok=True,
                    message=f"{self.tunnel_host}:{self.tunnel_port} доступен",
                )
        except Exception as exc:
            return CheckResult(
                name="postgres_tunnel",
                ok=False,
                message=f"{self.tunnel_host}:{self.tunnel_port} недоступен: {type(exc).__name__}: {exc}",
            )

    def _check_postgres(self) -> CheckResult:
        if not self.database_url:
            return CheckResult(
                name="postgres",
                ok=False,
                message="PROCUREMENT_DATABASE_URL не задан",
            )

        try:
            engine = create_engine(self.database_url, pool_pre_ping=True)
            with engine.connect() as conn:
                conn.execute(text("select 1"))
            return CheckResult(name="postgres", ok=True, message="PostgreSQL OK")
        except Exception as exc:
            return CheckResult(
                name="postgres",
                ok=False,
                message=f"PostgreSQL недоступен: {type(exc).__name__}: {exc}",
            )

    def _check_redis(self) -> CheckResult:
        try:
            client = redis.Redis.from_url(self.redis_url, decode_responses=True)
            pong = client.ping()
            if pong:
                return CheckResult(name="redis", ok=True, message="Redis OK")
            return CheckResult(name="redis", ok=False, message="Redis ping вернул False")
        except Exception as exc:
            return CheckResult(
                name="redis",
                ok=False,
                message=f"Redis недоступен: {type(exc).__name__}: {exc}",
            )

    def _load_state(self) -> dict[str, bool]:
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {str(k): bool(v) for k, v in data.items()}
        except Exception:
            return {}

    def _save_state(self) -> None:
        try:
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(self._last_status, f, ensure_ascii=False)
        except Exception as exc:
            logger.warning(f"Failed to save healthcheck state: {exc}")

    async def _notify_down(self, check: CheckResult) -> None:
        await self._send(
            "🚨 <b>Gas Equipment Bot Alert</b>\n\n"
            f"❌ <b>{check.name}</b> упал\n"
            f"{check.message}\n\n"
            f"Время: {self._now()}"
        )

    async def _notify_up(self, check: CheckResult) -> None:
        await self._send(
            "✅ <b>Gas Equipment Bot Recovery</b>\n\n"
            f"<b>{check.name}</b> восстановлен\n"
            f"{check.message}\n\n"
            f"Время: {self._now()}"
        )

    async def _send(self, text_value: str) -> None:
        try:
            await self.bot.send_message(
                chat_id=int(self.admin_chat_id),
                text=text_value,
            )
        except Exception as exc:
            logger.warning(f"Failed to send healthcheck notification: {exc}")

    @staticmethod
    def _now() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
