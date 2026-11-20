"""Local SQLite snapshots: creation, rotation, validation and safe restore.

The bot keeps a small SQLite file, so a snapshot is a consistent copy made with
the ``sqlite3`` backup API and immediately compressed with gzip. Restoring never
replaces the database file itself: the snapshot is copied *into* the live file,
which keeps every already open connection valid on both Linux and Windows.
"""

from __future__ import annotations

import gzip
import logging
import re
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

SQLITE_MAGIC = b"SQLite format 3\x00"
GZIP_MAGIC = b"\x1f\x8b"
# A copy made twice within the same second carries a microsecond suffix.
SNAPSHOT_RE = re.compile(r"^bot-(\d{8}T\d{6}Z)(?:-\d+)?\.db\.gz$")
REQUIRED_TABLES = frozenset({"users", "vehicle_cards", "paint_cards"})
# Telegram lets a bot receive files up to 20 MB and send documents up to 50 MB.
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
CHUNK_BYTES = 15 * 1024 * 1024
DEFAULT_KEEP_DAYS = 30
DEFAULT_KEEP_WEEKS = 12
DEFAULT_KEEP_MONTHS = 24
MIN_SNAPSHOTS_KEPT = 5


class BackupError(RuntimeError):
    """A backup or restore operation could not be completed safely."""


@dataclass(frozen=True, slots=True)
class Snapshot:
    """One compressed copy of the database."""

    path: Path
    created_at: datetime
    size: int

    @property
    def name(self) -> str:
        return self.path.name

    def label(self, language: str = "ru") -> str:
        """Short human readable description for the administrator list."""

        moment = self.created_at.astimezone(UTC)
        date = moment.strftime("%d.%m.%Y")
        clock = moment.strftime("%H:%M")
        size = format_size(self.size)
        if language == "de":
            return f"🗂 {date} · {clock} Uhr · {size}"
        return f"🗂 {date} · {clock} · {size}"


def format_size(size: int) -> str:
    """Return a compact size such as ``1,4 МБ``."""

    value = float(max(0, int(size)))
    if value < 1024:
        return f"{int(value)} Б"
    for unit in ("КБ", "МБ", "ГБ"):
        value /= 1024.0
        if value < 1024 or unit == "ГБ":
            text = f"{value:,.1f}".replace(",", " ")
            return f"{text} {unit}"
    return f"{value:,.1f} ГБ"


def snapshot_stamp(moment: datetime | None = None) -> str:
    return (moment or datetime.now(UTC)).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def create_snapshot(
    database_path: Path,
    backup_dir: Path,
    *,
    moment: datetime | None = None,
) -> Snapshot:
    """Copy the live database into a compressed snapshot inside ``backup_dir``."""

    if not database_path.exists():
        raise BackupError("Файл базы данных не найден")
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp_time = (moment or datetime.now(UTC)).astimezone(UTC)
    stamp = snapshot_stamp(stamp_time)
    target = backup_dir / f"bot-{stamp}.db.gz"
    if target.exists():
        # Two snapshots within the same second would overwrite each other.
        stamp = f"{stamp}-{datetime.now(UTC).microsecond:06d}"
        target = backup_dir / f"bot-{stamp}.db.gz"
    temporary = target.with_suffix(".db.tmp")

    source = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    try:
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            plain_path = Path(handle.name)
        try:
            plain = sqlite3.connect(plain_path)
            try:
                with plain:
                    source.backup(plain)
            finally:
                plain.close()
            with (
                open(plain_path, "rb") as raw,
                gzip.GzipFile(temporary, mode="wb", mtime=0) as packed,
            ):
                packed.write(raw.read())
        finally:
            plain_path.unlink(missing_ok=True)
    finally:
        source.close()

    temporary.replace(target)
    size = target.stat().st_size
    logger.info("Создана резервная копия %s (%s), байт", target.name, size)
    return Snapshot(path=target, created_at=stamp_time, size=size)


def list_snapshots(backup_dir: Path) -> list[Snapshot]:
    """Existing snapshots, newest first; unreadable names are ignored."""

    if not backup_dir.exists():
        return []
    snapshots: list[Snapshot] = []
    for entry in backup_dir.iterdir():
        if not entry.is_file():
            continue
        match = SNAPSHOT_RE.match(entry.name)
        if match is None:
            continue
        try:
            moment = datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(
                tzinfo=UTC
            )
        except ValueError:
            continue
        snapshots.append(
            Snapshot(path=entry, created_at=moment, size=entry.stat().st_size)
        )
    snapshots.sort(key=lambda item: item.created_at, reverse=True)
    return snapshots


