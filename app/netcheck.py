"""Find out why Telegram does not answer, and which way around it does.

A bot that prints «прямое подключение недоступно ()» is useless: the empty
brackets hide the only thing that matters. Three things usually break on a home
line in Russia, and they are repaired differently:

* the provider's DNS lies or stays silent — then the address has to be asked
  from a public DNS server and used directly, with the same name in the TLS
  handshake;
* the IPv4 route to Telegram is filtered while IPv6 is left alone — then the
  connection has to be made over IPv6;
* the connection is throttled but alive — then it only needs more patience.

This module answers those questions without any external program: a DNS query
is a small UDP packet, everything else is ordinary sockets. Run it directly for
a printed report:

    python -m app.netcheck
"""

from __future__ import annotations

import asyncio
import logging
import socket
import ssl
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path

TELEGRAM_HOST = "api.telegram.org"
TELEGRAM_PORT = 443
# Cloudflare, Google, Yandex, Google again: the first one that answers wins,
# so a provider that blocks one of them does not stop the check.
PUBLIC_DNS_SERVERS: tuple[str, ...] = ("1.1.1.1", "8.8.8.8", "77.88.8.8", "8.8.4.4")
DNS_TIMEOUT = 3.0
CONNECT_TIMEOUT = 8.0

_TYPE_A = 1
_TYPE_AAAA = 28


def _encode_name(host: str) -> bytes:
    encoded = b"".join(
        bytes([len(part)]) + part.encode("idna") for part in host.split(".") if part
    )
    return encoded + b"\x00"


def _skip_name(data: bytes, offset: int) -> int:
    """Walk past a DNS name, which may end in a compression pointer."""

    while offset < len(data):
        length = data[offset]
        if length == 0:
            return offset + 1
        if length & 0xC0 == 0xC0:
            return offset + 2
        offset += 1 + length
    return offset


def parse_dns_answers(data: bytes, wanted_type: int) -> list[str]:
    """Read the addresses out of a DNS answer packet."""

    if len(data) < 12:
        return []
    questions, answers = struct.unpack("!HH", data[4:8])
    offset = 12
    for _ in range(questions):
        offset = _skip_name(data, offset) + 4
    found: list[str] = []
    for _ in range(answers):
        offset = _skip_name(data, offset)
        if offset + 10 > len(data):
            break
        record_type, _klass, _ttl, length = struct.unpack(
            "!HHIH", data[offset : offset + 10]
        )
        offset += 10
        payload = data[offset : offset + length]
        offset += length
        if record_type == wanted_type == _TYPE_A and length == 4:
            found.append(socket.inet_ntop(socket.AF_INET, payload))
        elif record_type == wanted_type == _TYPE_AAAA and length == 16:
            found.append(socket.inet_ntop(socket.AF_INET6, payload))
    return found


def dns_query(
    server: str,
    host: str = TELEGRAM_HOST,
    record_type: int = _TYPE_A,
    timeout: float = DNS_TIMEOUT,
) -> list[str]:
    """Ask one DNS server for the address of ``host``. Empty list on failure."""

    packet = (
        struct.pack("!HHHHHH", 0x2A1B, 0x0100, 1, 0, 0, 0)
        + _encode_name(host)
        + struct.pack("!HH", record_type, 1)
    )
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as channel:
        channel.settimeout(timeout)
        channel.sendto(packet, (server, 53))
        data, _address = channel.recvfrom(2048)
    return parse_dns_answers(data, record_type)


def system_addresses(host: str = TELEGRAM_HOST) -> list[str]:
    """What this computer's own DNS says; empty when resolution fails."""

    found: list[str] = []
    try:
        records = socket.getaddrinfo(host, TELEGRAM_PORT, proto=socket.IPPROTO_TCP)
    except OSError:
        return found
    for family, _kind, _proto, _canon, address in records:
        if family in (socket.AF_INET, socket.AF_INET6):
            ip = address[0]
            if ip not in found:
                found.append(ip)
    return found


