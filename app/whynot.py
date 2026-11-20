"""Why the bot cannot reach Telegram — one screen, in plain words.

The bot already writes a diagnosis into its journal the moment every route has
failed (look for the lines «Диагностика сети:»). Useful, but it asks one
question only: *does this address answer?* It cannot tell the two failures
apart that look identical in a log and are cured in completely different ways:

* the packets never arrive — the line is cut somewhere outside;
* the packets arrive but the secure connection is opened by somebody else on
  this very computer — an antivirus, a DPI-bypass tool, a leftover VPN client.

So this check asks the questions that separate them. It measures, in order:

1. whether the internet works at all (a neutral site, not Telegram);
2. whether a plain connection to Telegram's own address gets through — no
   encryption, nothing that can be intercepted, just whether the road exists;
3. whether the secure connection is then really made with Telegram, and **who
   issued the certificate** — a certificate signed by an antivirus instead of
   a public authority is the fingerprint of interception;
4. what is installed on the computer that sits in the traffic's way.

It changes nothing and fixes nothing. It only says where the break is.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
import ssl
import subprocess
import sys
import time

TELEGRAM_HOST = "api.telegram.org"
TELEGRAM_PORT = 443
# Telegram's own addresses. The first is the one its name resolves to today;
# the others belong to the same service and are here so that one filtered
# address does not decide the answer.
TELEGRAM_ADDRESSES = (
    "149.154.166.110",
    "149.154.167.220",
    "149.154.175.50",
)
# Anything but Telegram. If this answers and Telegram does not, the internet is
# working and Telegram specifically is being kept out.
CONTROL_HOSTS = ("ya.ru", "www.google.com", "cloudflare.com")
TIMEOUT = 10.0

# Programs that put themselves between a program and the network. Found on a
# Russian Windows PC more often than anywhere else: the tools that work around
# provider filters, and the antivirus suites that inspect secure traffic.
DPI_TOOLS = (
    "goodbyedpi",
    "goodbye-dpi",
    "winws",
    "zapret",
    "byedpi",
    "bye-dpi",
    "nohang",
    "ciadpi",
    "tpws",
    "nfqws",
    "powerdpi",
)
VPN_TOOLS = (
    "wireguard",
    "openvpn",
    "happ",
    "protonvpn",
    "nordvpn",
    "surfshark",
    "expressvpn",
    "tun2socks",
    "xray",
    "v2ray",
    "sing-box",
    "clash",
    "nekobox",
    "hiddify",
    "amnezia",
    "warp-svc",
)
# Antivirus suites that open secure connections on the computer's behalf. A
# certificate issued by one of these, for Telegram, is the whole answer.
ANTIVIRUS = (
    "avp",
    "klnagent",
    "ekrn",
    "egui",
    "drweb",
    "dwengine",
    "bdagent",
    "avastui",
    "avgui",
    "avguard",
    "ntrtscan",
    "sophos",
    "mcafee",
)
FILTER_DRIVERS = (
    "windivert",
    "npf",
    "npcap",
    "tap0901",
    "wintun",
    "tap-windows",
    "klflt",
    "klim6",
    "eamon",
    "ehdrv",
    "bdnetflt",
    "dwflt",
)
# Certificate issuers that mean «somebody on this computer is reading this».
FOREIGN_ISSUERS = (
    "kaspersky",
    "dr.web",
    "drweb",
    "eset",
    "avast",
    "avg ",
    "bitdefender",
    "sophos",
    "mcafee",
    "adguard",
    "certum",
)


def _seconds(start: float) -> str:
    return f"{time.monotonic() - start:.1f} с"


def _name_of(certificate: dict, field: str) -> str:
    """The readable part of a certificate subject or issuer."""

    try:
        for items in certificate[field]:
            for key, value in items:
                if (
                    key in ("commonName", "organizationName")
                    and value
                    and value != "None"
                ):
                    return str(value)
    except (KeyError, TypeError, ValueError):
        pass
    return "?"


async def raw_tcp(address: str, port: int = TELEGRAM_PORT) -> tuple[bool, str]:
    """Open a plain connection. No names, no encryption, nothing to intercept.

    If this fails, no amount of certificate fiddling will help: the road
    itself is closed.
    """

    started = time.monotonic()
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(address, port, family=family),
            timeout=TIMEOUT,
        )
    except TimeoutError:
        return False, f"нет ответа {TIMEOUT:.0f} с"
    except OSError as exc:
        return False, f"не получилось ({type(exc).__name__}: {exc})"[:110]
    elapsed = _seconds(started)
    with contextlib.suppress(OSError, TimeoutError):
        writer.close()
        await writer.wait_closed()
    return True, f"соединение установлено, {elapsed}"


async def tls_hello(address: str, host: str) -> tuple[bool, str, str, str]:
    """Make a secure connection and report who signed the certificate.

    Returns ``(worked, what happened, who it was made out to, who signed it)``.
    The issuer is the point: a public authority means the conversation really
    is with Telegram; an antivirus means the antivirus is in the middle.
    """

    started = time.monotonic()
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    context = ssl.create_default_context()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(
                address, TELEGRAM_PORT, ssl=context, server_hostname=host, family=family
            ),
            timeout=TIMEOUT,
        )
    except TimeoutError:
        return (
            False,
            f"защищённое соединение не открылось: нет ответа {TIMEOUT:.0f} с",
            "?",
            "?",
        )
    except ssl.SSLCertVerificationError as exc:
        # The name in the handshake did not match what came back: the classic
        # signature of a program answering in Telegram's place.
        return False, f"сертификат не подошёл ({exc.verify_message})"[:110], "?", "?"
    except (OSError, ssl.SSLError) as exc:
        return False, f"не получилось ({type(exc).__name__}: {exc})"[:110], "?", "?"

    subject = issuer = "?"
    with contextlib.suppress(Exception):
        certificate = writer.get_extra_info("peercert")
        subject = _name_of(certificate, "subject")
        issuer = _name_of(certificate, "issuer")
    elapsed = _seconds(started)

    answer = "пусто"
    try:
        writer.write(f"HEAD / HTTP/1.0\r\nHost: {host}\r\n\r\n".encode())
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=TIMEOUT)
        answer = line.decode("latin-1").strip() or "пусто"
    except (OSError, TimeoutError, ssl.SSLError):
        answer = "ответа не дождались"
    finally:
        with contextlib.suppress(OSError, TimeoutError):
            writer.close()
            await writer.wait_closed()
    return (
        True,
        f"защищённое соединение установлено, {elapsed}, ответ: {answer}",
        subject,
        issuer,
    )


async def control_check() -> tuple[str, str, str]:
    """Is the internet there at all? Ask a site that is not Telegram."""

    for host in CONTROL_HOSTS:
        try:
            addresses = await asyncio.to_thread(
                socket.getaddrinfo, host, 443, type=socket.SOCK_STREAM
            )
        except OSError:
            continue
        for info in addresses[:2]:
            address = info[4][0]
            worked, detail, _subject, issuer = await tls_hello(address, host)
            if worked:
                return host, f"интернет есть ({host}: {detail})", issuer
    return "", "интернета нет: ни один обычный сайт не отвечает", "?"


def _run(command: list[str]) -> str:
    try:
        done = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="cp866",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return (done.stdout or "") + (done.stderr or "")


def look_for_interceptors() -> list[str]:
    """What is installed on this computer that sits in the traffic's way."""

    if sys.platform != "win32":
        return []
    found: list[str] = []

    tasks = _run(["tasklist", "/FO", "CSV", "/NH"]).lower()
    for group, label in (
        (DPI_TOOLS, "программа обхода блокировок"),
        (VPN_TOOLS, "VPN-клиент"),
        (ANTIVIRUS, "антивирус"),
    ):
        hits = sorted({name for name in group if f'"{name}.exe"' in tasks})
        if hits:
            found.append(f"{label}: " + ", ".join(hits))

    drivers = _run(["driverquery", "/FO", "CSV", "/NH"]).lower()
    hits = sorted(
        {
            name
            for name in FILTER_DRIVERS
            if f'"{name}"' in drivers or f'"{name}' in drivers
        }
    )
    if hits:
        found.append("драйвер-фильтр трафика: " + ", ".join(hits))

    catalog = _run(["netsh", "winsock", "show", "catalog"])
    layered: list[str] = []
    for line in catalog.splitlines():
        stripped = line.split(":", 1)[-1].strip() if ":" in line else ""
        # The ordinary providers Windows ships with all begin «MSAFD» or
        # «RSVP». Anything else was installed by somebody.
        if (
            line.strip().startswith("Description:")
            and stripped
            and not stripped.upper().startswith(("MSAFD", "RSVP", "HYPER-V"))
        ):
            layered.append(stripped)
    if layered:
        found.append("перехватчик Winsock: " + ", ".join(sorted(set(layered))[:6]))

    proxy = _run(["netsh", "winhttp", "show", "proxy"]).strip()
    for line in proxy.splitlines():
        if "Proxy Server" in line and line.split(":", 1)[-1].strip() not in (
            "",
            "Direct access",
        ):
            found.append("системный прокси Windows: " + line.split(":", 1)[-1].strip())
    return found


