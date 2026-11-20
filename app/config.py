from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

MAX_TELEGRAM_ID = 9_223_372_036_854_775_807
VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
VALID_PREFERENCES = frozenset({"direct", "proxy"})
# «второй читатель» — облако, которое смотрит ту же фотографию, что и бот.
VALID_GEMINI_MODES = frozenset({"off", "auto", "always", "first"})
GEMINI_MODE_DEFAULT = "auto"
GEMINI_TIMEOUT_DEFAULT = 45.0


def _parse_ids(raw: str | None, *, variable: str) -> frozenset[int]:
    if not raw or not raw.strip():
        return frozenset()

    values: set[int] = set()
    for raw_item in raw.split(","):
        item = raw_item.strip()
        if not item or not item.isascii() or not item.isdecimal():
            raise RuntimeError(
                f"{variable} должен содержать положительные числовые Telegram ID "
                "через запятую"
            )
        value = int(item)
        if value <= 0 or value > MAX_TELEGRAM_ID:
            raise RuntimeError(f"Недопустимый Telegram ID в {variable}: {item}")
        values.add(value)
    return frozenset(values)


def _parse_bool(raw: str | None, *, default: bool) -> bool:
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"Недопустимое логическое значение: {raw}")


def _validate_channel(raw: str | None) -> str | None:
    """A Telegram channel id such as ``@allnewclear`` or ``-1001234567890``.

    A full link is accepted as well, because that is what a channel page shows
    when it is opened in a browser: ``https://t.me/allnewclear`` simply becomes
    ``@allnewclear`` instead of stopping the bot at start-up.
    """

    value = (raw or "").strip().strip("/").split("?")[0].split("#")[0].strip()
    if not value:
        return None
    value = re.sub(
        r"^(?:https?://)?(?:www\.)?(?:t|telegram)\.me/",
        "@",
        value,
        flags=re.IGNORECASE,
    )
    if not value.startswith(("@", "-100")):
        value = f"@{value.lstrip('@')}"
    if not re.fullmatch(r"@[A-Za-z0-9_]{4,32}|-100\d{8,}", value):
        raise RuntimeError(
            "ARCHIVE_CHANNEL_ID должен быть @имя_канала, ссылкой https://t.me/имя "
            "или -1001234567890"
        )
    return value


def _validate_clock(raw: str | None) -> str:
    """A daily digest time in 24-hour ``HH:MM`` form."""

    value = (raw or "").strip()
    if not re.fullmatch(r"\d{2}:\d{2}", value):
        raise RuntimeError(
            "ARCHIVE_DIGEST_TIME должен быть в формате ЧЧ:ММ, например 23:30"
        )
    hours, minutes = (int(part) for part in value.split(":"))
    if hours > 23 or minutes > 59:
        raise RuntimeError("ARCHIVE_DIGEST_TIME: недопустимое время суток")
    return f"{hours:02d}:{minutes:02d}"


def _validate_language(raw: str | None) -> str:
    value = (raw or "").strip().lower()
    if value not in {"ru", "de"}:
        raise RuntimeError("ARCHIVE_LANGUAGE должен быть ru или de")
    return value


def _validate_preference(raw: str | None) -> str:
    """Which transport to try first: a direct connection or the proxy."""

    value = (raw or "").strip().lower()
    if not value:
        return "direct"
    if value not in VALID_PREFERENCES:
        raise RuntimeError(
            "TELEGRAM_PREFER должен быть direct или proxy: сначала прямое "
            "подключение или сначала прокси"
        )
    return value


def _validate_proxy(raw: str | None) -> str | None:
    value = (raw or "").strip()
    if not value:
        return None
    if any(char.isspace() for char in value):
        raise RuntimeError("TELEGRAM_PROXY не должен содержать пробелы")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise RuntimeError("В TELEGRAM_PROXY указан недопустимый порт") from exc
    if parsed.scheme not in {"socks5", "socks4", "http", "https"}:
        raise RuntimeError(
            "TELEGRAM_PROXY должен начинаться с socks5://, socks4://, http:// или https://"
        )
    if not parsed.hostname:
        raise RuntimeError("В TELEGRAM_PROXY не указан адрес прокси")
    if port is None or not 1 <= port <= 65535:
        raise RuntimeError("В TELEGRAM_PROXY должен быть указан порт от 1 до 65535")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise RuntimeError(
            "TELEGRAM_PROXY не должен содержать путь, параметры или фрагмент"
        )
    return value