async def public_dns_addresses(
    host: str = TELEGRAM_HOST, timeout: float = DNS_TIMEOUT
) -> tuple[list[str], str | None]:
    """Addresses from a public DNS server, plus the name of the one that answered."""

    for server in PUBLIC_DNS_SERVERS:
        collected: list[str] = []
        for record_type in (_TYPE_A, _TYPE_AAAA):
            try:
                found = await asyncio.to_thread(
                    dns_query, server, host, record_type, timeout
                )
            except (OSError, ValueError, struct.error):
                continue
            collected.extend(ip for ip in found if ip not in collected)
        if collected:
            return collected, server
    return [], None


async def discover_addresses(
    host: str = TELEGRAM_HOST,
) -> tuple[list[str], list[str]]:
    """Return (what this computer sees, other addresses worth trying).

    The second list only holds addresses the computer's own DNS did not give,
    because trying an address it already tried is wasted patience: if that
    address is filtered, it is filtered either way.
    """

    own = await asyncio.to_thread(system_addresses, host)
    foreign, _server = await public_dns_addresses(host)
    extra = [ip for ip in foreign if ip not in own]
    return own, extra


async def probe_address(
    address: str,
    host: str = TELEGRAM_HOST,
    timeout: float = CONNECT_TIMEOUT,
) -> str:
    """Connect to one address and say, in words, what came of it."""

    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    context = ssl.create_default_context()
    started = time.monotonic()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(
                address,
                TELEGRAM_PORT,
                ssl=context,
                server_hostname=host,
                family=family,
            ),
            timeout=timeout,
        )
    except TimeoutError:
        return f"нет ответа {timeout:.0f} с"
    except (OSError, ssl.SSLError) as exc:
        return f"не получилось ({type(exc).__name__}: {exc})"[:120]
    elapsed = time.monotonic() - started
    try:
        writer.write(
            f"HEAD / HTTP/1.0\r\nHost: {host}\r\nUser-Agent: vin-bot\r\n\r\n".encode()
        )
        await writer.drain()
        answer = await asyncio.wait_for(reader.readline(), timeout=timeout)
    except (OSError, TimeoutError, ssl.SSLError):
        answer = b""
    finally:
        writer.close()
        with_context = getattr(writer, "wait_closed", None)
        if with_context is not None:
            try:
                await with_context()
            except (OSError, TimeoutError):
                pass
    line = answer.decode("latin-1").strip() if answer else "пусто"
    return f"TLS и HTTPS работают, {elapsed:.1f} с, ответ: {line}"


def read_env_proxy(path: str | Path = ".env") -> str | None:
    """Return ``TELEGRAM_PROXY`` as it is written in the .env file, if at all.

    Read by hand rather than through python-dotenv: this module has to keep
    working on a machine where nothing else works, and a proxy line is a single
    ``name=value`` pair, not a language.
    """

    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        if name.strip() != "TELEGRAM_PROXY":
            continue
        value = value.strip().strip('"').strip("'")
        return value or None
    return None


