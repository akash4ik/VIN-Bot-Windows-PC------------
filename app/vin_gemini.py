"""A second opinion from Gemini, when he has paid for one.

He brought a ready-made project that sends the photograph to Google Gemini
and prints whatever comes back. The idea is sound — a vision model reads a
hard photograph better than Tesseract does — but the project as written
would have made things worse, and it is worth saying why:

* it asks for the alphabet ``A-H, J-N, P-R-T-V-Y``, which leaves out S, U, W,
  X and Z. Those are five perfectly ordinary VIN characters, and a Mercedes
  VIN starts with a W. Asked for a wrong alphabet, the model obliges.
* it prints the answer with no check digit and no way to correct a
  character, so one wrong letter becomes the VIN on record.
* its web page sends ``inline_data`` outside ``parts``, where the API does
  not look for it, so the page would have failed outright.
* it promises «100 % accuracy», which no reader delivers.

So the key is wired into his bot instead, next to the bot token, and the
model is asked under the same rules the local engine keeps: the right
alphabet, no guessing a character that cannot be read, and a check digit
that has to add up before the answer is believed.

The client talks to the REST endpoint over ``aiohttp``, which the bot already
ships, so no new package has to be installed on his PC. Without a key — or
without the network — nothing here runs and the bot reads locally exactly as
it always has.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
from collections import Counter
from dataclasses import dataclass, replace

import aiohttp

from .ocr import (
    VIN_LENGTH,
    mask_vin,
    vin_is_believable,
)
from .vin_pipeline import MAX_PICTURES, cloud_pictures

logger = logging.getLogger(__name__)

# Google switches its older models off on a published date, and a switched-off
# model answers 404. That is precisely how this bot once lost its second
# reader without anybody noticing: the name here was «gemini-2.0-flash»,
# retired on 1 June 2026, and the failure was only a warning in the journal
# while the bot went on reading every hard photograph by itself. So three
# things are now true. The default is a model that exists today. A 404 makes
# the client ask the API which models this key may use and carry on with one
# of those. And a refusal that will not repair itself is written as an error,
# in plain words, naming the repair.
DEFAULT_MODEL = "gemini-3.5-flash-lite"
# Tried in this order when the model above is refused. The last name is a
# Google-maintained alias that always points at the current Flash release, so
# this keeps working even after the next rename.
FALLBACK_MODELS = ("gemini-flash-latest",)
# Models this bot will not use, however they are reached — the default, a
# fallback, a name written in .env, or one Google offers this key.
#
# «gemini-3.6-flash» was in this list and was taken out: Google retires it on
# 19 November 2026, and a fallback that dies on a published date is worse than
# no fallback — it quietly becomes the model the bot depends on.
#
# «gemini-3.8-flash» is out because it did not earn its place, and there is a
# journal that says so. Asked to answer one word it thought for 46 seconds and
# answered nothing. On a real photograph it spent its output on thinking and
# cut its own answer off at 56 characters. «gemini-3.5-flash-lite» was handed
# the same photograph and read the VIN correctly, at 0.95. A model that is
# slower and answers less completely is not a fallback for one that works.
BANNED_MODELS = frozenset({"gemini-3.6-flash", "gemini-3.8-flash"})
ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
MODELS_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_TIMEOUT = 45.0
# Refusals that will never fix themselves: the key is wrong or lacks access.
# A timeout or a dropped connection is not one of these — those come back.
PERMANENT_STATUS = frozenset({400, 401, 403})
# The key is fine and the model is fine: the allowance behind them is spent.
# On the free tier this arrives within minutes of switching the cloud on, and
# it refills by itself, so it must never be reported as a broken reader.
QUOTA_STATUS = 429
# The model exists nowhere any more: renamed, retired, switched off.
GONE_STATUS = 404

#: What last went wrong with the cloud, in words, for the status screen.
last_problem: str = ""
#: The model that answered, so the same dead name is not tried twice.
_working_model: str = ""

# Exactly the characters a VIN may contain. I, O and Q are forbidden by the
# standard, precisely because a person copying a code reads them as 1, 0 and 2.
_VIN_SHAPE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
_SEPARATORS = re.compile(r"[\s\-–—_.]")

PROMPT = """You read vehicle identification numbers (VIN) from photographs taken
by a courier in a hurry: in a dark warehouse, in bright sun, through a dirty
windscreen. The picture is often bad. The code is still there.