def _validate_gemini_key(raw: str | None) -> str:
    """The key for the cloud reader, or "" when he has not bought one.

    Google hands these out as ``AIza…`` and they are 39 characters long. The
    length is checked only to catch a key that was pasted in half — the real
    test is whether Google accepts it, and that is only known at the first
    photograph.
    """

    value = (raw or "").strip()
    if not value:
        return ""
    if any(char.isspace() for char in value):
        raise RuntimeError("GEMINI_API_KEY не должен содержать пробелы")
    if len(value) < 20:
        raise RuntimeError("GEMINI_API_KEY слишком короткий: ключ вставляют целиком")
    return value


def _validate_gemini_mode(raw: str | None) -> str:
    """When to ask the cloud: never, only on hard photographs, or always."""

    value = (raw or "").strip().lower()
    if not value:
        return GEMINI_MODE_DEFAULT
    if value not in VALID_GEMINI_MODES:
        raise RuntimeError("GEMINI_MODE должен быть off, auto, first или always")
    return value


def _validate_seconds(raw: str | None) -> float:
    """How long to wait for the cloud before reading the picture ourselves."""

    value = (raw or "").strip()
    if not value:
        return GEMINI_TIMEOUT_DEFAULT
    try:
        seconds = float(value)
    except ValueError as exc:
        raise RuntimeError("GEMINI_TIMEOUT должен быть числом секунд") from exc
    if not 5.0 <= seconds <= 300.0:
        raise RuntimeError("GEMINI_TIMEOUT должен быть от 5 до 300 секунд")
    return seconds


