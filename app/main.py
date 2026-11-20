from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramAPIError, TelegramNetworkError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from aiogram.utils.backoff import BackoffConfig

from app.archive import LAST_DUMP_KEY, ArchiveService, DigestScheduler
from app.backup_service import (
    BackupError,
    create_snapshot,
    recover_database,
    rotate_snapshots,
)
from app.config import Config
from app.database import create_engine_and_session, init_database
from app.handlers import build_router
from app.middlewares import AccessMiddleware, UserContextMiddleware
from app.netcheck import diagnose
from app.ocr import OCRService
from app.repository import Repository
from app.single_instance import SingleInstanceError, SingleInstanceLock
from app.transport import (
    TRANSPORT_ERRORS,
    ConnectionMonitor,
    Transport,
    create_bot,
    describe_error,
    plan_routes,
)
from app.vin_gemini import GeminiSettings, startup_check

logger = logging.getLogger(__name__)
RECONNECT_DELAY = 5.0
# After a dropped line the bot comes back quickly, but if Telegram keeps
# refusing, waiting a little longer each time keeps Windows and the router
# quiet instead of hammering them every five seconds.
RECONNECT_BACKOFF = (5.0, 10.0, 20.0, 30.0, 60.0)
# Long polling window: Telegram holds the request open this long, so fewer
# requests are made and a slow answer is not mistaken for a broken connection.
POLLING_TIMEOUT = 30
# Anything that never reached the channel is retried on this schedule.
ARCHIVE_RETRY_INTERVAL = 1800.0
# The first route of every round gets more patience: a line that is throttled
# rather than cut still answers, only slowly, and twelve seconds is not enough
# to tell the difference.
FIRST_PROBE_TIMEOUT = 25.0
# Diagnose the network after the first complete failure and then every fifth
# one, so a long outage produces a report now and then instead of a wall of them.
DIAGNOSE_EVERY = 5


class _QuietPollingRetries(logging.Filter):
    """A dropped long poll is a network blink, not an error worth a traceback.

    Only the messages aiogram writes while it waits for Telegram and retries
    are touched. Anything Telegram actually answered (a rejected token, a
    blocked bot) keeps its level, because that is a real fault.
    """

    _retry_words = ("failed to fetch updates", "sleep for")
    _line_words = ("telegramnetworkerror", "clientconnector", "timeout", "winerror")

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage().lower()
        if not any(word in message for word in self._retry_words):
            return True
        if record.levelno > logging.ERROR:
            return True
        answered = record.levelno == logging.ERROR and not any(
            word in message for word in self._line_words
        )
        if answered:
            # Telegram itself said no — a revoked token or a blocked bot. That
            # is a fault and stays one.
            return True
        record.levelno = logging.INFO
        record.levelname = "INFO"
        return True


def configure_logging(log_level: str) -> None:
    log_directory = Path("logs")
    log_directory.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )
    file_handler = RotatingFileHandler(
        log_directory / "bot.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    handlers: list[logging.Handler] = [file_handler]
    if sys.stdout is not None:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        handlers.append(console_handler)
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        handlers=handlers,
        force=True,
    )
    logging.getLogger("aiogram.dispatcher").addFilter(_QuietPollingRetries())


async def configure_commands(bot: Bot) -> None:
    russian = [
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="menu", description="Главное меню"),
        BotCommand(command="manual", description="Инструкция по работе"),
        BotCommand(command="cancel", description="Отменить действие"),
        BotCommand(command="help", description="Помощь"),
    ]
    german = [
        BotCommand(command="start", description="Bot starten"),
        BotCommand(command="menu", description="Hauptmenü"),
        BotCommand(command="manual", description="Bedienungsanleitung"),
        BotCommand(command="cancel", description="Aktion abbrechen"),
        BotCommand(command="help", description="Hilfe"),
    ]
    await bot.set_my_commands(russian)
    await bot.set_my_commands(russian, language_code="ru")
    await bot.set_my_commands(german, language_code="de")