You are given SEVERAL pictures. They are all the SAME frame, prepared
differently: the original, one with contrast stretched, one sharpened, one
reduced to black and white, and tight crops of the places that look like a
line of characters. No two of them show the code equally well. Use whichever
picture makes a character readable, and say in notes which one it was.

A VIN is exactly 17 characters: digits 0-9 and the letters
A-H, J-N, P, R, S, T, U, V, W, X, Y, Z. The letters I, O and Q NEVER occur in
a VIN - if you think you see one, it is a 1, a 0 or a 2.

Where a VIN hides, and what spoils it there:
* a plate or a sticker in the door opening - usually clear, but the code may
  be tilted, curved, scratched, or half covered by a rubber seal;
* the lower corner of the windscreen, photographed from outside - the code is
  etched into glass, so it is low-contrast, often washed out by the sky, and
  a wiper, dirt, snow, a sticker or the dashboard edge may cover part of it;
* under the bonnet: the suspension turret, the firewall, a riveted plate;
* a paper invoice or a waybill - printed small, sometimes turned 90 degrees,
  often sitting in a table next to other long numbers.

Look at the WHOLE picture before you decide. Then:

1. Find every place that could carry a 17-character code and read each one.
   Read the characters one at a time, left to right.
2. Ignore spaces, hyphens and any other separators between the characters.
3. DO NOT GUESS. If a character is covered, washed out or unreadable, write
   "?" in its place. A gap can be filled by a person standing at the car; a
   plausible wrong letter cannot, because it looks like it was read.
4. These pairs are constantly confused: O/0, I/1/L, Q/0/2, S/5, B/8, Z/2,
   G/6, D/0, U/V, A/4, E/F, C/G, M/N, W/VV. Correct one only when the shape
   is unambiguous - otherwise keep what you saw and lower your confidence.
5. Judge the photograph: glare, blur, tilt and contrast, each from 0.0 (none)
   to 1.0 (severe). For contrast 1.0 means strong contrast, which is good.
6. If no 17-character code can be read anywhere, return null for best_vin and
   say in ONE short Russian sentence what to photograph instead.

Answer with JSON only - no prose, no markdown fences:
{"best_vin": "<17 characters, or null>",
 "candidates": [{"vin": "<17 characters>", "confidence": 0.0,
                  "where": "<where on the picture>"}],
 "partial_vin": "<17 characters with ? where unreadable, or null>",
 "image_quality": {"glare": 0.0, "blur": 0.0, "angle": 0.0, "contrast": 0.0},
 "retake_instructions": "<one short Russian sentence, or empty>",
 "notes": "<what helped or hindered, in one short sentence>"}"""


@dataclass(frozen=True, slots=True)
class GeminiReading:
    """What the model said about one photograph."""

    vin: str | None
    candidates: tuple[str, ...] = ()
    #: Each code the model offered with how sure it said it was, 0.0 to 1.0.
    scores: tuple[tuple[str, float], ...] = ()
    partial: str | None = None
    instructions: str = ""
    notes: str = ""
    raw: str = ""

    @property
    def believable(self) -> bool:
        """Whether the answer is a code that could be a real VIN.

        The model is asked not to guess, but it is a language model and it
        does complete patterns. Nothing it says is used until it has the
        shape of a VIN and, where the maker carries one, a ninth character
        that adds up from the other sixteen.

        «Where the maker carries one» is the part that mattered. Ford of
        Europe writes the model code at the ninth place, not a check digit —
        a Transit carries «R» there. Checking it as a check digit called the
        correct code «не годится» and handed the person a piece of noise
        instead, which is worse than reading nothing.
        """

        return bool(self.vin) and vin_is_believable(self.vin)

    @property
    def confidence(self) -> float:
        """How sure the model said it was about the code it settled on, 0.0 to 1.0."""

        for code, score in self.scores:
            if code == self.vin:
                return score
        return 0.0

    def best_code(self) -> tuple[str | None, float]:
        """The most believable of the codes on offer, and its confidence.

        Of everything the model offered, only codes that could be real VINs
        are considered at all: seventeen characters a VIN may hold, and a
        ninth character that adds up where the maker carries a check digit.
        Among those, the surest wins; when two are equally sure, the one more
        readings agree on wins, because a code seen twice is likelier than a
        code seen once. Returns ``(None, 0.0)`` when nothing survives.
        """

        tally = Counter(self.candidates)
        usable = [
            (code, confidence)
            for code, confidence in self.scores
            if vin_is_believable(code)
        ]
        if not usable:
            return None, 0.0
        best = max(usable, key=lambda item: (item[1], tally[item[0]]))
        return best[0], best[1]


def _clean(text: str) -> str:
    """Strip separators and markdown fences from a model's answer."""

    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:]
    return stripped.strip()


