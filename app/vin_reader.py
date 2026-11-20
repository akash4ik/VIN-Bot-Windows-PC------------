"""Reading a VIN off a photograph, written from scratch.

The old engine grew for two years and ended as a stack of patches: contour
finding, then a label search, then turns, then more contours, then patches on
top of the patches. It read a plate if the plate was obliging. This module
replaces it. It does one thing, in one pass, in this order:

1. **Look at the picture from every side it could have been taken from.**
   A phone held sideways writes the file sideways; a black plate carries light
   characters on a dark ground. So the picture is read upright and turned a
   quarter turn each way, and each of those is read light-on-dark as well as
   dark-on-light. Small pictures are enlarged first, because print below ten
   pixels cannot be read by anything.

2. **Let Tesseract find the lines.** It is built to divide a picture into
   lines, and it does that better than any contour work. Every line is then
   judged by *what is written in it*: seventeen characters out of an alphabet
   that holds no I, no O and no Q, with digits where the serial number goes.
   Nothing here looks for the word «VIN».

3. **Read the promising lines properly.** A line is blown up to a height
   Tesseract likes and read four ways: as it came, thresholded, adapted to the
   local light, and flattened to undo a reflection — each at two sizes and in
   three segmentation modes. A line wider than it is tall is cut into
   overlapping windows, because the code will sit whole inside one of them.

4. **Believe only what proves itself.** The ninth character of a VIN is
   computed from the other sixteen. A code that adds up is almost certainly
   real; one reading in eleven adds up by chance. So a code is believed when
   several independent readings agree on it and the check digit holds — and
   until then the search goes on.

The result is a code, or nothing. A code that fails the check digit is still
returned, because the person can see the plate and one wrong character is
easily put right; but it is returned knowing it is wrong, and the bot says so.
"""

from __future__ import annotations

import logging
import math

import cv2
import numpy as np
import pytesseract
from pytesseract import Output, TesseractError

from .ocr import (
    choose_best_candidate,
    vin_check_digit_matches,
)

logger = logging.getLogger(__name__)

# Tesseract reads best when a line of characters is about this many pixels tall.
LINE_HEIGHT = 96.0
# Below this the print is too small to make out; above it nothing is gained.
MIN_LINE_HEIGHT = 26.0
# A block taller than this is not one line of print; cut it up.
TALLEST_LINE = 130
MAX_LINE_HEIGHT = 130.0
# How many separate readings must agree on a code before it is believed.
AGREEMENT = 3
# How many before the search is allowed to stop early. Stopping is a stronger
# claim than accepting, so it asks for more.
EARLY_AGREEMENT = 6
# A line is only worth reading if it could hold a code.
MIN_SCORE = 7.0


def _decode(image_bytes: bytes) -> np.ndarray:
    buffer = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("не удалось прочитать изображение")
    return image