class _QuietEofReceived(logging.Filter):
    """Hide one asyncio complaint that would otherwise frighten the reader.

    Speaking TLS over an open socket and hanging up afterwards makes asyncio log
    «returning true from eof_received() has no effect when using ssl». Nothing
    is broken: the conversation is over and the socket is closed on purpose. For
    somebody reading NET-CHECK the English line is pure noise.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return "eof_received" not in record.getMessage()


async def probe_proxy(proxy: str, timeout: float = CONNECT_TIMEOUT) -> str:
    """Say, in words, whether the bot can reach Telegram through this proxy.

    A proxy that accepts the connection proves nothing: the bot needs a real
    TLS conversation with Telegram through it, so that is what is measured. A
    proxy that answers with a certificate of its own is reported separately —
    it is listening, but it is reading the traffic, not carrying it.
    """

    keeper = _QuietEofReceived()
    asyncio_logger = logging.getLogger("asyncio")
    asyncio_logger.addFilter(keeper)
    try:
        return await _measure_proxy(proxy, timeout)
    finally:
        asyncio_logger.removeFilter(keeper)


async def _measure_proxy(proxy: str, timeout: float = CONNECT_TIMEOUT) -> str:
    """Ask one proxy for Telegram and report what came of it."""

    scheme, _, address = proxy.partition("://")
    if scheme not in ("socks5", "http", "https"):
        return "не проверяется (годятся socks5:// и http://)"
    host, _, port_text = address.rpartition(":")
    try:
        port = int(port_text)
    except ValueError:
        return "не проверяется (в адресе нет порта)"
    if not 1 <= port <= 65535 or not host:
        return "не проверяется (непонятный адрес)"

    started = time.monotonic()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
    except TimeoutError:
        return f"нет ответа {timeout:.0f} с"
    except OSError as exc:
        return f"не отвечает ({type(exc).__name__}: {exc})"[:120]

    try:
        if scheme == "socks5":
            writer.write(b"\x05\x01\x00")
            await writer.drain()
            greeting = await asyncio.wait_for(reader.readexactly(2), timeout=timeout)
            if greeting[0] != 5 or greeting[1] != 0:
                if greeting[1] == 255:
                    return "не годится (прокси требует пароль)"
                return f"не годится (прокси ответил {greeting.hex()})"
            request = (
                b"\x05\x01\x00\x03"
                + bytes([len(TELEGRAM_HOST)])
                + TELEGRAM_HOST.encode()
                + struct.pack("!H", TELEGRAM_PORT)
            )
            writer.write(request)
            await writer.drain()
            reply = await asyncio.wait_for(reader.readexactly(4), timeout=timeout)
            if reply[1] != 0:
                return f"не пустил к Telegram (код {reply[1]})"
            if reply[3] == 1:
                await reader.readexactly(4)
            elif reply[3] == 3:
                await reader.readexactly((await reader.readexactly(1))[0])
            elif reply[3] == 4:
                await reader.readexactly(16)
            await reader.readexactly(2)
        else:
            writer.write(
                f"CONNECT {TELEGRAM_HOST}:{TELEGRAM_PORT} HTTP/1.1\r\n"
                f"Host: {TELEGRAM_HOST}:{TELEGRAM_PORT}\r\n\r\n".encode()
            )
            await writer.drain()
            answer = await asyncio.wait_for(
                reader.readuntil(b"\r\n\r\n"), timeout=timeout
            )
            status = answer.split(b"\r\n", 1)[0].decode("latin-1")
            if " 200" not in status:
                return f"не пустил к Telegram ({status})"

        context = ssl.create_default_context()
        transport = writer.transport
        # The protocol has to be remembered before start_tls: afterwards the
        # transport reports the SSL protocol, which cannot be written through.
        protocol = transport.get_protocol()
        new_transport = await asyncio.wait_for(
            asyncio.get_event_loop().start_tls(
                transport,
                protocol,
                context,
                server_hostname=TELEGRAM_HOST,
            ),
            timeout=timeout,
        )
        secure = asyncio.StreamWriter(
            new_transport,
            protocol,
            reader,
            asyncio.get_event_loop(),
        )
        secure.write(
            f"HEAD / HTTP/1.0\r\nHost: {TELEGRAM_HOST}\r\nUser-Agent: vin-bot\r\n\r\n".encode()
        )
        await secure.drain()
        line = (
            (await asyncio.wait_for(reader.readline(), timeout=timeout))
            .decode("latin-1")
            .strip()
        )
    except TimeoutError:
        return f"оборвал соединение (нет ответа {timeout:.0f} с)"
    except ssl.SSLCertVerificationError:
        return "не годится: подменяет сертификат Telegram — через него нельзя"
    except (OSError, ssl.SSLError, asyncio.IncompleteReadError) as exc:
        return f"оборвал соединение ({type(exc).__name__})"[:120]
    finally:
        writer.close()

    elapsed = time.monotonic() - started
    return f"работает: TLS и HTTPS идут, {elapsed:.1f} с, ответ: {line or 'пусто'}"


@dataclass
class Report:
    """Everything one run of the check found out."""

    own: list[str] = field(default_factory=list)
    foreign: list[str] = field(default_factory=list)
    dns_server: str | None = None
    probes: dict[str, str] = field(default_factory=dict)
    working: list[str] = field(default_factory=list)
    proxy: str | None = None
    proxy_result: str | None = None

    def as_text(self) -> str:
        lines = [f"Проверка связи с {TELEGRAM_HOST}", ""]
        lines.append(
            "1. DNS компьютера: "
            + (", ".join(self.own) if self.own else "не отвечает или пусто")
        )
        lines.append(
            "2. Публичный DNS"
            + (f" ({self.dns_server}): " if self.dns_server else ": ")
            + (", ".join(self.foreign) if self.foreign else "не отвечает")
        )
        for number, (address, result) in enumerate(self.probes.items(), start=3):
            lines.append(f"{number}. {address}: {result}")
        if self.proxy:
            lines.append(
                f"{len(self.probes) + 3}. Прокси из .env ({self.proxy}): "
                f"{self.proxy_result}"
            )
        lines.append("")
        proxy_works = bool(
            self.proxy_result and self.proxy_result.startswith("работает")
        )
        if self.working:
            lines.append(
                "Вывод: Telegram доступен по адресу " + ", ".join(self.working)
            )
            if self.proxy and proxy_works:
                lines.append(
                    "Бот подключится сам и напрямую, а прокси из .env останется"
                )
                lines.append(
                    "запасным путём — уберите строку TELEGRAM_PROXY, и его не будет."
                )
            elif self.proxy:
                lines.append("Прокси из .env при этом не работает — сотрите строку")
                lines.append("TELEGRAM_PROXY, чтобы бот не тратил на него время.")
            else:
                lines.append("Бот подключится сам — ничего делать не нужно.")
        elif proxy_works:
            # A working way out outranks the diagnosis of the way that is
            # broken: the bot will run, which is the only thing that matters.
            lines.append(
                "Вывод: напрямую Telegram не отвечает, но прокси из .env работает."
            )
            lines.append(
                "Бот подключится через него сам — ничего больше делать не нужно."
            )
        elif not self.own and not self.foreign:
            lines.append("Вывод: имя api.telegram.org не превращается ни в один адрес.")
            lines.append("Проверьте интернет и DNS провайдера.")
        else:
            lines.append(
                "Вывод: ни один адрес не отвечает. Соединение обрывают на сети,"
            )
            lines.append(
                "а не на компьютере: ни DNS, ни IPv6, ни прямой IP тут не помогут."
            )
            lines.append("Нужен любой туннель (прокси в .env) либо сервер за пределами")
            lines.append("заблокированной сети. Сам бот от этого не зависит: он просто")
            lines.append("будет подключаться, как только путь появится.")
        return "\n".join(lines)


async def diagnose() -> Report:
    """Ask the network questions and collect the answers."""

    report = Report()
    report.own = await asyncio.to_thread(system_addresses)
    foreign, server = await public_dns_addresses()
    report.foreign = foreign
    report.dns_server = server
    for address in report.own + [ip for ip in foreign if ip not in report.own]:
        result = await probe_address(address)
        report.probes[address] = result
        if result.startswith("TLS"):
            report.working.append(address)
    proxy = read_env_proxy()
    if proxy:
        report.proxy = proxy
        report.proxy_result = await probe_proxy(proxy)
    return report


def main() -> None:
    print(asyncio.run(diagnose()).as_text())


if __name__ == "__main__":
    main()