def _as_confidence(value: object) -> float:
    """Read a confidence the model wrote, whether it said 0.85 or 85."""

    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if number > 1.0:
        number = number / 100.0
    return min(1.0, max(0.0, number))


def _scored(value: object) -> tuple[tuple[str, float], ...]:
    """Keep only the answers that have the shape of a VIN, with confidence.

    A model is not above offering a code twice, and it is not above writing
    its confidence as a percentage. Both are settled here: duplicates count
    once, and 85 means the same as 0.85.
    """

    if not isinstance(value, list):
        return ()
    found: dict[str, float] = {}
    for item in value:
        confidence = 0.0
        if isinstance(item, dict):
            raw = item.get("vin") or item.get("raw") or item.get("normalized")
            confidence = _as_confidence(item.get("confidence"))
        else:
            raw = item
        if not isinstance(raw, str):
            continue
        compact = _SEPARATORS.sub("", raw.upper())
        if len(compact) == VIN_LENGTH and _VIN_SHAPE.match(compact):
            found.setdefault(compact, confidence)
    return tuple(found.items())


def _codes(value: object) -> tuple[str, ...]:
    """Keep only the answers that have the shape of a VIN."""

    return tuple(code for code, _confidence in _scored(value))


def _first_json_object(text: str) -> object:
    """Read the first JSON value out of an answer that may carry more.

    ``json.loads`` refuses a string that has anything after the value, and a
    model that appends a remark after its JSON therefore looks broken when it
    is only untidy. Taking the first complete value is what was meant.
    """

    try:
        return json.loads(text)
    except ValueError:
        pass
    decoder = json.JSONDecoder()
    value, _end = decoder.raw_decode(text)
    return value


#: A whole code inside quotes, as the model writes it.
_CODE_IN_QUOTES = re.compile(r'"([A-HJ-NPR-Z0-9]{17})"')
#: The same for a partial reading, where a "?" stands for an unread character.
_PARTIAL_IN_QUOTES = re.compile(r'"([A-HJ-NPR-Z0-9?]{17})"')


def _salvage(text: str) -> dict | None:
    """Pick the codes out of an answer that was cut off mid-JSON.

    Nothing is invented here and nothing is guessed: a code is taken only
    when the model wrote all seventeen of its characters inside quotes before
    the answer stopped. Anything shorter is left alone, because filling in a
    character is precisely what a VIN must never have done to it.
    """

    if not text.strip():
        return None

    best = None
    match = re.search(r'"best_vin"\s*:\s*"([A-HJ-NPR-Z0-9]{17})"', text)
    if match:
        best = match.group(1)

    partial = None
    match = re.search(r'"partial_vin"\s*:\s*"([A-HJ-NPR-Z0-9?]{17})"', text)
    if match:
        partial = match.group(1)

    codes = _CODE_IN_QUOTES.findall(text)
    if not best and not codes:
        return None

    found: dict = {"best_vin": best, "partial_vin": partial}
    if codes:
        found["candidates"] = [
            {"vin": code, "confidence": 0.5} for code in dict.fromkeys(codes)
        ]
    return found


