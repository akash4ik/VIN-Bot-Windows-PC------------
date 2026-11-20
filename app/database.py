from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    inspect,
    text,
)
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.roles import Role


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    language: Mapped[str | None] = mapped_column(String(2), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), default="")
    # Name assigned by an administrator. When set it is shown instead of the
    # Telegram profile name, which is resynchronised on every interaction.
    display_name: Mapped[str | None] = mapped_column(
        "display_name", String(64), nullable=True
    )
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    role: Mapped[str] = mapped_column(
        String(16), default=Role.DRIVER.value, nullable=False
    )
    # Kept for one-way compatibility with v10 databases. ``role`` is the
    # authoritative field; repository writes keep this legacy flag in sync.
    legacy_is_admin: Mapped[bool] = mapped_column(
        "is_admin", Boolean, default=False, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class VehicleCard(Base):
    __tablename__ = "vehicle_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id"), nullable=False, index=True
    )
    owner_name: Mapped[str] = mapped_column(String(255), default="")
    vehicle_photo_file_id: Mapped[str] = mapped_column(Text, nullable=False)
    invoice_photo_file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    vin_photo_file_id: Mapped[str] = mapped_column(Text, nullable=False)
    vin_full: Mapped[str | None] = mapped_column(String(17), nullable=True)
    vin_suffix6: Mapped[str] = mapped_column(String(6), nullable=False)
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Message id of the permanent copy inside the archive channel.
    archive_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


Index("ix_vehicle_cards_suffix_active", VehicleCard.vin_suffix6, VehicleCard.is_deleted)


class PaintStatus(StrEnum):
    """Lifecycle of a vehicle inside the painting section."""

    IN_PROGRESS = "in_progress"
    DONE = "done"


class PaintCard(Base):
    """Vehicle handed over for painting.

    Only two photographs are required: the vehicle itself and the cropped VIN
    fragment. The invoice is not needed for painting, therefore painting cards
    are stored separately from the regular vehicle cards.
    """

    __tablename__ = "paint_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id"), nullable=False, index=True
    )
    owner_name: Mapped[str] = mapped_column(String(255), default="")
    vehicle_photo_file_id: Mapped[str] = mapped_column(Text, nullable=False)
    vin_photo_file_id: Mapped[str] = mapped_column(Text, nullable=False)
    vin_full: Mapped[str | None] = mapped_column(String(17), nullable=True)
    vin_suffix6: Mapped[str] = mapped_column(String(6), nullable=False)
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), default=PaintStatus.IN_PROGRESS.value, nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    completed_by_name: Mapped[str] = mapped_column(String(255), default="")
    archive_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


Index("ix_paint_cards_status_suffix", PaintCard.status, PaintCard.vin_suffix6)


class AuditAction(StrEnum):
    """Actions recorded so every dangerous operation stays traceable."""

    CARD_CREATED = "card_created"
    CARD_DELETED = "card_deleted"
    CARD_RESTORED = "card_restored"
    CARD_PURGED = "card_purged"
    BACKUP_EXPORTED = "backup_exported"
    BACKUP_CREATED = "backup_created"
    BACKUP_RESTORED = "backup_restored"
    BACKUP_UPLOADED = "backup_uploaded"
    ROLE_CHANGED = "role_changed"
    USER_RENAMED = "user_renamed"


class AuditLog(Base):
    """Append-only record of who did what, kept next to the business data."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )
    actor_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    actor_name: Mapped[str] = mapped_column(String(255), default="")
    action: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    details: Mapped[str] = mapped_column(Text, default="")


class BotState(Base):
    """Small key/value memory that travels with the database.

    The daily archive dump has to survive a night with the computer switched
    off, and for that the bot must know when it last managed to send one. A
    file next to the database would do, but then a restored database would
    carry someone else's memory, so the note lives inside the data itself.
    """

    __tablename__ = "bot_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


def create_engine_and_session(
    database_url: str,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    return engine, sessions


async def init_database(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

        def add_missing_columns(sync_connection) -> None:
            inspector = inspect(sync_connection)
            card_columns = {
                column["name"]
                for column in inspector.get_columns(VehicleCard.__tablename__)
            }
            if "invoice_photo_file_id" not in card_columns:
                sync_connection.execute(
                    text(
                        "ALTER TABLE vehicle_cards "
                        "ADD COLUMN invoice_photo_file_id TEXT NULL"
                    )
                )

            user_columns = {
                column["name"] for column in inspector.get_columns(User.__tablename__)
            }
            # Archive references: the permanent copy inside the channel.
            for table in (VehicleCard.__tablename__, PaintCard.__tablename__):
                columns = {column["name"] for column in inspector.get_columns(table)}
                if "archive_message_id" not in columns:
                    sync_connection.execute(
                        text(
                            f"ALTER TABLE {table} "
                            "ADD COLUMN archive_message_id BIGINT NULL"
                        )
                    )

            if "display_name" not in user_columns:
                sync_connection.execute(
                    text("ALTER TABLE users ADD COLUMN display_name VARCHAR(64) NULL")
                )
            if "is_admin" not in user_columns:
                sync_connection.execute(
                    text(
                        "ALTER TABLE users "
                        "ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT 0"
                    )
                )

            role_was_added = "role" not in user_columns
            if role_was_added:
                sync_connection.execute(
                    text(
                        "ALTER TABLE users "
                        "ADD COLUMN role VARCHAR(16) NOT NULL DEFAULT 'driver'"
                    )
                )
                # Preserve administrators from v10 while applying the new
                # least-privilege default (driver) to all other existing users.
                sync_connection.execute(
                    text(
                        "UPDATE users SET role = CASE "
                        "WHEN is_admin = 1 THEN 'admin' ELSE 'driver' END"
                    )
                )

            # A damaged or manually edited value must never grant extra rights.
            sync_connection.execute(
                text(
                    "UPDATE users SET role = 'driver' "
                    "WHERE role NOT IN ('driver', 'worker', 'admin') OR role IS NULL"
                )
            )
            sync_connection.execute(
                text(
                    "UPDATE users SET is_admin = CASE "
                    "WHEN role = 'admin' THEN 1 ELSE 0 END"
                )
            )

            # A damaged paint status must never hide a vehicle from both lists.
            sync_connection.execute(
                text(
                    "UPDATE paint_cards SET status = 'in_progress' "
                    "WHERE status IS NULL OR status NOT IN ('in_progress', 'done')"
                )
            )

        await connection.run_sync(add_missing_columns)
