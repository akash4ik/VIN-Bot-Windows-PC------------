from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database import (
    AuditLog,
    BotState,
    PaintCard,
    PaintStatus,
    User,
    VehicleCard,
)
from app.ocr import is_valid_vin, is_valid_vin_fragment
from app.roles import STORED_ROLES, Role, normalize_stored_role


@dataclass(frozen=True, slots=True)
class DailyDigest:
    """Counters for the daily archive summary."""

    created: int
    deleted: int
    paint_created: int
    active: int
    paint_active: int


@dataclass(frozen=True, slots=True)
class AdminStats:
    users: int
    main_admins: int
    admins: int
    workers: int
    drivers: int
    active_cards: int
    deleted_cards: int
    total_cards: int
    paint_in_progress: int
    paint_completed: int


def normalize_paint_status(value: str | PaintStatus | None) -> PaintStatus:
    """Return a safe paint status; unknown values are treated as in progress."""

    try:
        return PaintStatus(value or PaintStatus.IN_PROGRESS)
    except ValueError:
        return PaintStatus.IN_PROGRESS


def _search_needle(value: str) -> str:
    """Fold a search term: lower case, no spaces, no punctuation."""

    return "".join(character for character in value.casefold() if character.isalnum())


def _card_haystack(card: VehicleCard) -> str:
    """Everything a trash search may match against."""

    return " ".join(
        part
        for part in (card.vin_full or "", card.vin_suffix6, card.owner_name or "")
        if part
    )


def display_name_of(user: User | None) -> str:
    """Name shown for a user: an administrator-assigned name wins."""

    if user is None:
        return ""
    return (user.display_name or user.full_name or "").strip() or str(user.telegram_id)