async def prepare_telegram(
    bot: Bot, transport: Transport, *, timeout: float = 12.0
) -> bool:
    """Return True when Telegram is reachable through this transport."""

    try:
        identity = await asyncio.wait_for(bot.get_me(), timeout=timeout)
        await configure_commands(bot)
        await bot.delete_webhook(drop_pending_updates=False)
    except TRANSPORT_ERRORS as exc:
        logger.warning(
            "%s недоступно: %s. Пробую следующий способ подключения.",
            transport.name.capitalize(),
            describe_error(exc),
        )
        return False
    except TelegramAPIError:
        # A wrong token or a blocked bot is not fixed by another transport.
        raise
    logger.info(
        "Подключение к Telegram выполнено: @%s (%s)",
        identity.username,
        transport.describe(),
    )
    return True


async def connect_telegram(
    config: Config,
    transports: list[Transport],
    *,
    factory: Callable[[Config, Transport], Any] = create_bot,
) -> tuple[Any, Transport] | None:
    """Probe every transport in order and return the first one that answers.

    The bot therefore starts without any VPN or proxy program: a direct
    connection is tried first and a configured proxy is only a fallback.
    """

    for index, transport in enumerate(transports):
        bot = factory(config, transport)
        if await prepare_telegram(
            bot,
            transport,
            timeout=FIRST_PROBE_TIMEOUT if index == 0 else 12.0,
        ):
            return bot, transport
        await bot.session.close()
    return None


async def poll_with_transport(
    dispatcher: Dispatcher,
    bot: Any,
    transport: Transport,
    *,
    switchable: bool = True,
    stop_event: asyncio.Event | None = None,
) -> bool:
    """Poll Telegram through one transport.

    Returns True when the caller should connect again, and False only when the
    bot is really being stopped. Polling that ends on its own is not a reason
    to exit: on a home PC the line drops, so the bot simply connects again.
    """

    async def stop_polling_safely() -> None:
        # The monitor may fire a moment after polling has already ended.
        with contextlib.suppress(RuntimeError):
            await dispatcher.stop_polling()

    monitor = ConnectionMonitor(
        bot, transport, stop_polling_safely, switchable=switchable
    )
    try:
        monitor_task = asyncio.create_task(monitor.run())
        try:
            await dispatcher.start_polling(
                bot,
                allowed_updates=dispatcher.resolve_used_update_types(),
                handle_as_tasks=False,
                polling_timeout=POLLING_TIMEOUT,
                handle_signals=False,
                # Network hiccup: retry inside polling instead of restarting it.
                backoff_config=BackoffConfig(
                    min_delay=1.0, max_delay=30.0, factor=1.6, jitter=0.2
                ),
            )
        finally:
            monitor.stop()
            monitor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await monitor_task
        if stop_event is not None and stop_event.is_set():
            return False
        if monitor.exhausted:
            logger.info("Переключаю способ подключения к Telegram.")
            return True
        logger.warning(
            "Опрос Telegram завершился сам; подключаюсь заново, бот продолжает работу."
        )
        return True
    except TRANSPORT_ERRORS as exc:
        logger.warning(
            "Соединение прервано (%s): %s", transport.name, describe_error(exc)
        )
        return True
    except Exception:
        # Even an unexpected error must not end the bot: it reconnects and
        # keeps working.
        logger.exception("Неожиданная ошибка в опросе Telegram; переподключаюсь")
        return True
    finally:
        await bot.session.close()


async def report_connection_problem() -> None:
    """Write a network diagnosis into the journal.

    When no route answers at all, the cause is outside the computer, and saying
    so — with the addresses and the reason for each — is the only useful thing
    the bot can do. The check itself must never break the bot, so nothing here
    is allowed to raise.
    """

    with contextlib.suppress(Exception):
        report = await diagnose()
        for line in report.as_text().splitlines():
            if line:
                logger.warning("Диагностика сети: %s", line)


async def announce_second_reader(config: Config) -> None:
    """Say at start-up whether the paid-for second reader really answers.

    Run in the background: a model Google has retired must not hold up the
    connection to Telegram, and the bot reads photographs by itself either
    way. The point is only that the answer is visible — a second reader that
    silently stopped working is worse than none, because it looks like the
    bot still reads badly.
    """

    with contextlib.suppress(Exception):
        verdict = await startup_check(
            GeminiSettings(
                api_key=config.gemini_api_key,
                model=config.gemini_model,
                mode=config.gemini_mode,
                timeout=config.gemini_timeout,
                proxy=config.gemini_proxy,
            )
        )
        logger.info("Второй читатель: %s", verdict)


