"""Permanent archive of every photograph and of the database inside a channel.

Each new card is mirrored into a Telegram channel at once, so a photograph is
safe the second it is uploaded. Once a day the service posts a short summary and
the compressed database dump into the same channel. Every failure is logged and
swallowed: the archive is a safety net and must never block the workflow.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from datetime import UTC, datetime, timedelta

from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile, InputMediaPhoto
from sqlalchemy.exc import SQLAlchemyError

from app.backup_service import (
    create_snapshot,
    format_size,
    rotate_snapshots,
    split_for_telegram,
)
from app.config import Config
from app.database import PaintCard, VehicleCard
from app.repository import DailyDigest, Repository

logger = logging.getLogger(__name__)

ARCHIVE_KIND_CARD = "card"
LAST_DUMP_KEY = "last_archive_dump"
ARCHIVE_KIND_PAINT = "paint"


def card_owner_name(card: VehicleCard | PaintCard) -> str:
    """Owner name stored on the card; it survives the removal of the user."""

    return (getattr(card, "owner_name", "") or "").strip()


# The archive is a safety net: these problems are logged, never raised.
ARCHIVE_ERRORS = (TelegramAPIError, OSError, SQLAlchemyError, ValueError, RuntimeError)


class ArchiveService:
    """Mirror cards into a channel and publish the daily database dump."""

    #: Minimum gap between two failure notices sent to the main administrator.
    WARNING_COOLDOWN = 600.0

    def __init__(self, config: Config, repository: Repository) -> None:
        self.config = config
        self.repository = repository
        self._bot = None
        self._last_warning = 0.0

    @property
    def enabled(self) -> bool:
        return self.config.archive_enabled

    @property
    def bot(self):
        """The bot instance attached by :meth:`attach`, if any."""

        return self._bot

    def attach(self, bot) -> None:
        """Remember the live bot instance used for scheduled messages."""

        self._bot = bot

    # --------------------------------------------------------------- health

    async def probe(self, bot) -> tuple[bool, str]:
        """Check the channel and report, in Russian, what exactly is wrong.

        A silent archive is worse than a broken one, so this is the answer an
        administrator gets when the photographs do not arrive: no channel
        configured, channel not visible, or the bot has no right to post.
        """

        if not self.enabled:
            return False, (
                "⛔ Архив отключён: в .env не указан ARCHIVE_CHANNEL_ID.\n"
                "Добавьте строку ARCHIVE_CHANNEL_ID=@allnewclear и перезапустите бота."
            )
        channel = self.config.archive_channel_id
        try:
            chat = await bot.get_chat(channel)
        except ARCHIVE_ERRORS as exc:
            return False, (
                f"⛔ Бот не видит канал {channel}.\n"
                f"Ошибка Telegram: {exc}\n\n"
                f"Проверьте, что канал существует и бот добавлен в него "
                f"администратором с правом публикации сообщений."
            )
        title = (
            getattr(chat, "title", None)
            or getattr(chat, "username", None)
            or str(channel)
        )
        try:
            member = await bot.get_chat_member(channel, bot.id)
        except ARCHIVE_ERRORS as exc:
            return False, (
                f"⛔ Канал «{title}» найден, но бота в нём нет.\n"
                f"Ошибка Telegram: {exc}\n\n"
                f"Откройте канал → Управление → Администраторы → "
                f"Добавить администратора → выберите бота."
            )
        status = str(getattr(member, "status", "") or "?")
        if status in {"left", "kicked"}:
            return False, (
                f"⛔ Бот не состоит в канале «{title}» (статус: {status}).\n"
                f"Добавьте бота в канал администратором."
            )
        if status not in {"creator", "administrator"}:
            return False, (
                f"⛔ Бот есть в канале «{title}», но не может писать "
                f"(статус: {status}).\n"
                f"В канале публиковать сообщения могут только администраторы: "
                f"выдайте боту права администратора."
            )
        can_post = getattr(member, "can_post_messages", None)
        if can_post is False:
            return False, (
                f"⛔ У бота нет права «Публикация сообщений» в канале «{title}»."
            )
        return True, (
            f"✅ Канал «{title}» доступен, бот может публиковать сообщения.\n"
            f"🆔 <code>{chat.id}</code> — этот номер нужен в .env, если канал сделать приватным."
        )

    async def notify_failure(self, bot, text: str) -> None:
        """Send a failure notice to every main administrator, at most once an hour."""

        now = time.monotonic()
        if now - self._last_warning < self.WARNING_COOLDOWN:
            return
        self._last_warning = now
        for admin_id in sorted(self.config.admin_user_ids):
            with contextlib.suppress(Exception):
                await bot.send_message(admin_id, text)

    # ------------------------------------------------------------- mirroring

    def _caption(
        self,
        *,
        card_id: int,
        vin_text: str,
        owner: str,
        kind: str,
        moment: datetime,
    ) -> str:
        local = moment.astimezone(self.config.timezone)
        stamp = local.strftime("%d.%m.%Y %H:%M")
        russian = self.config.archive_language != "de"
        title = (
            f"🚗 Карточка №{card_id}"
            if kind == ARCHIVE_KIND_CARD
            else f"🎨 Покраска №{card_id}"
        )
        if not russian:
            title = (
                f"🚗 Karteikarte Nr.{card_id}"
                if kind == ARCHIVE_KIND_CARD
                else f"🎨 Lackierung Nr.{card_id}"
            )
        who = f"👤 {owner}" if owner else ""
        lines = [f"<b>{title}</b>", f"🔑 VIN: <code>{vin_text}</code>", f"🕓 {stamp}"]
        if who:
            lines.append(who)
        return "\n".join(lines)

    @staticmethod
    def _vin_text(card: VehicleCard | PaintCard) -> str:
        return (card.vin_full or "").strip() or f"…{card.vin_suffix6}"

    async def _send_card_copy(
        self,
        bot,
        channel: str,
        card: VehicleCard | PaintCard,
        caption: str,
    ) -> int | None:
        """Post the card and return the id of the first message that arrived.

        Three attempts, each weaker but more reliable than the previous one:
        all photographs as one album, then every photograph on its own, and
        finally the VIN as plain text. A card whose picture cannot be sent
        still leaves its VIN in the channel, because that is what makes the
        vehicle findable later.
        """

        photos = [card.vehicle_photo_file_id]
        invoice = getattr(card, "invoice_photo_file_id", None)
        if invoice and self.config.archive_include_invoice:
            photos.append(invoice)
        photos.append(card.vin_photo_file_id)
        photos = [file_id for file_id in photos if file_id]

        if photos:
            try:
                media = [InputMediaPhoto(media=photos[0], caption=caption)]
                media += [InputMediaPhoto(media=file_id) for file_id in photos[1:]]
                sent = await bot.send_media_group(channel, media)
                if isinstance(sent, list) and sent:
                    return sent[0].message_id
            except Exception:
                logger.exception(
                    "Карточка №%s: альбом в канал не отправился, "
                    "пробую по одному фото.",
                    card.id,
                )

        first_message_id: int | None = None
        for index, file_id in enumerate(photos):
            try:
                message = await bot.send_photo(
                    channel,
                    file_id,
                    caption=caption if first_message_id is None else None,
                )
            except Exception:
                logger.exception(
                    "Карточка №%s: фото %s не отправилось.", card.id, index + 1
                )
                continue
            if first_message_id is None:
                first_message_id = message.message_id
        if first_message_id is not None:
            return first_message_id

        try:
            message = await bot.send_message(channel, caption)
        except Exception:
            logger.exception(
                "Карточка №%s: не удалось отправить в канал даже текст", card.id
            )
            return None
        return message.message_id

    async def mirror_card(
        self,
        bot,
        card: VehicleCard | PaintCard,
        *,
        kind: str,
        owner: str = "",
    ) -> int | None:
        """Post the photographs of a fresh card into the archive channel."""

        if not self.enabled or not self.config.archive_immediate:
            return None
        channel = self.config.archive_channel_id
        caption = self._caption(
            card_id=card.id,
            vin_text=self._vin_text(card),
            owner=owner,
            kind=kind,
            moment=card.created_at or datetime.now(UTC),
        )
        message_id = await self._send_card_copy(bot, channel, card, caption)
        if message_id is None:
            logger.error(
                "Карточка №%s НЕ попала в канал %s. Она останется в списке "
                "недошедших и бот отправит её позже автоматически.",
                card.id,
                channel,
            )
            await self.notify_failure(
                bot,
                "⚠️ Архив: карточку №"
                f"{card.id} не удалось отправить в канал {channel}.\n"
                "Бот повторит отправку автоматически через полчаса; можно "
                "нажать «Отправить пропущенное» в разделе «Канал-архив».",
            )
            return None

        try:
            if kind == ARCHIVE_KIND_PAINT:
                await self.repository.set_paint_archive_message_id(card.id, message_id)
            else:
                await self.repository.set_archive_message_id(card.id, message_id)
        except ARCHIVE_ERRORS as exc:
            logger.warning("Не удалось сохранить ссылку на архив: %s", exc)
        logger.info("Карточка №%s отправлена в канал-архив %s", card.id, channel)
        return message_id

    async def mirror_pending(self, bot, *, limit: int = 5, since_days: int = 7) -> int:
        """Send everything that is still missing from the channel.

        A card is mirrored the moment it is created, but a photograph taken
        while the line was down would otherwise never reach the channel. This is
        what makes the archive reliable: whatever is missing is simply sent
        again — after every restart and then every half hour.
        """

        if not self.enabled or bot is None:
            return 0
        since = datetime.now(UTC) - timedelta(days=max(since_days, 1))
        try:
            cards = await self.repository.list_cards_without_archive(
                since=since, limit=limit
            )
            paints = await self.repository.list_paint_cards_without_archive(
                since=since, limit=limit
            )
        except ARCHIVE_ERRORS as exc:
            logger.warning("Не удалось получить список недошедших карточек: %s", exc)
            return 0
        sent = 0
        for card in cards:
            if await self.mirror_card(
                bot, card, kind=ARCHIVE_KIND_CARD, owner=card_owner_name(card)
            ):
                sent += 1
        for card in paints:
            if await self.mirror_card(
                bot, card, kind=ARCHIVE_KIND_PAINT, owner=card_owner_name(card)
            ):
                sent += 1
        return sent

    async def note_deletion(self, bot, card: VehicleCard, actor: str) -> None:
        """Record a deletion in the channel so it can always be traced."""

        if not self.enabled:
            return
        local = datetime.now(UTC).astimezone(self.config.timezone)
        stamp = local.strftime("%d.%m.%Y %H:%M")
        vin_text = self._vin_text(card)
        if self.config.archive_language == "de":
            text = (
                f"🗑 <b>Karteikarte Nr.{card.id} gelöscht</b>\n"
                f"🔑 VIN: <code>{vin_text}</code>\n"
                f"👤 {actor}\n"
                f"🕓 {stamp}"
            )
        else:
            text = (
                f"🗑 <b>Карточка №{card.id} удалена</b>\n"
                f"🔑 VIN: <code>{vin_text}</code>\n"
                f"👤 {actor}\n"
                f"🕓 {stamp}"
            )
        try:
            await bot.send_message(
                self.config.archive_channel_id, text, disable_notification=True
            )
        except ARCHIVE_ERRORS as exc:
            logger.warning("Не удалось записать удаление в канал: %s", exc)

    # ---------------------------------------------------------------- digest

    def digest_text(self, digest: DailyDigest, *, size: int, day: datetime) -> str:
        local_day = day.astimezone(self.config.timezone).strftime("%d.%m.%Y")
        russian = self.config.archive_language != "de"
        if russian:
            return (
                f"📦 <b>АРХИВ ЗА {local_day}</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"➕ Добавлено карточек: <b>{digest.created}</b>\n"
                f"🎨 Сдано в покраску: <b>{digest.paint_created}</b>\n"
                f"🗑 Удалено: <b>{digest.deleted}</b>\n\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🗂 Активных карточек: <b>{digest.active}</b>\n"
                f"🎨 В покраске: <b>{digest.paint_active}</b>\n"
                f"💾 Размер базы: <b>{format_size(size)}</b>\n\n"
                f"Файл базы данных — ниже."
            )
        return (
            f"📦 <b>ARCHIV VOM {local_day}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"➕ Neue Karteikarten: <b>{digest.created}</b>\n"
            f"🎨 In Lackierung: <b>{digest.paint_created}</b>\n"
            f"🗑 Gelöscht: <b>{digest.deleted}</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🗂 Aktive Karteikarten: <b>{digest.active}</b>\n"
            f"🎨 In Arbeit: <b>{digest.paint_active}</b>\n"
            f"💾 Datenbank: <b>{format_size(size)}</b>\n\n"
            f"Die Datenbankdatei folgt unten."
        )

    def digest_due_time(self, now: datetime, *, upcoming: bool = False) -> datetime:
        """The moment the daily dump is scheduled for.

        ``upcoming`` asks for the next one in the future; without it the most
        recent one in the past is returned — that is the dump the bot owes when
        it was switched off at the time it should have been sent.
        """

        hours, minutes = (
            int(part) for part in self.config.archive_digest_time.split(":")
        )
        local = now.astimezone(self.config.timezone)
        target = local.replace(hour=hours, minute=minutes, second=0, microsecond=0)
        if upcoming and target <= local:
            target += timedelta(days=1)
        if not upcoming and target > local:
            target -= timedelta(days=1)
        return target

    async def send_daily_digest(self, bot, *, since: datetime | None = None) -> bool:
        """Post the daily summary and the database dump into the channel."""

        if not self.enabled:
            return False
        moment = datetime.now(UTC)
        start = since or (moment - timedelta(hours=24))
        try:
            digest = await self.repository.daily_digest(start)
        except ARCHIVE_ERRORS as exc:
            logger.warning("Не удалось собрать сводку для архива: %s", exc)
            return False
        database_path = self.config.sqlite_path
        if database_path is None:
            logger.warning("Архив работает только с SQLite: дамп пропущен")
            return False
        try:
            snapshot = await asyncio.to_thread(
                create_snapshot,
                database_path,
                self.config.backup_dir,
            )
            await asyncio.to_thread(rotate_snapshots, self.config.backup_dir)
        except ARCHIVE_ERRORS as exc:
            logger.warning("Не удалось создать резервную копию для архива: %s", exc)
            return False

        try:
            await bot.send_message(
                self.config.archive_channel_id,
                self.digest_text(digest, size=snapshot.size, day=moment),
            )
            data = snapshot.path.read_bytes()
            parts = split_for_telegram(data)
            name = snapshot.path.name
            for index, part in enumerate(parts, start=1):
                suffix = f".part{index}" if len(parts) > 1 else ""
                await bot.send_document(
                    self.config.archive_channel_id,
                    BufferedInputFile(part, filename=f"{name}{suffix}"),
                    caption=(
                        f"💾 {name}{suffix} · {format_size(len(part))}"
                        if len(parts) > 1
                        else f"💾 Резервная копия базы · {format_size(len(part))}"
                    ),
                )
            await self.repository.set_state(LAST_DUMP_KEY, moment.isoformat())
        except ARCHIVE_ERRORS as exc:
            logger.warning("Не удалось отправить сводку в канал: %s", exc)
            await self.notify_failure(
                bot,
                "⚠️ Архив: ежедневная выгрузка базы в канал не удалась.\n"
                f"Причина: {exc}",
            )
            return False
        return True


class DigestScheduler:
    """Fire :meth:`ArchiveService.send_daily_digest` once per local day."""

    def __init__(self, config: Config, archive: ArchiveService) -> None:
        self.config = config
        self.archive = archive
        self._task: asyncio.Task | None = None

    def _seconds_until_next_digest(self, now: datetime) -> float:
        target = self.archive.digest_due_time(now, upcoming=True)
        local = now.astimezone(self.config.timezone)
        return max(1.0, (target - local).total_seconds())

    async def _loop(self) -> None:
        while True:
            delay = self._seconds_until_next_digest(datetime.now(UTC))
            logger.info(
                "Суточная выгрузка базы запланирована через %.0f мин.", delay / 60.0
            )
            await asyncio.sleep(delay)
            bot = self.archive._bot
            if bot is None:
                continue
            try:
                await self.archive.send_daily_digest(bot)
            except ARCHIVE_ERRORS as exc:
                logger.warning("Ошибка суточной выгрузки: %s", exc)
            # Never fire twice within the same minute.
            await asyncio.sleep(90)

    def start(self) -> None:
        if not self.archive.enabled or self._task is not None:
            return
        self._task = asyncio.create_task(self._loop(), name="archive-digest")

    def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        self._task = None