def rotate_snapshots(
    backup_dir: Path,
    *,
    keep_days: int = DEFAULT_KEEP_DAYS,
    keep_weeks: int = DEFAULT_KEEP_WEEKS,
    keep_months: int = DEFAULT_KEEP_MONTHS,
    now: datetime | None = None,
) -> int:
    """Delete old snapshots but keep recent, weekly and monthly survivors.

    Recent copies protect against an accidental deletion, weekly and monthly
    copies protect against a problem that is noticed only much later.
    """

    snapshots = list_snapshots(backup_dir)
    if not snapshots:
        return 0
    current = (now or datetime.now(UTC)).astimezone(UTC)

    keep: set[Path] = set()
    for index, snapshot in enumerate(snapshots):
        age_days = (current - snapshot.created_at).days
        if index < MIN_SNAPSHOTS_KEPT or age_days <= keep_days:
            keep.add(snapshot.path)
    for unit, limit in (
        (("year", "week"), keep_weeks),
        (("year", "month"), keep_months),
    ):
        grouped: dict[tuple[int, int], Snapshot] = {}
        for snapshot in snapshots:
            calendar = snapshot.created_at.isocalendar() if unit[1] == "week" else None
            if calendar is not None:
                key = (calendar[0], calendar[1])
            else:
                key = (snapshot.created_at.year, snapshot.created_at.month)
            if key not in grouped:
                grouped[key] = snapshot
        for snapshot in list(grouped.values())[: max(0, limit)]:
            keep.add(snapshot.path)

    removed = 0
    for snapshot in snapshots:
        if snapshot.path in keep:
            continue
        try:
            snapshot.path.unlink()
            removed += 1
        except OSError as exc:  # pragma: no cover - filesystem dependent
            logger.warning("Не удалось удалить копию %s: %s", snapshot.path.name, exc)
    if removed:
        logger.info("Ротация резервных копий: удалено %s шт.", removed)
    return removed


def decompress(data: bytes) -> bytes:
    """Turn uploaded bytes into plain SQLite content, accepting gzip or raw."""

    if not data:
        raise BackupError("Файл пустой")
    if len(data) > MAX_DOWNLOAD_BYTES:
        raise BackupError("Файл слишком большой для Telegram")
    if data[:2] == GZIP_MAGIC:
        try:
            data = gzip.decompress(data)
        except OSError as exc:
            raise BackupError("Файл повреждён: не удалось распаковать") from exc
    return data


def validate_sqlite(data: bytes) -> None:
    """Refuse anything that is not a readable database with the right tables."""

    if not data.startswith(SQLITE_MAGIC):
        raise BackupError("Это не база данных SQLite")
    if len(data) < 4096:
        raise BackupError("Файл базы данных слишком короткий")
    with tempfile.NamedTemporaryFile(delete=False) as handle:
        handle.write(data)
        path = Path(handle.name)
    try:
        connection = sqlite3.connect(path)
        try:
            verdict = connection.execute("PRAGMA integrity_check").fetchone()
            if not verdict or str(verdict[0]).lower() != "ok":
                raise BackupError(
                    "База данных повреждена: проверка целостности не пройдена"
                )
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            missing = REQUIRED_TABLES - tables
            if missing:
                raise BackupError(
                    "В файле нет нужных таблиц: " + ", ".join(sorted(missing))
                )
        finally:
            connection.close()
    finally:
        path.unlink(missing_ok=True)


def _healthy_tables(connection: sqlite3.Connection) -> bool:
    """True when the business tables are all present.

    An empty file is a valid empty database and passes ``integrity_check``,
    which is exactly the shape a truncated file takes, so the tables are
    checked as well.
    """

    try:
        verdict = connection.execute("PRAGMA integrity_check").fetchone()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    except sqlite3.DatabaseError:
        return False
    return (
        bool(verdict)
        and str(verdict[0]).lower() == "ok"
        and not (REQUIRED_TABLES - tables)
    )


def database_is_usable(path: Path) -> bool:
    """True when ``path`` is a readable database with the expected tables."""

    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return False
    try:
        return _healthy_tables(connection)
    finally:
        connection.close()