def parse_answer(text: str) -> GeminiReading:
    """Turn the model's JSON into a reading, or into nothing at all."""

    cleaned = _clean(text)
    try:
        body = _first_json_object(cleaned)
    except (ValueError, TypeError):
        # The answer was cut short. Whatever the model managed to write is
        # still its answer, and a code it already read is worth more than a
        # shrug — so it is picked out of the wreckage rather than invented.
        body = _salvage(cleaned)
        if body is None:
            raise
        logger.warning("Ответ Gemini оборван — вычитал из него то, что успело прийти")
    if not isinstance(body, dict):
        raise TypeError("ответ не является объектом")

    vin: str | None = None
    raw_vin = body.get("best_vin")
    if isinstance(raw_vin, str):
        compact = _SEPARATORS.sub("", raw_vin.upper())
        if len(compact) == VIN_LENGTH and _VIN_SHAPE.match(compact):
            vin = compact

    partial: str | None = None
    raw_partial = body.get("partial_vin")
    if isinstance(raw_partial, str):
        compact = _SEPARATORS.sub("", raw_partial.upper())
        # A «?» is allowed here on purpose: it is the model saying it could
        # not read a character, which is exactly what it was asked to do.
        if len(compact) == VIN_LENGTH and re.fullmatch(r"[A-HJ-NPR-Z0-9?]+", compact):
            partial = compact

    notes = str(body.get("notes") or "")
    instructions = str(body.get("retake_instructions") or "")
    scores = _scored(body.get("candidates"))
    if vin is not None:
        own = _as_confidence(body.get("confidence"))
        known = dict(scores)
        # A confidence written beside the code is more specific than one
        # written beside the answer, and it is the one the model nearly always
        # writes — the answer often carries none at all. Taking the top-level
        # number unconditionally turned a code the model was ninety-five per
        # cent sure of into one it was nought per cent sure of, and a reading
        # that sure of nothing loses to any local guess.
        scores = tuple(
            (code, known.get(code, own) if code == vin else known.get(code, 0.0))
            for code, _ in scores
        ) or ((vin, own),)
    return GeminiReading(
        vin=vin,
        candidates=_codes(body.get("candidates")),
        scores=scores,
        partial=partial,
        instructions=instructions,
        notes=notes,
        raw=text,
    )


def _mentions_thinking(text: str) -> bool:
    """Whether Google's refusal is about the thinking setting."""

    return "thinking" in text.lower()


def _answer_text(text: str) -> str:
    """The answer out of the API's envelope, and only the answer.

    Two things go wrong here, and both were seen in a real journal. A model
    that thinks before it answers returns its thinking as extra parts, and
    gluing those onto the answer produces something that is no longer JSON —
    the journal read «Extra data: line 1 column 3». And an answer cut short
    by the token limit ends mid-sentence, which read as «Unterminated
    string». Both are reported here rather than being passed on as a JSON
    error nobody can act on.
    """

    body = json.loads(text)
    candidate = body["candidates"][0]
    reason = str(candidate.get("finishReason") or "")
    if reason and reason not in ("STOP", "MAX_TOKENS"):
        logger.warning("Gemini закончил ответ с причиной %s", reason)
    if reason == "MAX_TOKENS":
        logger.warning(
            "Ответ Gemini обрезан по лимиту токенов — модель не договорила"
        )

    parts = candidate["content"]["parts"]
    # Thinking parts carry the model's reasoning, not its answer: they are
    # marked, and they must not end up inside the JSON.
    answer = "".join(
        str(part.get("text", ""))
        for part in parts
        if not part.get("thought") and part.get("text") is not None
    )
    if not answer.strip():
        raise ValueError("ответ модели пуст")
    return answer


def _first_error_line(text: str) -> str:
    """Google's own wording out of an error answer, if there is any."""

    try:
        body = json.loads(text)
        message = body.get("error", {}).get("message", "")
        return str(message).strip().splitlines()[0][:300]
    except (AttributeError, IndexError, TypeError, ValueError):
        return text.strip().replace("\n", " ")[:300]


async def _request(
    api_key: str,
    model: str,
    payload: dict,
    timeout: float,
    proxy: str = "",
) -> tuple[int, str]:
    """One request to one model. Returns ``(status, body)``; 0 for no answer."""

    url = ENDPOINT.format(model=model)
    try:
        async with (
            aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=timeout),
                proxy=proxy or None,
            ) as session,
            session.post(url, params={"key": api_key}, json=payload) as response,
        ):
            return response.status, await response.text()
    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
        # Some of these carry no message at all, and «Gemini недоступен: »
        # with nothing after it tells nobody anything. Name the failure when
        # it will not name itself.
        detail = str(exc).strip() or type(exc).__name__
        logger.warning("Gemini недоступен: %s", detail)
        return 0, detail