async def make_startup_snapshot(config: Config) -> None:
    """Create one fresh snapshot when the bot starts; failure is not fatal."""

    database_path = config.sqlite_path
    if database_path is None or not database_path.exists():
        return
    try:
        snapshot = await asyncio.to_thread(
            create_snapshot, database_path, config.backup_dir
        )
        await asyncio.to_thread(rotate_snapshots, config.backup_dir)
    except (BackupError, OSError, ValueError) as exc:
        logger.warning("Не удалось создать резервную копию при запуске: %s", exc)
        return
    logger.info(
        "Резервная копия при запуске: %s (%s байт)",
        snapshot.path.name,
        snapshot.size,
    )


async def archive_catchup_loop(archive: ArchiveService, stop: asyncio.Event) -> None:
    """Re-send cards that never reached the archive channel.

    A photograph is only safe once it is in the channel, and a card created
    while the line was down would otherwise stay unarchived forever. This loop
    quietly retries every half hour. It never raises: losing the archive is
    bad, losing the bot would be worse.
    """

    while True:
        try:
            await asyncio.wait_for(stop.wait(), timeout=ARCHIVE_RETRY_INTERVAL)
            return
        except TimeoutError:
            pass
        bot = archive.bot
        if bot is None or not archive.enabled:
            continue
        try:
            sent = await archive.mirror_pending(bot)
        except Exception:
            logger.exception("Не удалось догнать архив канала")
            continue
        if sent:
            logger.info("Архив: догружено карточек в канал: %s", sent)


async def tell_main_admins(bot: Any, config: Config, text: str) -> None:
    """Write to every main administrator; a blocked chat is not a reason to stop."""

    for admin_id in sorted(config.admin_user_ids):
        with contextlib.suppress(TelegramAPIError):
            await bot.send_message(admin_id, text)


async def catch_up_daily_dump(archive: ArchiveService, repository: Repository) -> None:
    """Send the daily dump that was missed while the bot was switched off.

    The scheduler only knows about the next 23:30, so a computer that is
    started in the morning would quietly skip the copy of the day before.
    The moment of the last successful dump is remembered inside the database,
    which makes the gap visible.
    """

    due = archive.digest_due_time(datetime.now(UTC))
    raw = await repository.get_state(LAST_DUMP_KEY)
    last: datetime | None = None
    if raw:
        try:
            last = datetime.fromisoformat(raw)
        except ValueError:
            last = None
    if last is not None and last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    if last is not None and last >= due:
        return
    bot = archive.bot
    if bot is None:
        return
    logger.info("Ежедневная выгрузка базы в канал пропущена, отправляю её сейчас.")
    try:
        await archive.send_daily_digest(bot, since=last)
    except Exception:
        logger.exception("Не удалось догнать ежедневную выгрузку базы")