class Repository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def touch_user(
        self,
        telegram_id: int,
        full_name: str,
        username: str | None,
    ) -> User:
        async with self.sessions() as session:
            user = await session.get(User, telegram_id)
            safe_name = (full_name or "").strip()[:255]
            safe_username = (username or "").strip()[:64] or None
            if user is None:
                user = User(
                    telegram_id=telegram_id,
                    full_name=safe_name,
                    username=safe_username,
                    role=Role.DRIVER.value,
                    legacy_is_admin=False,
                )
                session.add(user)
            else:
                user.full_name = safe_name
                user.username = safe_username
                normalized_role = normalize_stored_role(user.role)
                user.role = normalized_role.value
                user.legacy_is_admin = normalized_role is Role.ADMIN
                user.updated_at = datetime.now(UTC)
            await session.commit()
            return user

    async def set_language(self, telegram_id: int, language: str) -> None:
        async with self.sessions() as session:
            user = await session.get(User, telegram_id)
            if user is None:
                user = User(
                    telegram_id=telegram_id,
                    full_name="",
                    language=language,
                    role=Role.DRIVER.value,
                    legacy_is_admin=False,
                )
                session.add(user)
            else:
                user.language = language
                user.updated_at = datetime.now(UTC)
            await session.commit()

    async def get_user(self, telegram_id: int) -> User | None:
        async with self.sessions() as session:
            return await session.get(User, telegram_id)

    async def list_users(self, *, offset: int, limit: int) -> tuple[list[User], int]:
        async with self.sessions() as session:
            total = int(
                (await session.scalar(select(func.count(User.telegram_id)))) or 0
            )
            statement = (
                select(User)
                .order_by(User.created_at.desc(), User.telegram_id.desc())
                .offset(max(offset, 0))
                .limit(max(limit, 1))
            )
            users = list((await session.scalars(statement)).all())
            return users, total

    async def count_user_cards(self, telegram_id: int) -> tuple[int, int]:
        """Return (vehicle cards, paint cards) still owned by this user."""

        async with self.sessions() as session:
            vehicles = int(
                (
                    await session.scalar(
                        select(func.count(VehicleCard.id)).where(
                            and_(
                                VehicleCard.owner_id == telegram_id,
                                VehicleCard.is_deleted.is_(False),
                            )
                        )
                    )
                )
                or 0
            )
            paints = int(
                (
                    await session.scalar(
                        select(func.count(PaintCard.id)).where(
                            PaintCard.owner_id == telegram_id
                        )
                    )
                )
                or 0
            )
            return vehicles, paints

    async def delete_user(self, telegram_id: int) -> bool:
        """Remove a user row; the cards they created are kept.

        Every card stores the owner name next to the owner id, so deleting an
        employee leaves the vehicle history completely intact.
        """

        async with self.sessions() as session:
            user = await session.get(User, telegram_id)
            if user is None:
                return False
            await session.delete(user)
            await session.commit()
            return True

    async def list_cards_without_archive(
        self, *, since: datetime, limit: int = 5
    ) -> list[VehicleCard]:
        """Active cards that never reached the archive channel."""

        async with self.sessions() as session:
            statement = (
                select(VehicleCard)
                .where(
                    VehicleCard.is_deleted.is_(False),
                    VehicleCard.archive_message_id.is_(None),
                    VehicleCard.created_at >= since,
                )
                .order_by(VehicleCard.created_at.asc())
                .limit(max(limit, 1))
            )
            return list((await session.scalars(statement)).all())

    async def list_paint_cards_without_archive(
        self, *, since: datetime, limit: int = 5
    ) -> list[PaintCard]:
        """Painting cards that never reached the archive channel."""

        async with self.sessions() as session:
            statement = (
                select(PaintCard)
                .where(
                    PaintCard.archive_message_id.is_(None),
                    PaintCard.created_at >= since,
                )
                .order_by(PaintCard.created_at.asc())
                .limit(max(limit, 1))
            )
            return list((await session.scalars(statement)).all())

    async def get_dynamic_admin_ids(self) -> frozenset[int]:
        async with self.sessions() as session:
            statement = select(User.telegram_id).where(User.role == Role.ADMIN.value)
            return frozenset((await session.scalars(statement)).all())

    async def set_display_name(
        self, telegram_id: int, display_name: str | None
    ) -> User | None:
        """Assign or clear the name an administrator gave to this user."""

        cleaned = (display_name or "").strip()
        async with self.sessions() as session:
            user = await session.get(User, telegram_id)
            if user is None:
                return None
            user.display_name = cleaned[:64] or None
            user.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(user)
            return user

    async def set_role(self, telegram_id: int, role: str | Role) -> User | None:
        try:
            normalized_role = Role(role)
        except ValueError as exc:
            raise ValueError("Недопустимая роль пользователя") from exc
        if normalized_role not in STORED_ROLES:
            raise ValueError("Недопустимая роль пользователя")
        async with self.sessions() as session:
            user = await session.get(User, telegram_id)
            if user is None:
                return None
            user.role = normalized_role.value
            user.legacy_is_admin = normalized_role is Role.ADMIN
            user.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(user)
            return user

    async def get_admin_stats(
        self, super_admin_ids: frozenset[int] = frozenset()
    ) -> AdminStats:
        async with self.sessions() as session:
            users = int(
                (await session.scalar(select(func.count(User.telegram_id)))) or 0
            )
            configured_main_admins = len(super_admin_ids)

            async def count_role(role: Role) -> int:
                conditions = [User.role == role.value]
                if super_admin_ids:
                    conditions.append(User.telegram_id.not_in(super_admin_ids))
                return int(
                    (
                        await session.scalar(
                            select(func.count(User.telegram_id)).where(*conditions)
                        )
                    )
                    or 0
                )

            admins = await count_role(Role.ADMIN)
            workers = await count_role(Role.WORKER)
            drivers = await count_role(Role.DRIVER)
            active_cards = int(
                (
                    await session.scalar(
                        select(func.count(VehicleCard.id)).where(
                            VehicleCard.is_deleted.is_(False)
                        )
                    )
                )
                or 0
            )
            deleted_cards = int(
                (
                    await session.scalar(
                        select(func.count(VehicleCard.id)).where(
                            VehicleCard.is_deleted.is_(True)
                        )
                    )
                )
                or 0
            )
            paint_in_progress = int(
                (
                    await session.scalar(
                        select(func.count(PaintCard.id)).where(
                            PaintCard.status == PaintStatus.IN_PROGRESS.value
                        )
                    )
                )
                or 0
            )
            paint_completed = int(
                (
                    await session.scalar(
                        select(func.count(PaintCard.id)).where(
                            PaintCard.status == PaintStatus.DONE.value
                        )
                    )
                )
                or 0
            )
            return AdminStats(
                users=users,
                main_admins=configured_main_admins,
                admins=admins,
                workers=workers,
                drivers=drivers,
                active_cards=active_cards,
                deleted_cards=deleted_cards,
                total_cards=active_cards + deleted_cards,
                paint_in_progress=paint_in_progress,
                paint_completed=paint_completed,
            )

    # ------------------------------------------------------------------ paint

    async def create_paint_card(
        self,
        *,
        owner_id: int,
        owner_name: str,
        vehicle_photo_file_id: str,
        vin_photo_file_id: str,
        vin_full: str | None,
        vin_suffix6: str,
        ocr_confidence: float | None,
    ) -> PaintCard:
        if owner_id <= 0:
            raise ValueError("Некорректный Telegram ID владельца")
        vehicle_photo = (vehicle_photo_file_id or "").strip()
        vin_photo = (vin_photo_file_id or "").strip()
        if not vehicle_photo or not vin_photo:
            raise ValueError("Для покраски нужны две фотографии")
        if vehicle_photo == vin_photo:
            raise ValueError("Для покраски нужны две разные фотографии")
        if not is_valid_vin_fragment(vin_suffix6, {6}):
            raise ValueError("Некорректные последние 6 символов VIN")
        if vin_full is not None and (
            not is_valid_vin(vin_full) or not vin_full.endswith(vin_suffix6)
        ):
            raise ValueError("Полный VIN не соответствует последним 6 символам")
        if ocr_confidence is not None and not 0 <= ocr_confidence <= 100:
            raise ValueError("Некорректная уверенность OCR")

        async with self.sessions() as session:
            card = PaintCard(
                owner_id=owner_id,
                owner_name=(owner_name or "").strip()[:255],
                vehicle_photo_file_id=vehicle_photo,
                vin_photo_file_id=vin_photo,
                vin_full=vin_full,
                vin_suffix6=vin_suffix6,
                ocr_confidence=ocr_confidence,
                status=PaintStatus.IN_PROGRESS.value,
            )
            session.add(card)
            await session.commit()
            await session.refresh(card)
            return card

    async def get_paint_card(self, card_id: int) -> PaintCard | None:
        async with self.sessions() as session:
            card = await session.get(PaintCard, card_id)
            if card is not None:
                card.status = normalize_paint_status(card.status).value
            return card

    async def find_active_paint_by_full_vin(self, vin_full: str) -> PaintCard | None:
        async with self.sessions() as session:
            statement = select(PaintCard).where(
                PaintCard.vin_full == vin_full,
                PaintCard.status == PaintStatus.IN_PROGRESS.value,
            )
            return await session.scalar(statement)

    def _paint_conditions(
        self, *, status: str | PaintStatus | None, query: str | None
    ) -> list:
        conditions = []
        if status is not None:
            conditions.append(PaintCard.status == normalize_paint_status(status).value)
        if query:
            conditions.append(PaintCard.vin_suffix6.endswith(query))
        return conditions

    async def get_paint_page(
        self,
        *,
        status: str | PaintStatus | None,
        query: str | None,
        offset: int,
    ) -> tuple[PaintCard | None, int]:
        conditions = self._paint_conditions(status=status, query=query)
        async with self.sessions() as session:
            total_statement = select(func.count(PaintCard.id)).where(*conditions)
            total = int((await session.scalar(total_statement)) or 0)
            if total == 0:
                return None, 0
            safe_offset = min(max(offset, 0), total - 1)
            item_statement = (
                select(PaintCard)
                .where(*conditions)
                .order_by(PaintCard.created_at.desc(), PaintCard.id.desc())
                .offset(safe_offset)
                .limit(1)
            )
            card = await session.scalar(item_statement)
            return card, total

    async def get_paint_card_position(
        self,
        card_id: int,
        *,
        status: str | PaintStatus | None,
        query: str | None,
    ) -> tuple[PaintCard | None, int, int]:
        """Return a paint card together with its current zero-based position."""

        async with self.sessions() as session:
            card = await session.get(PaintCard, card_id)
            if card is None:
                return None, 0, 0
            card.status = normalize_paint_status(card.status).value
            if status is not None and card.status != normalize_paint_status(status):
                return None, 0, 0
            if query and not card.vin_suffix6.endswith(query):
                return None, 0, 0

            conditions = self._paint_conditions(status=status, query=query)
            total_statement = select(func.count(PaintCard.id)).where(*conditions)
            total = int((await session.scalar(total_statement)) or 0)
            before_statement = select(func.count(PaintCard.id)).where(
                *conditions,
                or_(
                    PaintCard.created_at > card.created_at,
                    and_(
                        PaintCard.created_at == card.created_at,
                        PaintCard.id > card.id,
                    ),
                ),
            )
            offset = int((await session.scalar(before_statement)) or 0)
            return card, offset, total

    async def complete_paint_card(
        self,
        card_id: int,
        completed_by: int,
        completed_by_name: str = "",
    ) -> bool:
        """Move a painting card into the “picked up” catalogue."""

        async with self.sessions() as session:
            card = await session.get(PaintCard, card_id)
            if card is None:
                return False
            if normalize_paint_status(card.status) is PaintStatus.DONE:
                return False
            card.status = PaintStatus.DONE.value
            card.completed_at = datetime.now(UTC)
            card.completed_by = completed_by
            card.completed_by_name = (completed_by_name or "").strip()[:255]
            await session.commit()
            return True

    async def create_card(
        self,
        *,
        owner_id: int,
        owner_name: str,
        vehicle_photo_file_id: str,
        vin_photo_file_id: str,
        vin_full: str | None,
        vin_suffix6: str,
        ocr_confidence: float | None,
        invoice_photo_file_id: str | None = None,
    ) -> VehicleCard:
        photo_ids = (
            vehicle_photo_file_id,
            invoice_photo_file_id,
            vin_photo_file_id,
        )
        if owner_id <= 0:
            raise ValueError("Некорректный Telegram ID владельца")
        if any(not value or not value.strip() for value in photo_ids):
            raise ValueError("Все три фотографии обязательны")
        # The invoice and the VIN photograph are allowed to be one and the
        # same picture: he asked to be able to send the invoice as the VIN,
        # and the engine finds the code by its shape anywhere on the page.
        # What must not happen is the car standing in for its own paperwork.
        if vehicle_photo_file_id in (invoice_photo_file_id, vin_photo_file_id):
            raise ValueError("Фотография автомобиля не может быть документом")
        if not is_valid_vin_fragment(vin_suffix6, {6}):
            raise ValueError("Некорректные последние 6 символов VIN")
        if vin_full is not None and (
            not is_valid_vin(vin_full) or not vin_full.endswith(vin_suffix6)
        ):
            raise ValueError("Полный VIN не соответствует последним 6 символам")
        if ocr_confidence is not None and not 0 <= ocr_confidence <= 100:
            raise ValueError("Некорректная уверенность OCR")

        async with self.sessions() as session:
            card = VehicleCard(
                owner_id=owner_id,
                owner_name=(owner_name or "").strip()[:255],
                vehicle_photo_file_id=vehicle_photo_file_id.strip(),
                invoice_photo_file_id=invoice_photo_file_id.strip(),
                vin_photo_file_id=vin_photo_file_id.strip(),
                vin_full=vin_full,
                vin_suffix6=vin_suffix6,
                ocr_confidence=ocr_confidence,
            )
            session.add(card)
            await session.commit()
            await session.refresh(card)
            return card

    async def find_active_by_full_vin(self, vin_full: str) -> VehicleCard | None:
        async with self.sessions() as session:
            statement = select(VehicleCard).where(
                VehicleCard.vin_full == vin_full,
                VehicleCard.is_deleted.is_(False),
            )
            return await session.scalar(statement)

    async def get_card(self, card_id: int) -> VehicleCard | None:
        async with self.sessions() as session:
            return await session.get(VehicleCard, card_id)

    async def get_page(
        self,
        *,
        query: str | None,
        offset: int,
    ) -> tuple[VehicleCard | None, int]:
        conditions = [VehicleCard.is_deleted.is_(False)]
        if query:
            conditions.append(VehicleCard.vin_suffix6.endswith(query))

        async with self.sessions() as session:
            total_statement = select(func.count(VehicleCard.id)).where(*conditions)
            total = int((await session.scalar(total_statement)) or 0)
            if total == 0:
                return None, 0
            safe_offset = min(max(offset, 0), total - 1)
            item_statement = (
                select(VehicleCard)
                .where(*conditions)
                .order_by(VehicleCard.created_at.desc(), VehicleCard.id.desc())
                .offset(safe_offset)
                .limit(1)
            )
            card = await session.scalar(item_statement)
            return card, total

    async def get_card_position(
        self,
        card_id: int,
        *,
        query: str | None,
    ) -> tuple[VehicleCard | None, int, int]:
        """Return an active card together with its current zero-based list position."""
        async with self.sessions() as session:
            card = await session.get(VehicleCard, card_id)
            if card is None or card.is_deleted:
                return None, 0, 0
            if query and not card.vin_suffix6.endswith(query):
                return None, 0, 0

            conditions = [VehicleCard.is_deleted.is_(False)]
            if query:
                conditions.append(VehicleCard.vin_suffix6.endswith(query))

            total_statement = select(func.count(VehicleCard.id)).where(*conditions)
            total = int((await session.scalar(total_statement)) or 0)
            before_statement = select(func.count(VehicleCard.id)).where(
                *conditions,
                or_(
                    VehicleCard.created_at > card.created_at,
                    and_(
                        VehicleCard.created_at == card.created_at,
                        VehicleCard.id > card.id,
                    ),
                ),
            )
            offset = int((await session.scalar(before_statement)) or 0)
            return card, offset, total

    async def soft_delete_card(self, card_id: int, deleted_by: int) -> bool:
        async with self.sessions() as session:
            card = await session.get(VehicleCard, card_id)
            if card is None or card.is_deleted:
                return False
            card.is_deleted = True
            card.deleted_at = datetime.now(UTC)
            card.deleted_by = deleted_by
            await session.commit()
            return True

    # ------------------------------------------------------------ audit log

    async def add_audit(
        self,
        *,
        actor_id: int,
        actor_name: str,
        action: str,
        details: str = "",
    ) -> None:
        """Append one record to the journal; failures never break the flow."""

        async with self.sessions() as session:
            session.add(
                AuditLog(
                    actor_id=actor_id,
                    actor_name=(actor_name or "").strip()[:255],
                    action=action,
                    details=(details or "")[:2000],
                )
            )
            await session.commit()

    async def list_audit(self, limit: int = 20) -> list[AuditLog]:
        async with self.sessions() as session:
            rows = await session.scalars(
                select(AuditLog)
                .order_by(AuditLog.id.desc())
                .limit(max(1, min(int(limit), 100)))
            )
            return list(rows)

    # ------------------------------------------------------------- bot state

    async def get_state(self, key: str) -> str | None:
        """Read a remembered value, or None when it was never written."""

        async with self.sessions() as session:
            row = await session.get(BotState, key)
            return None if row is None else row.value

    async def set_state(self, key: str, value: str) -> None:
        """Remember a value; writing twice simply replaces the old one."""

        async with self.sessions() as session:
            row = await session.get(BotState, key)
            if row is None:
                session.add(BotState(key=key, value=value))
            else:
                row.value = value
            await session.commit()

    # ---------------------------------------------------------------- trash

    async def list_deleted_cards(
        self, *, offset: int, limit: int, query: str | None = None
    ) -> tuple[list[VehicleCard], int]:
        """A page of soft-deleted cards, most recently deleted first.

        ``query`` matches the VIN (in full or by its last digits) or the name of
        the person who added the card. The bin keeps 30 days of cards, so the
        matching is done in Python: it is case-insensitive for Cyrillic too,
        which SQLite cannot do on its own.
        """

        rows = await self._deleted_cards(query=query)
        total = len(rows)
        if total == 0:
            return [], 0
        start = max(0, min(int(offset), total - 1))
        return rows[start : start + max(1, int(limit))], total

    async def count_deleted_cards(self, *, query: str | None = None) -> int:
        """How many cards are in the bin, optionally matching ``query``."""

        return len(await self._deleted_cards(query=query))

    async def _deleted_cards(self, *, query: str | None) -> list[VehicleCard]:
        async with self.sessions() as session:
            rows = list(
                await session.scalars(
                    select(VehicleCard)
                    .where(VehicleCard.is_deleted.is_(True))
                    .order_by(
                        func.coalesce(
                            VehicleCard.deleted_at, VehicleCard.created_at
                        ).desc(),
                        VehicleCard.id.desc(),
                    )
                )
            )
        if not query:
            return rows
        needle = _search_needle(query)
        return [card for card in rows if needle in _search_needle(_card_haystack(card))]

    async def get_deleted_card(self, card_id: int) -> VehicleCard | None:
        async with self.sessions() as session:
            card = await session.get(VehicleCard, card_id)
            if card is None or not card.is_deleted:
                return None
            return card

    async def restore_card(self, card_id: int) -> bool:
        """Bring a soft-deleted card back into the active catalogue."""

        async with self.sessions() as session:
            card = await session.get(VehicleCard, card_id)
            if card is None or not card.is_deleted:
                return False
            card.is_deleted = False
            card.deleted_at = None
            card.deleted_by = None
            await session.commit()
            return True

    async def purge_card(self, card_id: int, *, min_age_days: int = 30) -> bool:
        """Erase a card forever; only allowed after the safety period."""

        async with self.sessions() as session:
            card = await session.get(VehicleCard, card_id)
            if card is None or not card.is_deleted:
                return False
            if card.deleted_at is None:
                return False
            age = datetime.now(UTC) - card.deleted_at.replace(
                tzinfo=UTC if card.deleted_at.tzinfo is None else card.deleted_at.tzinfo
            )
            if age.days < max(0, int(min_age_days)):
                return False
            await session.delete(card)
            await session.commit()
            return True

    # -------------------------------------------------------------- archive

    async def set_archive_message_id(self, card_id: int, message_id: int) -> None:
        async with self.sessions() as session:
            card = await session.get(VehicleCard, card_id)
            if card is None:
                return
            card.archive_message_id = message_id
            await session.commit()

    async def set_paint_archive_message_id(self, card_id: int, message_id: int) -> None:
        async with self.sessions() as session:
            card = await session.get(PaintCard, card_id)
            if card is None:
                return
            card.archive_message_id = message_id
            await session.commit()

    async def daily_digest(self, since: datetime) -> DailyDigest:
        """Numbers shown in the daily archive summary."""

        async with self.sessions() as session:
            created = int(
                (
                    await session.scalar(
                        select(func.count(VehicleCard.id)).where(
                            VehicleCard.created_at >= since
                        )
                    )
                )
                or 0
            )
            deleted = int(
                (
                    await session.scalar(
                        select(func.count(VehicleCard.id)).where(
                            VehicleCard.is_deleted.is_(True),
                            VehicleCard.deleted_at >= since,
                        )
                    )
                )
                or 0
            )
            paint_created = int(
                (
                    await session.scalar(
                        select(func.count(PaintCard.id)).where(
                            PaintCard.created_at >= since
                        )
                    )
                )
                or 0
            )
            active = int(
                (
                    await session.scalar(
                        select(func.count(VehicleCard.id)).where(
                            VehicleCard.is_deleted.is_(False)
                        )
                    )
                )
                or 0
            )
            paint_active = int(
                (
                    await session.scalar(
                        select(func.count(PaintCard.id)).where(
                            PaintCard.status == PaintStatus.IN_PROGRESS.value
                        )
                    )
                )
                or 0
            )
            return DailyDigest(
                created=created,
                deleted=deleted,
                paint_created=paint_created,
                active=active,
                paint_active=paint_active,
            )
