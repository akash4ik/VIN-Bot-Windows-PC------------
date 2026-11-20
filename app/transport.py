"""Connection transports for Telegram.

The bot never depends on a single VPN or proxy program. It keeps a list of
ways to reach Telegram — a direct connection and, if one is configured, a local
proxy — probes them in order and automatically moves on to the next option when
the active one stops answering.
"""

from __future__ import annotations

import asyncio
import logging
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramNetworkError
from aiohttp.abc import AbstractResolver
from aiohttp.resolver import DefaultResolver

from app.config import Config

# Imported here rather than at the top of the module: the network check is only
# needed when the connection is planned, and the transport must stay importable
# on a machine where even that is broken.
from app.netcheck import TELEGRAM_HOST, discover_addresses

logger = logging.getLogger(__name__)

PREFER_DIRECT = "direct"
PREFER_PROXY = "proxy"
VALID_PREFERENCES = frozenset({PREFER_DIRECT, PREFER_PROXY})

PROBE_TIMEOUT = 12.0
# A home router, a Wi-Fi access point or a mobile modem drops a connection for
# a few seconds several times an hour. The bot must ride those out instead of
# restarting, so the health check is deliberately slow and patient: it runs
# every 90 seconds and needs four failures in a row — roughly six minutes of
# continuous silence — before it touches the connection at all.
HEALTH_CHECK_INTERVAL = 90.0
HEALTH_CHECK_TIMEOUT = 25.0
FAILURES_BEFORE_SWITCH = 4
# Telegram answers slowly on weak connections; a 60 second request timeout is
# what made getUpdates fail in the first place.
REQUEST_TIMEOUT = 120.0
# How many failed checks in a row are still treated as an ordinary blip. Two
# checks are about three minutes of silence, which a home line produces on its
# own; anything longer is worth a warning.
QUIET_FAILURES = 2

# Failures that mean “this way to reach Telegram is unusable”.
TRANSPORT_ERRORS: tuple[type[BaseException], ...] = (
    TimeoutError,  # asyncio.wait_for raises TimeoutError on Python 3.11+
    OSError,
    TelegramNetworkError,
)


@dataclass(frozen=True, slots=True)
class Transport:
    """One way to reach Telegram: directly, over one address, or through a proxy.

    ``pinned_ip`` sends the request to a fixed address while the TLS handshake
    still names ``api.telegram.org`` — the way out when the provider's DNS
    answers with junk. ``family`` picks IPv4 or IPv6 explicitly for the same
    reason the other way round.
    """

    proxy: str | None
    force_ipv4: bool
    pinned_ip: str | None = None
    family: int = socket.AF_UNSPEC

    @property
    def name(self) -> str:
        if self.proxy:
            return f"прокси {self.proxy}"
        if self.pinned_ip:
            return f"прямое подключение на адрес {self.pinned_ip}"
        if self.family == socket.AF_INET6:
            return "прямое подключение через IPv6"
        return "прямое подключение"

    def describe(self) -> str:
        if self.proxy:
            return f"через прокси {self.proxy}"
        if self.pinned_ip:
            return (
                f"напрямую на адрес {self.pinned_ip} "
                "(то же имя в TLS, в обход DNS провайдера)"
            )
        if self.family == socket.AF_INET6:
            return "напрямую через IPv6, без VPN и прокси"
        return "напрямую, без VPN и прокси"


def build_transports(
    config: Config,
    *,
    pinned_ips: tuple[str, ...] = (),
    with_ipv6: bool = False,
) -> list[Transport]:
    """Return the transports to try, best one first.

    A direct connection is preferred so the bot keeps working when a VPN or any
    other VPN program is closed, uninstalled or not connected yet. The extra
    routes are appended behind it: they are only worth their patience when the
    ordinary way is the one that is broken.
    """

    direct = Transport(proxy=None, force_ipv4=config.force_ipv4)
    extras: list[Transport] = []
    if with_ipv6 and config.force_ipv4:
        # Forced onto IPv4 by configuration, so the other family is never tried
        # on its own. Providers that filter Telegram usually filter the IPv4
        # ranges and leave IPv6 alone, which makes this worth one attempt.
        extras.append(Transport(proxy=None, force_ipv4=False, family=socket.AF_INET6))
    for address in pinned_ips:
        extras.append(Transport(proxy=None, force_ipv4=False, pinned_ip=address))

    if not config.telegram_proxy:
        return [direct, *extras]
    proxy = Transport(proxy=config.telegram_proxy, force_ipv4=False)
    if config.telegram_prefer == PREFER_PROXY:
        return [proxy, direct, *extras]
    return [direct, *extras, proxy]