def recover_database(database_path: Path, backup_dir: Path) -> str | None:
    """Bring back the newest usable snapshot when the database is broken.

    The damaged file is never thrown away: it is renamed with a ``.broken``
    suffix so it can still be inspected by hand. Returns a short note for the
    administrator, or None when there was nothing to repair.
    """

    if not database_path.exists():
        # Nothing to repair: the bot is being installed for the first time.
        return None
    if database_is_usable(database_path):
        return None

    kept_aside: Path | None = None
    if database_path.exists():
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        kept_aside = database_path.with_name(f"{database_path.name}.{stamp}.broken")
        try:
            database_path.replace(kept_aside)
        except OSError:
            logger.warning("Не удалось отложить повреждённую базу в сторону")
            kept_aside = None

    for snapshot in list_snapshots(backup_dir):
        try:
            raw = snapshot.path.read_bytes()
            validate_sqlite(decompress(raw))
        except (BackupError, OSError, ValueError, EOFError):
            logger.warning("Снимок %s не читается, пробую следующий", snapshot.name)
            continue
        try:
            restore_snapshot(database_path, decompress(raw))
        except (BackupError, OSError, ValueError, sqlite3.Error) as exc:
            logger.warning("Не удалось восстановить базу из %s: %s", snapshot.name, exc)
            continue
        moment = snapshot.created_at.astimezone(UTC).strftime("%d.%m.%Y %H:%M")
        note = (
            "\u26a0\ufe0f \u0411\u0430\u0437\u0430 \u0431\u044b\u043b\u0430 \u043f\u043e\u0432\u0440\u0435\u0436\u0434\u0435\u043d\u0430 \u0438\u043b\u0438 \u043f\u0443\u0441\u0442\u0430, "
            f"\u0432\u0435\u0440\u043d\u0443\u043b \u0441\u043e\u0441\u0442\u043e\u044f\u043d\u0438\u0435 \u043d\u0430 {moment} (UTC) "
            f"\u0438\u0437 \u0441\u043d\u0438\u043c\u043a\u0430 {snapshot.name}."
        )
        if kept_aside is not None:
            note += f"\n\u041f\u043e\u0432\u0440\u0435\u0436\u0434\u0451\u043d\u043d\u044b\u0439 \u0444\u0430\u0439\u043b \u0441\u043e\u0445\u0440\u0430\u043d\u0451\u043d: {kept_aside.name}"
        return note

    logger.error("База повреждена, а годных снимков нет")
    note = "\u26a0\ufe0f \u0411\u0430\u0437\u0430 \u043f\u043e\u0432\u0440\u0435\u0436\u0434\u0435\u043d\u0430, \u0438 \u0433\u043e\u0434\u043d\u043e\u0433\u043e \u0441\u043d\u0438\u043c\u043a\u0430 \u043d\u0435\u0442."
    if kept_aside is not None:
        note += f"\n\u0424\u0430\u0439\u043b \u0441\u043e\u0445\u0440\u0430\u043d\u0451\u043d: {kept_aside.name}"
    return note


def restore_snapshot(database_path: Path, snapshot_bytes: bytes) -> dict[str, int]:
    """Write a validated snapshot *into* the live database file.

    The file itself is never replaced, therefore connections that are already
    open keep working and no operating system specific trickery is needed.
    """

    validate_sqlite(snapshot_bytes)
    database_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(delete=False) as handle:
        handle.write(snapshot_bytes)
        plain_path = Path(handle.name)
    try:
        source = sqlite3.connect(plain_path)
        try:
            target = sqlite3.connect(database_path, timeout=30.0)
            try:
                # A plain journal keeps the copy predictable on every platform.
                target.execute("PRAGMA journal_mode=DELETE")
                target.execute("PRAGMA foreign_keys=OFF")
                with target:
                    source.backup(target)
            finally:
                target.close()
        finally:
            source.close()
    finally:
        plain_path.unlink(missing_ok=True)

    for suffix in ("-wal", "-shm", "-journal"):
        stale = database_path.with_name(database_path.name + suffix)
        if stale.exists():
            try:
                stale.unlink()
            except OSError:  # pragma: no cover - filesystem dependent
                logger.warning("Не удалось удалить служебный файл %s", stale.name)

    counts: dict[str, int] = {}
    connection = sqlite3.connect(database_path, timeout=30.0)
    try:
        for table in ("users", "vehicle_cards", "paint_cards"):
            try:
                counts[table] = int(
                    connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                )
            except sqlite3.Error:  # pragma: no cover - guarded by validate_sqlite
                counts[table] = 0
    finally:
        connection.close()
    logger.info("База восстановлена из резервной копии: %s", counts)
    return counts


def split_for_telegram(data: bytes, chunk_size: int = CHUNK_BYTES) -> list[bytes]:
    """Split a dump into parts small enough for Telegram to send and receive."""

    if not data:
        return []
    size = max(1, int(chunk_size))
    return [data[index : index + size] for index in range(0, len(data), size)]


def table_counts(data: bytes) -> dict[str, int]:
    """Row counts of a dump, used to show the administrator what is inside."""

    validate_sqlite(data)
    with tempfile.NamedTemporaryFile(delete=False) as handle:
        handle.write(data)
        path = Path(handle.name)
    try:
        connection = sqlite3.connect(path)
        try:
            counts: dict[str, int] = {}
            for table in sorted(REQUIRED_TABLES):
                try:
                    counts[table] = int(
                        connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[
                            0
                        ]
                    )
                except sqlite3.Error:  # pragma: no cover - guarded by validation
                    counts[table] = 0
            return counts
        finally:
            connection.close()
    finally:
        path.unlink(missing_ok=True)