async def list_models(
    api_key: str, *, timeout: float = DEFAULT_TIMEOUT, proxy: str = ""
) -> list[str]:
    """Ask which models this key may use with pictures.

    Cheaper than guessing. When Google retires a name it also names the
    replacement, and this list is where that answer lives; asking for it costs
    one small request only on the day a model disappears.
    """

    if not api_key:
        return []
    try:
        async with (
            aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=timeout),
                proxy=proxy or None,
            ) as session,
            session.get(MODELS_ENDPOINT, params={"key": api_key}) as response,
        ):
            if response.status != 200:
                return []
            body = await response.json()
    except (aiohttp.ClientError, TimeoutError, ValueError):
        return []

    names: list[str] = []
    for item in body.get("models") or []:
        name = str(item.get("name", "")).removeprefix("models/")
        methods = item.get("supportedGenerationMethods") or []
        if name and "generateContent" in methods:
            names.append(name)
    return names


def _version(name: str) -> float:
    found = re.findall(r"\d+(?:\.\d+)?", name)
    return float(found[0]) if found else 0.0


def pick_flash_model(names: list[str], *, exclude: tuple[str, ...] = ()) -> str | None:
    """The newest picture-taking Flash model in the list, if there is one.

    Specialised models are skipped: one that only speaks, only draws or only
    reads a screen would answer, and answer wrongly.
    """

    usable = [
        name
        for name in names
        if "flash" in name
        and name not in exclude
        and name not in BANNED_MODELS
        and "preview" not in name
        and not name.endswith(("-tts", "-live", "-image", "-transcribe"))
    ]
    if not usable:
        return None
    # A full Flash model reads better than a lite one, so a lite name is only
    # taken when the key is offered nothing better.
    full = [name for name in usable if "lite" not in name]
    return max(full or usable, key=_version)


def _candidate_models(configured: str) -> list[str]:
    """The model to ask first, then the ones to fall back on."""

    ordered: list[str] = []
    for name in (_working_model, configured, *FALLBACK_MODELS, DEFAULT_MODEL):
        # A banned name is dropped wherever it came from — including a .env
        # written before the model was taken out — and the default stands in
        # for it, so the reader is never left with nothing to ask.
        if name and name not in BANNED_MODELS and name not in ordered:
            ordered.append(name)
    return ordered