async def run() -> None:
    config = Config.from_env()
    configure_logging(config.log_level)
    instance_lock = SingleInstanceLock(Path("data/bot.lock"))
    try:
        instance_lock.acquire()
    except SingleInstanceError:
        logger.error("VIN-бот уже запущен; второй экземпляр не будет запущен")
        raise

    if not config.allowed_user_ids:
        logger.warning(
            "ALLOWED_USER_IDS пуст: бот доступен любому пользователю Telegram, который его найдёт"
        )
    if not config.admin_user_ids:
        logger.warning(
            "ADMIN_USER_IDS пуст: назначать администраторов через Telegram некому"
        )

    # A database that will not open is healed from the newest snapshot before
    # anything touches it; the administrator hears about it once Telegram is
    # reachable, because a silent repair is worse than a visible one.
    recovery_note: str | None = None
    if config.sqlite_path is not None:
        recovery_note = await asyncio.to_thread(
            recover_database, config.sqlite_path, config.backup_dir
        )
        if recovery_note:
            logger.warning("База восстановлена из снимка: %s", recovery_note)

    engine, sessions = create_engine_and_session(config.database_url)
    await init_database(engine)
    repository = Repository(sessions)
    ocr = OCRService(config.tesseract_cmd)

    archive = ArchiveService(config, repository)
    await make_startup_snapshot(config)
    if archive.enabled:
        logger.info(
            "Архив включён: канал %s, ежедневная выгрузка в %s",
            config.archive_channel_id,
            config.archive_digest_time,
        )
    else:
        logger.info(
            "Архив в Telegram-канал отключён: укажите ARCHIVE_CHANNEL_ID в .env"
        )
    asyncio.create_task(announce_second_reader(config), name="second-reader-check")
    scheduler = DigestScheduler(config, archive)

    dispatcher = Dispatcher(storage=MemoryStorage())
    access_middleware = AccessMiddleware(config.allowed_user_ids, config.admin_user_ids)
    user_context_middleware = UserContextMiddleware(repository, config.admin_user_ids)
    dispatcher.message.outer_middleware(access_middleware)
    dispatcher.callback_query.outer_middleware(access_middleware)
    dispatcher.message.outer_middleware(user_context_middleware)
    dispatcher.callback_query.outer_middleware(user_context_middleware)
    dispatcher.include_router(build_router(config, repository, ocr, archive=archive))

    transports = await plan_routes(config)
    logger.info(
        "Способы подключения к Telegram: %s",
        ", ".join(transport.name for transport in transports),
    )
    if len(transports) > 1:
        logger.info(
            "Прокси используется только как запасной вариант: бот работает и без него."
        )

    archive_stop = asyncio.Event()
    catchup_task = asyncio.create_task(
        archive_catchup_loop(archive, archive_stop), name="archive-catchup"
    )

    offset = 0
    failures = 0
    try:
        while True:
            rotation = transports[offset:] + transports[:offset]
            connected = await connect_telegram(config, rotation)
            offset = (offset + 1) % len(transports)
            if connected is None:
                delay = RECONNECT_BACKOFF[min(failures, len(RECONNECT_BACKOFF) - 1)]
                failures += 1
                logger.warning(
                    "Telegram недоступен ни одним из %s способов. "
                    "Повторная попытка через %s сек.",
                    len(transports),
                    int(delay),
                )
                if failures == 1 or failures % DIAGNOSE_EVERY == 0:
                    await report_connection_problem()
                await asyncio.sleep(delay)
                continue
            failures = 0
            bot, transport = connected
            archive.attach(bot)
            scheduler.start()
            if recovery_note is not None:
                await tell_main_admins(bot, config, recovery_note)
                recovery_note = None
            if archive.enabled:
                # Say out loud what is wrong with the channel: a silent archive
                # is worse than a broken one.
                with contextlib.suppress(Exception):
                    healthy, report = await archive.probe(bot)
                    logger.info("Проверка канала-архива: %s", report)
                    if not healthy:
                        await archive.notify_failure(
                            bot,
                            "⚠️ Архив в Telegram-канал не работает:\n" + report,
                        )
                # Anything created while the bot was offline still has to reach
                # the channel, so the missing copies are sent right away.
                with contextlib.suppress(Exception):
                    sent = await archive.mirror_pending(bot)
                    if sent:
                        logger.info(
                            "Догнали архив: отправлено карточек в канал: %s", sent
                        )
                # A night with the computer off must not cost a day of copies.
                with contextlib.suppress(Exception):
                    await catch_up_daily_dump(archive, repository)
            should_switch = await poll_with_transport(
                dispatcher,
                bot,
                transport,
                switchable=len(transports) > 1,
            )
            if not should_switch:
                return
            await asyncio.sleep(RECONNECT_DELAY)
    finally:
        archive_stop.set()
        catchup_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await catchup_task
        scheduler.stop()
        await engine.dispose()
        instance_lock.release()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except SingleInstanceError as exc:
        if sys.stdout is not None:
            print(f"ОШИБКА: {exc}")
        raise SystemExit(2) from exc
    except TelegramNetworkError as exc:
        logger.error("Telegram недоступен: %s", exc)
        raise SystemExit(3) from exc
    except TelegramAPIError as exc:
        # Another transport cannot fix this: the token or the bot is wrong.
        logger.error("Telegram отклонил бота: %s. Проверьте BOT_TOKEN в .env.", exc)
        raise SystemExit(4) from exc
    except KeyboardInterrupt:
        logger.info("VIN-бот остановлен")