@dataclass(frozen=True, slots=True)
class Config:
    bot_token: str
    database_url: str
    allowed_user_ids: frozenset[int]
    admin_user_ids: frozenset[int]
    timezone: ZoneInfo
    log_level: str
    tesseract_cmd: str | None
    telegram_proxy: str | None
    telegram_prefer: str
    force_ipv4: bool
    # Local snapshot directory readable and writable by the bot process.
    backup_dir: Path = Path("data/backups")
    # Telegram channel that keeps a permanent copy of every photograph and of
    # the daily database dump. The defaults keep a manually built Config valid;
    # ``from_env`` always fills them from the environment.
    archive_channel_id: str | None = None
    archive_immediate: bool = True
    archive_digest_time: str = "23:30"
    archive_include_invoice: bool = True
    archive_language: str = "ru"
    # Second reader in the cloud. Empty by default: the bot reads every
    # photograph itself and works without a key, a network or a payment.
    # He buys a key from Google, drops it into .env next to the bot token,
    # and from then on hard photographs get a second opinion.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"
    # off — never ask; auto — ask only when the local reading is not certain
    # (the usual choice: money is spent where it helps); always — ask always.
    gemini_mode: str = GEMINI_MODE_DEFAULT
    gemini_timeout: float = GEMINI_TIMEOUT_DEFAULT
    # Only the cloud request uses this. Telegram keeps its own route, so a
    # proxy that dies takes the second reader with it and nothing else.
    gemini_proxy: str = ""

    @classmethod
    def from_env(cls) -> Config:
        load_dotenv()
        token = os.getenv("BOT_TOKEN", "").strip()
        if not token or token == "replace_with_new_token":
            raise RuntimeError(
                "BOT_TOKEN не указан. Создайте .env и добавьте новый токен от @BotFather."
            )
        if not re.fullmatch(r"[1-9][0-9]{4,15}:[A-Za-z0-9_-]{30,}", token):
            raise RuntimeError(
                "BOT_TOKEN имеет неверный формат. Получите новый токен у @BotFather."
            )

        database_url = os.getenv(
            "DATABASE_URL", "sqlite+aiosqlite:///data/bot.db"
        ).strip()
        if not database_url:
            raise RuntimeError("DATABASE_URL не может быть пустым")
        if database_url.startswith("sqlite+aiosqlite:///"):
            raw_path = database_url.removeprefix("sqlite+aiosqlite:///")
            if raw_path and raw_path != ":memory:":
                Path(raw_path).parent.mkdir(parents=True, exist_ok=True)

        timezone_name = os.getenv("TIMEZONE", "Europe/Berlin").strip()
        try:
            timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise RuntimeError(
                f"Неизвестный часовой пояс TIMEZONE: {timezone_name}"
            ) from exc

        log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()
        if log_level not in VALID_LOG_LEVELS:
            raise RuntimeError(
                "LOG_LEVEL должен быть DEBUG, INFO, WARNING, ERROR или CRITICAL"
            )

        # Windows paths are written with backslashes; forward slashes work on
        # both systems, so the value is normalised before it is used.
        backup_dir = Path(
            (os.getenv("BACKUP_DIR", "").strip() or "data/backups").replace("\\", "/")
        ).resolve()
        backup_dir.mkdir(parents=True, exist_ok=True)

        return cls(
            bot_token=token,
            database_url=database_url,
            allowed_user_ids=_parse_ids(
                os.getenv("ALLOWED_USER_IDS"), variable="ALLOWED_USER_IDS"
            ),
            admin_user_ids=_parse_ids(
                os.getenv("ADMIN_USER_IDS"), variable="ADMIN_USER_IDS"
            ),
            timezone=timezone,
            log_level=log_level,
            tesseract_cmd=(os.getenv("TESSERACT_CMD") or "").strip() or None,
            telegram_proxy=_validate_proxy(os.getenv("TELEGRAM_PROXY")),
            telegram_prefer=_validate_preference(os.getenv("TELEGRAM_PREFER")),
            force_ipv4=_parse_bool(os.getenv("FORCE_IPV4"), default=True),
            backup_dir=backup_dir,
            archive_channel_id=_validate_channel(os.getenv("ARCHIVE_CHANNEL_ID")),
            archive_immediate=_parse_bool(os.getenv("ARCHIVE_IMMEDIATE"), default=True),
            archive_digest_time=_validate_clock(
                os.getenv("ARCHIVE_DIGEST_TIME") or "23:30"
            ),
            archive_include_invoice=_parse_bool(
                os.getenv("ARCHIVE_INCLUDE_INVOICE"), default=True
            ),
            archive_language=_validate_language(os.getenv("ARCHIVE_LANGUAGE") or "ru"),
            gemini_api_key=_validate_gemini_key(os.getenv("GEMINI_API_KEY")),
            gemini_model=(os.getenv("GEMINI_MODEL") or "").strip()
            or "gemini-3.5-flash-lite",
            gemini_mode=_validate_gemini_mode(os.getenv("GEMINI_MODE")),
            gemini_timeout=_validate_seconds(os.getenv("GEMINI_TIMEOUT")),
            gemini_proxy=(os.getenv("GEMINI_PROXY") or "").strip(),
        )

    @property
    def archive_enabled(self) -> bool:
        """The archive only runs when a channel is configured."""

        return self.archive_channel_id is not None

    @property
    def gemini_enabled(self) -> bool:
        """Whether the cloud reader will be asked at all."""

        return self.gemini_mode != "off" and bool(self.gemini_api_key)

    @property
    def gemini_second_reader(self) -> bool:
        """True when the cloud is a fallback, not the primary reader.

        The bot always reads the photograph itself first: it works offline,
        costs nothing and is the one already tested. The cloud is asked only
        afterwards, when that reading is not certain.
        """

        return self.gemini_enabled

    @property
    def sqlite_path(self) -> Path | None:
        """Path of the SQLite file, or None for any other database backend."""

        prefix = "sqlite+aiosqlite:///"
        if not self.database_url.startswith(prefix):
            return None
        raw_path = self.database_url.removeprefix(prefix)
        if not raw_path or raw_path == ":memory:":
            return None
        return Path(raw_path).resolve()