async def _call_cloud(
    api_key: str, model: str, payload: dict, timeout: float, proxy: str = ""
) -> tuple[str | None, str]:
    """Send one request, trying the model names in order.

    Returns ``(which model answered, its answer)``. A model Google has retired
    is not the end of it: the API is asked what this key may use and the
    newest of those is tried next. A refusal that will not repair itself — a
    bad key, mainly — is written to the journal as an error, in plain words,
    because a second reader that quietly stopped working is worse than no
    second reader at all.
    """

    global _working_model, last_problem

    # Work on a copy: the thinking setting is dropped below when a model
    # refuses it, and the caller's payload must survive that untouched.
    payload = {
        **payload,
        "generationConfig": dict(payload.get("generationConfig") or {}),
    }

    tried: list[str] = []
    retired: list[str] = []
    available: list[str] = []
    # Set only when a name was refused as retired. A switch after a mere
    # timeout is not evidence that the configured name is wrong.
    saw_gone = False
    queue = _candidate_models(model)
    while queue:
        candidate = queue.pop(0)
        if candidate in tried:
            continue
        tried.append(candidate)
        status, text = await _request(api_key, candidate, payload, timeout, proxy)

        if status == 200:
            _working_model = candidate
            last_problem = ""
            if candidate != model and saw_gone:
                logger.warning(
                    "Второй читатель отвечает на модели %s. Имя %s отключено — "
                    "пропишите GEMINI_MODEL=%s в .env, чтобы не тратить "
                    "лишний запрос на каждом снимке.",
                    candidate,
                    model,
                    candidate,
                )
            elif candidate != model:
                # A timeout or a spent quota is not a dead name. Saying
                # otherwise sends a person to edit a setting that is right,
                # and pins the bot to whichever fallback happened to answer.
                logger.info(
                    "Ответила резервная модель %s (%s не ответил в этот раз).",
                    candidate,
                    model,
                )
            return candidate, text

        if status == 400 and _mentions_thinking(text):
            # A model that does not know this setting must not cost the whole
            # reader. Drop it and ask the same model again, once.
            logger.warning(
                "Модель %s не приняла thinkingConfig — спрашиваю без него.", candidate
            )
            config = payload.get("generationConfig")
            if isinstance(config, dict):
                config.pop("thinkingConfig", None)
            status, text = await _request(api_key, candidate, payload, timeout, proxy)
            if status == 200:
                _working_model = candidate
                last_problem = ""
                return candidate, text

        if status == QUOTA_STATUS:
            last_problem = (
                "квота исчерпана (429): бесплатный ключ исчерпал лимит. "
                "Он восстанавливается сам — подождите или подключите платный "
                "тариф в Google AI Studio. Пока бот читает снимки сам."
            )
            logger.warning("Второй читатель временно недоступен: %s", last_problem)
            return None, ""

        if status in PERMANENT_STATUS:
            last_problem = f"ключ не принят ({status}): {_first_error_line(text)}"
            logger.error("Второй читатель НЕ работает: %s", last_problem)
            return None, ""

        if status == GONE_STATUS:
            # A retired name. The API knows which models this key may use, and
            # asking costs one small request on the one day it matters. If it
            # cannot be asked, the names kept below are still worth a try, so
            # this falls through to them instead of giving up here.
            logger.error("Модель %s отключена: Google её больше не отдаёт.", candidate)
            saw_gone = True
            retired.append(candidate)
            known = await list_models(api_key, timeout=timeout, proxy=proxy)
            if known:
                available = known
            better = pick_flash_model(available, exclude=(*tried, *retired))
            if better:
                logger.error(
                    "Спрашиваю у API, какие модели доступны этому ключу, и пробую %s.",
                    better,
                )
                queue.insert(0, better)
            continue

        if status:
            last_problem = f"ответ {status}: {_first_error_line(text)}"
            logger.error("Второй читатель НЕ работает: %s", last_problem)
            return None, ""

    if retired:
        last_problem = (
            f"модель {', '.join(retired)} отключена — Google её больше не отдаёт; "
            "доступные этому ключу: "
            + (", ".join(available[:6]) if available else "спросить не удалось")
        )
        logger.error("Второй читатель НЕ работает: %s", last_problem)
        return None, ""
    last_problem = "облако не ответило ни на один запрос"
    return None, ""


async def read_with_gemini(
    image_bytes: bytes,
    *,
    api_key: str,
    model: str = DEFAULT_MODEL,
    timeout: float = DEFAULT_TIMEOUT,
    mime_type: str = "image/jpeg",
    proxy: str = "",
) -> GeminiReading | None:
    """Ask the model what it sees. Returns None if it cannot be asked.

    A second opinion is a luxury: if the network is down or the model answers
    with prose, the bot reads the photograph itself, exactly as it did before.
    That silence is deliberate. But a setting that can never work — a refused
    key, a retired model — is not swallowed quietly: it is written as an error
    and shown on the status screen.
    """

    if not api_key:
        return None

    # The cloud is shown the frame several ways at once. Preparing them costs
    # real CPU — sharpening and denoising a four-megapixel frame takes
    # seconds — so it is pushed off the loop rather than blocking the bot.
    try:
        pictures = await asyncio.to_thread(cloud_pictures, image_bytes, MAX_PICTURES)
    except ValueError as exc:
        # OpenCV could not read the file. That is not a reason to give up on
        # the cloud: the model accepts formats OpenCV does not, and a picture
        # sent as it arrived is better than no second opinion at all.
        logger.warning(
            "Снимок не удалось обработать (%s) — уходит в облако как есть", exc
        )
        pictures = [image_bytes]

    parts: list[dict] = [{"text": PROMPT}]
    for picture in pictures:
        parts.append(
            {
                "inline_data": {
                    "mime_type": mime_type,
                    "data": base64.b64encode(picture).decode("ascii"),
                }
            }
        )
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": 4096,
            # Reading a code is not a reasoning problem. Left to itself the
            # model spends its whole output allowance thinking, and the JSON
            # arrives cut in half — the journal showed answers truncated at
            # fifty-six characters, and a one-word check took 46 seconds.
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    answered, text = await _call_cloud(api_key, model, payload, timeout, proxy)
    if answered is None or not text:
        return None

    try:
        answer = _answer_text(text)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        logger.warning("Ответ Gemini не удалось разобрать: %s", exc)
        return None

    try:
        reading = parse_answer(answer)
    except (ValueError, TypeError) as exc:
        logger.warning("Gemini вернул не JSON: %s", exc)
        return None

    # A top answer that is already a real code is left alone. Only when it is
    # not — wrong length, a forbidden letter, a check digit that does not add
    # up — does the vote decide, because a code the model offered second and
    # vouched for is better than nothing at all.
    if not reading.believable:
        chosen, confidence = reading.best_code()
        if chosen:
            logger.info(
                "Второй читатель: голосование дало %s (уверенность %.2f) вместо %s",
                mask_vin(chosen, chosen[-6:]),
                confidence,
                mask_vin(reading.vin, reading.vin[-6:]) if reading.vin else "—",
            )
            reading = replace(reading, vin=chosen)
    return reading