def _preparations(strip: np.ndarray) -> list[np.ndarray]:
    """One line, made readable four different ways.

    Which one works depends on the light the photograph was taken in, and
    that cannot be told in advance. Preparing a line is cheap — it is one line
    — and the one that worked is known afterwards by its check digit.
    """

    equalised = cv2.createCLAHE(clipLimit=2.4, tileGridSize=(8, 8)).apply(strip)
    threshold = cv2.threshold(equalised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    adaptive = cv2.adaptiveThreshold(
        equalised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 12
    )
    # Flattening divides out the slow change of brightness a lamp or a
    # reflection leaves across the line.
    background = cv2.GaussianBlur(
        equalised, (max(3, (equalised.shape[1] // 12) | 1), 3), 0
    )
    flattened = cv2.divide(equalised, background, scale=255)
    return [equalised, threshold, adaptive, flattened]


def _read(image: np.ndarray, page_segmentation_mode: int) -> tuple[str, float]:
    """Read one picture, once. Failures are not fatal: try the next way."""

    config = (
        f"--oem 3 --psm {page_segmentation_mode} "
        "-c tessedit_char_whitelist=ABCDEFGHJKLMNPRSTUVWXYZ0123456789"
    )
    try:
        data = pytesseract.image_to_data(
            image, lang="eng", config=config, output_type=Output.DICT
        )
    except (TesseractError, RuntimeError, OSError):
        return "", 0.0
    words: dict[tuple[str, str, str], list[str]] = {}
    lines: dict[tuple[str, str, str], list[str]] = {}
    confidences: list[float] = []
    for index, raw in enumerate(data["text"]):
        word = str(raw).strip()
        if not word:
            continue
        key = (
            str(data["block_num"][index]),
            str(data["par_num"][index]),
            str(data["line_num"][index]),
        )
        words.setdefault(key, []).append(word)
        lines.setdefault(key, []).append(word)
        try:
            confidence = float(data["conf"][index])
        except (TypeError, ValueError):
            continue
        if confidence >= 0:
            confidences.append(confidence)
    text = " ".join(" ".join(parts) for parts in lines.values())
    average = sum(confidences) / len(confidences) if confidences else 0.0
    return text, average


def _score(text: str, words: int) -> float:
    """How much a line looks like it carries a code. No word is looked for."""

    compact = "".join(char for char in text.upper() if char.isalnum())
    if not compact:
        return 0.0
    score = 0.0
    if not any(char in "IOQ" for char in compact):
        score += 2.0
    if 15 <= len(compact) <= 19:
        score += 6.0
    elif 13 <= len(compact) <= 22:
        score += 2.0
    else:
        score -= 4.0
    digits = sum(char.isdigit() for char in compact)
    if digits >= 4:
        score += 2.0
    elif digits == 0:
        score -= 2.0
    if words > 1:
        score -= 3.0 * (words - 1)
    if any(not char.isalnum() for char in text if not char.isspace()):
        score -= 2.0
    return score


def _code_lines(
    frame: np.ndarray,
) -> list[tuple[float, np.ndarray, tuple[int, int]]]:
    """The lines of this picture that could be carrying the code.

    Each comes back as ``(score, strip, (top, bottom))`` — the last part is
    where in the frame the line lies, so the report can say where on the
    photograph the code was found.
    """

    try:
        data = pytesseract.image_to_data(
            frame,
            lang="eng",
            config="--oem 3 --psm 11 -c tessedit_char_whitelist="
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-.:/ ",
            output_type=Output.DICT,
        )
    except (TesseractError, RuntimeError, OSError):
        return []
    grouped: dict[tuple[str, str, str], list[tuple[int, int, int, int, str]]] = {}
    for index, raw in enumerate(data["text"]):
        word = str(raw).strip()
        if not word:
            continue
        grouped.setdefault(
            (
                str(data["block_num"][index]),
                str(data["par_num"][index]),
                str(data["line_num"][index]),
            ),
            [],
        ).append(
            (
                int(data["left"][index]),
                int(data["top"][index]),
                int(data["width"][index]),
                int(data["height"][index]),
                word,
            )
        )
    found: list[tuple[float, np.ndarray, tuple[int, int]]] = []
    for words in grouped.values():
        joined = "".join(word for *_rest, word in words)
        score = _score(joined, len(words))
        if score < MIN_SCORE:
            continue
        top = min(word[1] for word in words)
        bottom = max(word[1] + word[3] for word in words)
        # Tesseract's boxes stop short of the ends of a line often enough to
        # cut a code in half, so the whole width of the picture is taken at
        # that height: the code is certainly in there.
        pad = max(3, int((bottom - top) * 0.35))
        strip = frame[max(0, top - pad) : min(frame.shape[0], bottom + pad), :]
        if not strip.size:
            continue
        # Tesseract merges neighbouring lines into one block whenever a
        # picture is tilted, and it did exactly that on a plate turned six
        # degrees: it handed back a block nearly three hundred pixels high
        # which, scaled down to reading height, lost the code altogether. A
        # block taller than a line can be is therefore cut into its rows.
        if strip.shape[0] > TALLEST_LINE:
            pieces: list[tuple[np.ndarray, int, int]] = [
                (row, top, bottom) for row, top, bottom in _rows(_straighten(strip))
            ]
        else:
            pieces = [(strip, top, min(frame.shape[0], bottom))]
        for row, start, stop in pieces:
            if row.size:
                found.append((score, row, (start, stop)))
    found.sort(key=lambda item: item[0], reverse=True)
    return [(score, strip, box) for score, strip, box in found[:4]]


def _straighten(block: np.ndarray) -> np.ndarray:
    """Turn a tilted block level, so that its rows can be told apart.

    A block tilted six degrees smears every row across two hundred pixels of
    height, and no amount of counting ink top to bottom will then separate
    them. Levelling it first is what makes the rows fall out.
    """

    blurred = cv2.GaussianBlur(block, (5, 5), 0)
    _, inked = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    points = cv2.findNonZero(inked)
    if points is None or len(points) < 32:
        return block
    angle = float(cv2.minAreaRect(points)[-1])
    if angle > 45.0:
        angle -= 90.0
    if angle < -45.0:
        angle += 90.0
    if abs(angle) < 0.4:
        return block
    height, width = block.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2.0, height / 2.0), angle, 1.0)
    radians = abs(math.radians(angle))
    grown = (
        int(width * math.cos(radians) + height * math.sin(radians)) + 2,
        int(width * math.sin(radians) + height * math.cos(radians)) + 2,
    )
    matrix[0, 2] += grown[0] / 2.0 - width / 2.0
    matrix[1, 2] += grown[1] / 2.0 - height / 2.0
    return cv2.warpAffine(
        block,
        matrix,
        grown,
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def _rows(block: np.ndarray) -> list[tuple[np.ndarray, int, int]]:
    """Cut a block of print into the rows of print it is made of.

    Each row comes back with where it sits inside the block.
    """

    blurred = cv2.GaussianBlur(block, (5, 5), 0)
    _, inked = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    profile = (inked > 0).sum(axis=1)
    if not profile.any():
        return [block]
    tallest = int(profile.max())
    floor = max(1, int(tallest * 0.18))
    rows: list[tuple[int, int]] = []
    start: int | None = None
    for y, amount in enumerate(profile):
        if amount >= floor and start is None:
            start = y
        elif amount < floor and start is not None:
            rows.append((start, y))
            start = None
    if start is not None:
        rows.append((start, len(profile)))
    if not rows:
        return [block]
    out: list[tuple[np.ndarray, int, int]] = []
    for top, bottom in rows:
        pad = max(3, int((bottom - top) * 0.35))
        start = max(0, top - pad)
        stop = min(block.shape[0], bottom + pad)
        row = block[start:stop, :]
        if row.size:
            out.append((row, start, stop))
    return out


def _read_line(strip: np.ndarray) -> list[tuple[str, float]]:
    """Read one line every way there is."""

    out: list[tuple[str, float]] = []
    height = strip.shape[0]
    targets = [LINE_HEIGHT]
    if height > MAX_LINE_HEIGHT:
        targets = [LINE_HEIGHT, LINE_HEIGHT * 0.6]
    elif height < MIN_LINE_HEIGHT:
        targets = [LINE_HEIGHT, LINE_HEIGHT * 1.5]
    for prepared in _preparations(strip):
        for target in targets:
            scale = target / max(prepared.shape[0], 1)
            scaled = (
                cv2.resize(
                    prepared, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC
                )
                if not 0.95 < scale < 1.05
                else prepared
            )
            for mode in (7, 13, 8):
                text, confidence = _read(scaled, mode)
                if text:
                    out.append((text, confidence))
            if float(strip.mean()) < 150.0:
                inverted = cv2.bitwise_not(scaled)
                for mode in (7, 13):
                    text, confidence = _read(inverted, mode)
                    if text:
                        out.append((text, confidence))
    return out


def _read_line_tilted(strip: np.ndarray) -> list[tuple[str, float]]:
    """The same line, tilted a few degrees either way.

    A photograph is hardly ever held level, and a line two or three degrees
    out of true reads badly — badly enough to turn «1» into «A» and «S» into
    «5», which is what happened to a plate tilted three degrees. On a strip
    this small, trying a few angles costs very little.
    """

    out: list[tuple[str, float]] = []
    height, width = strip.shape[:2]
    for angle in (-6.0, -3.0, -1.5, 1.5, 3.0, 6.0):
        # The strip is a long, low ribbon, so turning it even a couple of
        # degrees swings its ends far past its own height. The canvas has to
        # grow to match, or the turn cuts the ends off and the reading loses
        # exactly the characters that were being tried for.
        matrix = cv2.getRotationMatrix2D((width / 2.0, height / 2.0), angle, 1.0)
        radians = abs(math.radians(angle))
        grown = (
            int(width * math.cos(radians) + height * math.sin(radians)) + 2,
            int(width * math.sin(radians) + height * math.cos(radians)) + 2,
        )
        matrix[0, 2] += grown[0] / 2.0 - width / 2.0
        matrix[1, 2] += grown[1] / 2.0 - height / 2.0
        tilted = cv2.warpAffine(
            strip,
            matrix,
            grown,
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE,
        )
        prepared = cv2.createCLAHE(clipLimit=2.4, tileGridSize=(8, 8)).apply(tilted)
        scale = LINE_HEIGHT / max(prepared.shape[0], 1)
        scaled = cv2.resize(
            prepared, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC
        )
        for mode in (7, 13):
            reading, confidence = _read(scaled, mode)
            if reading:
                out.append((reading, confidence))
    return out


def _read_windows(strip: np.ndarray) -> list[tuple[str, float]]:
    """Read a line that is far wider than it is tall, a window at a time.

    Blown up to a readable height such a line becomes a ribbon thirty times
    wider than tall, and Tesseract reads nothing off a shape like that. Cut
    into overlapping windows, the code sits whole inside at least one.
    """

    height, width = strip.shape[:2]
    if height < 4 or width < height * 6:
        return []
    window = int(height * 5.5)
    step = max(int(window * 0.55), 1)
    out: list[tuple[str, float]] = []
    for left in range(0, width, step):
        piece = strip[:, left : left + window]
        if piece.shape[1] < height * 1.5:
            break
        scale = LINE_HEIGHT / max(piece.shape[0], 1)
        scaled = cv2.resize(
            piece, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC
        )
        for mode in (7, 13):
            text, confidence = _read(scaled, mode)
            if text:
                out.append((text, confidence))
    return out


def _views(gray: np.ndarray) -> list[np.ndarray]:
    """The picture, from every side a phone could have taken it from."""

    height, width = gray.shape[:2]
    # Enlarge small print until a line of it is big enough to read.
    longest = max(height, width)
    if longest < 1900:
        scale = min(1900 / max(longest, 1), 4.0)
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    upright = gray
    turned = [
        cv2.rotate(gray, cv2.ROTATE_90_CLOCKWISE),
        cv2.rotate(gray, cv2.ROTATE_180),
        cv2.rotate(gray, cv2.ROTATE_90_COUNTERCLOCKWISE),
    ]
    return [upright, *turned]


def _settled(observations: list[tuple[str, float]], at_least: int = AGREEMENT) -> bool:
    """Whether a code has been read so often that it can be believed.

    One reading in eleven has a valid check digit by accident, so agreement
    matters as much as the check digit does. Stopping the search early takes
    more agreement than accepting a code at the end of it: a stopped search
    cannot be un-stopped, and on one trial picture an upright plate gave
    «WBASASCS0DF123456» — a code that adds up, read three times — while the
    true code came out only once the picture had been turned.
    """

    candidate = choose_best_candidate(observations)[0]
    if candidate is None or not vin_check_digit_matches(candidate):
        return False
    return sum(1 for text, _ in observations if text == candidate) >= at_least


def _read_line_cheaply(strip: np.ndarray) -> list[tuple[str, float]]:
    """Read a line the two ways that cost least and find most."""

    out: list[tuple[str, float]] = []
    equalised = cv2.createCLAHE(clipLimit=2.4, tileGridSize=(8, 8)).apply(strip)
    scale = LINE_HEIGHT / max(equalised.shape[0], 1)
    scaled = cv2.resize(
        equalised, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC
    )
    for mode in (7, 13):
        reading, confidence = _read(scaled, mode)
        if reading:
            out.append((reading, confidence))
    out.extend(_read_windows(strip))
    return out


def read(
    image_bytes: bytes,
) -> tuple[str | None, float | None, list[tuple[str, float]]]:
    """Read the VIN off a photograph. Returns the code, or nothing at all."""

    gray = cv2.cvtColor(_decode(image_bytes), cv2.COLOR_BGR2GRAY)
    observations: list[tuple[str, float]] = []

    for index, view in enumerate(_views(gray)):
        # Every side is looked at, because a phone held sideways writes the
        # file sideways and upright such a photograph yields nothing. The
        # upright view is read thoroughly; the turns are read cheaply, since
        # they are usually the long shot — but they are always taken, because
        # a wrong code read confidently upright can only be caught by them.
        for mode in (11, 6):
            text, confidence = _read(view, mode)
            if text:
                observations.append((text, confidence))
        for _score, strip, _box in _code_lines(view):
            if index == 0:
                observations.extend(_read_line(strip))
                observations.extend(_read_windows(strip))
                observations.extend(_read_line_tilted(strip))
            else:
                observations.extend(_read_line_cheaply(strip))
        if index == 0 and _settled(observations, EARLY_AGREEMENT * 2):
            return *choose_best_candidate(observations), observations

    return *choose_best_candidate(observations), observations