def _is_foreign(issuer: str) -> bool:
    lowered = issuer.lower()
    return any(word in lowered for word in FOREIGN_ISSUERS)


async def investigate() -> str:
    lines: list[str] = []
    lines.append("ПОЧЕМУ БОТ НЕ ДОСТУЧАЛСЯ ДО TELEGRAM")
    lines.append("=" * 52)
    lines.append("")

    lines.append("1. Интернет вообще (обычный сайт, не Telegram)")
    control_host, control_detail, control_issuer = await control_check()
    lines.append(f"   {control_detail}")
    if _is_foreign(control_issuer):
        lines.append(f"   ВНИМАНИЕ: сертификат подписал «{control_issuer}»,")
        lines.append("   а не общественная организация. Значит, защищённый трафик")
        lines.append("   на этом компьютере кто-то разбирает.")
    lines.append("")

    lines.append("2. Что на компьютере стоит на пути трафика")
    interceptors = look_for_interceptors()
    if interceptors:
        for item in interceptors:
            lines.append(f"   • {item}")
    else:
        lines.append("   ничего не найдено: ни программы обхода блокировок,")
        lines.append("   ни драйвера-фильтра, ни перехватчика Winsock.")
    lines.append("")

    lines.append("3. Дорога до Telegram (обычное соединение, без шифрования)")
    road_is_open = False
    for address in TELEGRAM_ADDRESSES:
        worked, detail = await raw_tcp(address)
        lines.append(f"   {address}: {detail}")
        road_is_open = road_is_open or worked
    lines.append("")

    lines.append("4. Защищённое соединение с Telegram")
    telegram_ok = False
    issuer = "?"
    subject = "?"
    for address in TELEGRAM_ADDRESSES:
        worked, detail, subject, issuer = await tls_hello(address, TELEGRAM_HOST)
        lines.append(f"   {address}: {detail}")
        if worked:
            telegram_ok = True
            break
    if telegram_ok:
        lines.append(f"   сертификат выдан: {subject}")
        lines.append(f"   кем подписан: {issuer}")
    lines.append("")

    lines.append("=" * 52)
    lines.append("ЧТО ЭТО ЗНАЧИТ")
    lines.append("")

    if telegram_ok and _is_foreign(issuer):
        lines.append("Связь есть, но сертификат Telegram подменила программа на")
        lines.append(f"этом компьютере — «{issuer}». Она разбирает защищённый")
        lines.append("трафик, и бот с ней не договаривается.")
        lines.append("Что делать: добавьте python.exe в исключения антивируса")
        lines.append("или выключите в нём проверку защищённых соединений")
        lines.append("(часто называется «Secure Connection», «HTTPS-сканирование»,")
        lines.append("«Защищённые соединения»).")
    elif telegram_ok:
        lines.append("Telegram доступен. Значит, помеха была временной — бот")
        lines.append("подключается сам и делает это каждые 5–60 секунд;")
        lines.append("перезапускать его не нужно.")
    elif not control_host:
        lines.append("Интернета на компьютере нет вовсе: обычные сайты не")
        lines.append("отвечают. Тут ни бот, ни Telegram ни при чём — проверьте")
        lines.append("подключение (кабель, Wi-Fi, роутер).")
    elif not road_is_open:
        lines.append("До обычных сайтов дорога есть, до Telegram — нет: даже")
        lines.append("простое соединение без шифрования не устанавливается.")
        lines.append("Значит, путь к Telegram закрыт.")
        if interceptors:
            lines.append("")
            lines.append("При этом на компьютере найдено то, что может его")
            lines.append("закрывать (см. пункт 2). Первым делом закройте эти")
            lines.append("программы и дайте боту минуту — он подключится сам.")
        lines.append("")
        lines.append("Если это провайдер, бот умеет работать через прокси:")
        lines.append("запустите SET-PROXY.cmd и укажите адрес socks5://…")
        lines.append("Прокси боту нужен не всегда — только когда прямой путь")
        lines.append("именно закрыт.")
    else:
        lines.append("Необычный случай: обычное соединение до Telegram доходит,")
        lines.append("а защищённое — нет. Это похоже на фильтр, который")
        lines.append("разбирает трафик по дороге, или на антивирус.")
        lines.append("Проверьте пункт 2 и выключите проверку защищённых")
        lines.append("соединений в антивирусе.")
    lines.append("")
    lines.append("Бот не сломан: он продолжает пытаться и подключится сразу,")
    lines.append("как только путь появится. Перезапуск не требуется.")
    return "\n".join(lines)


def main() -> None:
    print(asyncio.run(investigate()))
    if sys.platform == "win32":
        print()
        input("Нажмите Enter, чтобы закрыть.")


if __name__ == "__main__":
    main()