async def plan_routes(config: Config) -> list[Transport]:
    """Ask where Telegram lives before deciding how to reach it.

    The computer's own DNS is trusted first; a public DNS server is only asked
    to supply addresses the first one never mentioned, because retrying an
    address that is already being filtered changes nothing. Any problem while
    asking leaves the ordinary routes untouched.
    """

    try:
        own, extra = await discover_addresses(TELEGRAM_HOST)
    except Exception:
        logger.debug("Не удалось спросить адреса Telegram у DNS", exc_info=True)
        return build_transports(config, with_ipv6=True)
    if extra:
        logger.info(
            "Публичный DNS даёт другие адреса Telegram (%s); "
            "добавляю их в список способов подключения.",
            ", ".join(extra),
        )
    if not any(":" in address for address in own):
        # No IPv6 address from the computer's own DNS: an IPv6 attempt would
        # only cost twenty seconds of staring at a dead route.
        return build_transports(config, pinned_ips=tuple(extra))
    return build_transports(config, pinned_ips=tuple(extra), with_ipv6=True)


def describe_error(exc: BaseException) -> str:
    """Put a failure into words, even one that carries no message of its own.

    ``asyncio.TimeoutError``, the usual answer when packets are silently
    dropped, has an empty string: logging it produced the famous pair of empty
    brackets and told nobody anything.
    """

    detail = str(exc).strip()
    text = type(exc).__name__
    if detail:
        text += f": {detail}"
    else:
        text += " (сервер не ответил вовсе)"
    cause = exc.__cause__ or exc.__context__
    if cause is not None and cause is not exc and str(cause).strip():
        text += f" [причина: {type(cause).__name__}: {str(cause).strip()}]"
    return text


class PinnedResolver(AbstractResolver):
    """Resolve one name to one fixed address and leave every other name alone.

    The request still says «api.telegram.org» inside the TLS handshake, so the
    certificate matches; only the lookup is skipped. That is the repair for a
    provider whose DNS answers with a dead or a wrong address.
    """

    def __init__(self, host: str, address: str) -> None:
        self._host = host.lower()
        self._address = address
        self._family = socket.AF_INET6 if ":" in address else socket.AF_INET
        # Built on first use, not here: aiohttp's resolver wants a running event
        # loop, and a route is planned long before the loop that uses it exists.
        self._fallback: DefaultResolver | None = None

    @property
    def fallback(self) -> DefaultResolver:
        if self._fallback is None:
            self._fallback = DefaultResolver()
        return self._fallback

    async def resolve(
        self, host: str, port: int = 0, family: int = socket.AF_INET
    ) -> list[dict[str, Any]]:
        if host.lower() != self._host:
            return await self.fallback.resolve(host, port, family)
        return [
            {
                "hostname": host,
                "host": self._address,
                "port": port,
                "family": self._family,
                "proto": 0,
                "flags": socket.AI_NUMERICHOST,
            }
        ]

    async def close(self) -> None:
        if self._fallback is not None:
            await self._fallback.close()