@dataclass(frozen=True, slots=True)
class GeminiSettings:
    """How the second opinion is configured."""

    api_key: str = ""
    model: str = DEFAULT_MODEL
    # «off» — never asked. «auto» — asked only when the local engine is not
    # sure of itself, which is where the hard photographs are and where the
    # money is worth spending. «always» — asked about every picture.
    mode: str = "auto"
    timeout: float = DEFAULT_TIMEOUT
    # Where the request leaves the computer from. Empty means straight out,
    # which is right everywhere except where the service refuses the caller's
    # country; then this is the way round it. Only this one call takes the
    # detour — Telegram keeps its own, direct route.
    proxy: str = ""

    @property
    def enabled(self) -> bool:
        return self.mode != "off" and bool(self.api_key)

    @property
    def only_when_unsure(self) -> bool:
        """Ask only about the photographs the local engine could not read."""

        return self.mode == "auto"

    @property
    def cloud_reads_first(self) -> bool:
        """The cloud is the reader; the local engine is the way out.

        This is what he asked for: one reader that is not bothered by glare,
        dirt or a code etched into glass. The photograph goes to the cloud
        first, and the local engine only runs when the cloud came back with
        nothing usable — which also means a hard picture is no longer read
        twice, in two slow ways.
        """

        return self.enabled and self.mode == "first"


async def probe_key(
    api_key: str,
    *,
    model: str = DEFAULT_MODEL,
    timeout: float = DEFAULT_TIMEOUT,
    proxy: str = "",
) -> tuple[bool, str, float]:
    """Ask one cheap question, purely to prove the key works.

    Returns ``(works, what came back, seconds)``. It is called from the bot's
    status screen, where he presses a button and expects a straight answer
    about his key: accepted, refused — or a model that no longer exists, with
    the list of models this key may actually use.
    """

    if not api_key:
        return False, "ключ не указан в .env", 0.0

    payload = {
        "contents": [{"parts": [{"text": "Ответь одним словом: ок"}]}],
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": 64,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    started = time.monotonic()
    answered, text = await _call_cloud(api_key, model, payload, timeout, proxy)
    elapsed = time.monotonic() - started
    if answered is None:
        return False, last_problem or "облако не ответило", elapsed
    try:
        body = json.loads(text)
        parts = body.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        answer = " ".join(str(part.get("text", "")) for part in parts).strip()
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        answer = ""
    return True, answer or "ответ получен", elapsed


async def startup_check(settings: GeminiSettings) -> str:
    """Say once, at start-up, whether the second reader really answers.

    One small request, made only when a key is configured. The point is that
    a dead model or a refused key is visible the moment the bot starts,
    instead of surfacing weeks later as «the bot still reads badly» — which is
    exactly how the retired ``gemini-2.0-flash`` went unnoticed.
    """

    if not settings.enabled:
        return "Второй читатель выключен: бот читает снимки сам, как и раньше."
    works, detail, seconds = await probe_key(
        settings.api_key,
        model=settings.model,
        timeout=settings.timeout,
        proxy=settings.proxy,
    )
    if works:
        return (
            f"Второй читатель отвечает: {settings.model}, {seconds:.1f} с. "
            "Будет спрашиваться по трудным снимкам."
        )
    return f"Второй читатель НЕ работает: {detail} Пока так — бот читает снимки сам."