def create_bot(config: Config, transport: Transport) -> Bot:
    session = AiohttpSession(proxy=transport.proxy, limit=8, timeout=REQUEST_TIMEOUT)
    if transport.proxy is None:
        if transport.pinned_ip:
            session._connector_init["resolver"] = PinnedResolver(
                TELEGRAM_HOST, transport.pinned_ip
            )
            session._connector_init["family"] = (
                socket.AF_INET6 if ":" in transport.pinned_ip else socket.AF_INET
            )
        elif transport.family in (socket.AF_INET, socket.AF_INET6):
            session._connector_init["family"] = transport.family
        elif transport.force_ipv4:
            # Some Windows VPN adapters time out on Telegram's IPv6 route.
            session._connector_init["family"] = socket.AF_INET
    return Bot(
        token=config.bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


async def probe(
    bot: Any, transport: Transport, *, timeout: float = PROBE_TIMEOUT
) -> bool:
    """Return True when Telegram answers through this transport.

    Only connectivity problems are treated as a failure. A rejected token or
    another API error is re-raised, because switching transports cannot fix it.
    """

    try:
        await asyncio.wait_for(bot.get_me(), timeout=timeout)
    except TRANSPORT_ERRORS:
        # Deliberately silent: one failed check is a blip, and only the caller
        # knows how many of them mean real trouble.
        return False
    except TelegramAPIError:
        raise
    return True


class ConnectionMonitor:
    """Watches the active transport and reports when it stops working.

    aiogram keeps retrying ``getUpdates`` forever when the network breaks, so a
    dead proxy would silently freeze the bot. This monitor notices that and asks
    the caller to switch to the next transport.
    """

    def __init__(
        self,
        bot: Any,
        transport: Transport,
        on_failure: Callable[[], Awaitable[None]],
        *,
        interval: float = HEALTH_CHECK_INTERVAL,
        timeout: float = HEALTH_CHECK_TIMEOUT,
        failures: int = FAILURES_BEFORE_SWITCH,
        switchable: bool = True,
    ) -> None:
        self._bot = bot
        self._transport = transport
        self._on_failure = on_failure
        self._interval = interval
        self._timeout = timeout
        self._failures_to_switch = max(failures, 1)
        # With a single way to reach Telegram there is nothing to switch to.
        # Restarting polling would only throw away the updates that are already
        # waiting, so the monitor then only reports and lets aiogram retry on
        # its own, which it does for as long as it takes.
        self._switchable = switchable
        self._consecutive_failures = 0
        self._stopped = asyncio.Event()

    @property
    def exhausted(self) -> bool:
        return (
            self._switchable and self._consecutive_failures >= self._failures_to_switch
        )

    @property
    def failures(self) -> int:
        return self._consecutive_failures

    async def run(self) -> None:
        while not self._stopped.is_set():
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self._interval)
                return
            except TimeoutError:
                pass

            if await probe(self._bot, self._transport, timeout=self._timeout):
                if self._consecutive_failures >= QUIET_FAILURES:
                    logger.info(
                        "Связь через %s восстановлена, бот продолжает работу.",
                        self._transport.name,
                    )
                self._consecutive_failures = 0
                continue

            self._consecutive_failures += 1
            if not self._switchable:
                self._report_blip()
                continue
            logger.warning(
                "Проверка связи (%s) не удалась: %s из %s",
                self._transport.name,
                self._consecutive_failures,
                self._failures_to_switch,
            )
            if self.exhausted:
                logger.warning(
                    "%s не отвечает. Переключаюсь на следующий способ подключения.",
                    self._transport.name.capitalize(),
                )
                await self._on_failure()
                return

    def _report_blip(self) -> None:
        """Tell the log about a dropped line without crying wolf.

        A home router, a Wi-Fi access point or a mobile modem drops the
        connection for a few seconds several times an hour, and the bot rides
        those out on its own. Writing a warning for each one makes the journal
        useless: after a week it is impossible to see the one outage that
        mattered. So the first failures stay INFO and only a silence of several
        minutes becomes a warning.
        """

        count = self._consecutive_failures
        if count <= QUIET_FAILURES:
            logger.info(
                "Telegram не ответил на проверку связи (раз подряд: %s). "
                "Это обычный обрыв: бот не останавливается и подключится сам.",
                count,
            )
            return
        if count > QUIET_FAILURES + 1 and (count - QUIET_FAILURES) % 10 != 0:
            logger.debug("Telegram по-прежнему не отвечает (%s раз подряд).", count)
            return
        minutes = int(count * self._interval // 60)
        logger.warning(
            "Telegram не отвечает уже %s проверок подряд (примерно %s мин). "
            "Бот жив, продолжает ждать и подключится сам, как только сеть "
            "вернётся. Ничего делать не нужно.",
            count,
            minutes,
        )

    def stop(self) -> None:
        self._stopped.set()
