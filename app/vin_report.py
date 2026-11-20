"""A full account of what the picture gave up, in the shape he asked for.

He brought a prompt written for a cloud vision model: find every region that
could be a VIN, read them, return every candidate, mark characters that cannot
be read instead of guessing them, judge the photograph itself, and say plainly
what to do if it is not good enough. Every one of those is a good rule. None
of them needs a cloud: the engine already reads the picture, so the report is
built from what it did and what it saw.

The shape of the answer is kept deliberately close to the prompt's JSON, so
that a vision model can be asked for a second opinion later and the two
answers compared field by field.

Two rules are worth spelling out because they are the ones usually broken:

* **No character is invented.** Where the readings cannot agree, the report
  writes ``?`` — never the most likely letter. A ``?`` is something a person
  can put right from the plate; a plausible wrong letter is not.
* **A check digit is arithmetic, not truth.** Roughly one reading in eleven
  has a valid check digit by accident, so agreement between separate readings
  counts as much as the digit itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np

from .ocr import (
    VIN_LENGTH,
    _looks_like_a_real_vin,
    choose_best_candidate,
    extract_vin_candidates,
    is_valid_vin,
    repair_vin,
    unsure_positions,
    vin_check_digit_is_wrong,
)
from .vin_reader import _code_lines, _decode, _views
from .vin_reader import read as read_vin

logger = logging.getLogger(__name__)

# The steps the engine puts a photograph through. Reported honestly — nothing
# is listed that is not done.
PREPROCESSING: tuple[str, ...] = (
    "upscale",
    "four-rotations",
    "deskew",
    "clahe",
    "otsu",
    "adaptive-threshold",
    "background-flatten",
    "line-tilt",
    "sliding-windows",
)

UNREADABLE = "?"


@dataclass(frozen=True, slots=True)
class ImageQuality:
    """How bad the photograph itself is, each from 0 (fine) to 1 (bad).

    ``contrast`` is the exception: 1 means strong contrast, which is good.
    The prompt lists it alongside the others, so it is reported the same way
    round as they are.
    """

    glare: float
    blur: float
    angle: float
    contrast: float

    def as_dict(self) -> dict[str, float]:
        return {
            "glare": round(self.glare, 3),
            "blur": round(self.blur, 3),
            "angle": round(self.angle, 3),
            "contrast": round(self.contrast, 3),
        }


@dataclass(frozen=True, slots=True)
class Candidate:
    """One code the picture might be carrying."""

    raw: str
    normalized: str
    confidence: float  # 0..100, as Tesseract reckons it
    source: str
    bbox: tuple[float, float, float, float]
    notes: str

    def as_dict(self) -> dict[str, object]:
        return {
            "raw": self.raw,
            "normalized": self.normalized,
            "confidence": round(self.confidence / 100.0, 3),
            "source": self.source,
            "bbox": [round(value, 4) for value in self.bbox],
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class ReadingReport:
    """Everything the picture gave up, and what to do about it."""

    best_vin: str | None
    best_confidence: float  # 0..100
    candidates: tuple[Candidate, ...]
    partial_vin: str | None
    need_retake: bool
    retake_instructions: str
    image_quality: ImageQuality
    preprocessing: tuple[str, ...] = PREPROCESSING

    @property
    def unreadable_positions(self) -> tuple[int, ...]:
        """Which characters came out as «?» (counting from one)."""

        if not self.partial_vin:
            return ()
        return tuple(
            index + 1
            for index, char in enumerate(self.partial_vin)
            if char == UNREADABLE
        )

    def as_json(self) -> dict[str, object]:
        """The answer in the shape the prompt asks for.

        Confidences come out as fractions, 0 to 1, the way the prompt writes
        them; inside the bot they are kept as percentages.
        """

        return {
            "best_vin": self.best_vin,
            "best_confidence": round(self.best_confidence / 100.0, 3),
            "candidates": [candidate.as_dict() for candidate in self.candidates],
            "partial_vin": self.partial_vin,
            "need_retake": self.need_retake,
            "retake_instructions": self.retake_instructions,
            "image_quality": self.image_quality.as_dict(),
            "preprocessing": list(self.preprocessing),
        }


def measure_quality(gray: np.ndarray) -> ImageQuality:
    """Judge the photograph: blown out, out of focus, tilted, washed out.

    Each number is a rough proportion, not a laboratory measurement. They are
    used for one thing only — deciding whether to ask for another photograph
    and, if so, saying what is wrong with this one.
    """

    height, width = gray.shape[:2]
    # Look at the middle of the picture: the frame of a phone photograph is
    # often the sky, the floor or a thumb, none of which is the plate.
    centre = gray[height // 4 : height * 3 // 4, width // 4 : width * 3 // 4]
    if centre.size == 0:
        centre = gray

    # Glare: light so bright that no character survives under it.
    glare = float((centre >= 250).mean())
    glare = min(1.0, glare * 8.0)

    # Focus: the Laplacian is flat on a blurred picture and busy on a sharp
    # one. Below about a hundred it is genuinely out of focus.
    focus = float(cv2.Laplacian(centre, cv2.CV_64F).var())
    blur = float(min(1.0, max(0.0, 1.0 - focus / 600.0)))

    # Contrast: how far the darks and lights are pulled apart.
    spread = float(centre.std())
    contrast = float(min(1.0, spread / 80.0))

    # Tilt: how far the print lies off the horizontal, from the ink itself.
    angle = _tilt_of(centre)

    return ImageQuality(glare=glare, blur=blur, angle=angle, contrast=contrast)


def _tilt_of(gray: np.ndarray) -> float:
    """How far the print in this picture lies off level, 0 to 1.

    Twenty degrees is as far as anyone would hold a camera and still expect
    the code to be read, so that is the top of the scale.
    """

    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    _, inked = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    points = cv2.findNonZero(inked)
    if points is None or len(points) < 32:
        return 0.0
    raw = float(cv2.minAreaRect(points)[-1])
    if raw > 45.0:
        raw -= 90.0
    if raw < -45.0:
        raw += 90.0
    return float(min(1.0, abs(raw) / 20.0))


def _code_band(gray: np.ndarray) -> tuple[float, float, float, float] | None:
    """Where in the picture the code was found, as fractions of the frame.

    The engine takes the whole width of the picture at the height of the line:
    Tesseract's boxes stop short of the ends of a line often enough to cut a
    code in half, so the honest answer is «somewhere along this band».
    """

    for view in _views(gray):
        lines = _code_lines(view)
        if not lines:
            continue
        _score, _strip, (top, bottom) = lines[0]
        height = view.shape[0]
        return (
            0.0,
            max(0.0, min(1.0, top / max(height, 1))),
            1.0,
            max(0.0, min(1.0, bottom / max(height, 1))),
        )
    return None


def _source_of(gray: np.ndarray) -> tuple[str, str]:
    """What the code was printed on, as far as pixels can tell.

    A windshield, a door jamb and a dashboard are not distinguishable from a
    photograph — not honestly. What *can* be told is whether the characters
    are light on a dark plate or dark on a light one, and that is what is
    reported, with the guess labelled as the guess it is.
    """

    for view in _views(gray):
        lines = _code_lines(view)
        if not lines:
            continue
        _score, strip, _box = lines[0]
        darkness = float(strip.mean())
        if darkness < 110.0:
            return (
                "sticker",
                (
                    "светлые знаки на тёмной табличке — похоже на "
                    "металлическую табличку или тёмную наклейку"
                ),
            )
        if darkness > 190.0:
            return (
                "sticker",
                "тёмные знаки на светлом фоне — документ или светлая наклейка",
            )
        return (
            "unknown",
            (
                "контраст не позволяет сказать, что именно на снимке: "
                "стекло, проём двери или панель — по пикселям не различить"
            ),
        )
    return ("unknown", "строка с кодом на снимке не найдена")


def _partial(observations: list[tuple[str, float]]) -> str | None:
    """The code with a «?» wherever the readings could not agree.

    Built only when the engine saw the code but the readings argued about
    part of it. Where they agree, the character is written down; where they
    argue, guessing one would be inventing it — and a «?» is something he can
    put right from the plate in one tap, which a plausible wrong letter is
    not. Two fifths of the readings disagreeing is the line: below that it is
    noise, above it the camera genuinely could not tell.
    """

    best, _best_score = choose_best_candidate(observations)
    if best is None or len(best) != VIN_LENGTH:
        return None
    disputed = unsure_positions(best, observations, share=0.4)
    if not disputed:
        return None
    letters = list(best)
    for index in disputed:
        letters[index] = UNREADABLE
    partial = "".join(letters)
    return None if partial == best else partial


def _tally(observations: list[tuple[str, float]]) -> dict[str, list[float]]:
    """Every code the readings contained, and how sure each reading was.

    A reading is a line of raw OCR, often the code with a label or two words
    of small print stuck to either end of it, so each reading is searched for
    a code the way the engine searches it. Only codes shaped like a real one
    are counted: a noisy line yields dozens of seventeen-character windows
    made of letters off a headline and digits off a date.
    """

    found: dict[str, list[float]] = {}
    for text, confidence in observations:
        for code in extract_vin_candidates(text):
            if not _looks_like_a_real_vin(code):
                continue
            found.setdefault(code, []).append(confidence or 0.0)
    return found


def _instructions(quality: ImageQuality, *, language: str, missing: int) -> str:
    """What to do about a photograph that will not do."""

    advice: list[str] = []
    if quality.blur >= 0.6:
        advice.append(
            "снимок не в фокусе — поднесите камеру ближе и дайте ей навестись на код"
            if language == "ru"
            else "unscharf — näher heran und scharf stellen"
        )
    if quality.glare >= 0.5:
        advice.append(
            "блик закрывает код — снимите со вспышкой, направленной "
            "мимо, или прикройте блик рукой"
            if language == "ru"
            else "Blendung — seitlich beleuchten oder abschatten"
        )
    if quality.angle >= 0.6:
        advice.append(
            "сильный наклон — держите камеру параллельно табличке"
            if language == "ru"
            else "stark geneigt — parallel halten"
        )
    if quality.contrast <= 0.25:
        advice.append(
            "мало контраста — посветите на табличку сбоку"
            if language == "ru"
            else "zu wenig Kontrast — seitlich anleuchten"
        )
    if missing:
        advice.append(
            f"не прочитано знаков: {missing} — можно заполнить их вручную"
            if language == "ru"
            else f"{missing} Zeichen unleserlich — von Hand ergänzen"
        )
    if not advice:
        advice.append(
            "код не найден: снимите табличку во весь кадр, свет сбоку, "
            "без вспышки в упор"
            if language == "ru"
            else "Code nicht gefunden: ganzformatig, Licht von der Seite"
        )
    return "; ".join(advice)


def build_report(
    image_bytes: bytes,
    *,
    language: str = "ru",
    vin: str | None = None,
    observations: tuple[tuple[str, float], ...] | None = None,
) -> ReadingReport:
    """Read a photograph and give the whole account of it.

    The reading itself takes a minute on a hard picture, and the bot has
    usually already done it — so pass ``vin`` and ``observations`` and the
    report is built from what is known, with no second pass over the picture.
    Only the geometry and the quality of the photograph are measured fresh,
    and those are a single look at the frame.
    """

    gray = cv2.cvtColor(_decode(image_bytes), cv2.COLOR_BGR2GRAY)
    quality = measure_quality(gray)
    band = _code_band(gray)
    source, note = _source_of(gray)
    bbox = band or (0.0, 0.0, 1.0, 1.0)

    if observations is None:
        vin, confidence, observations = read_vin(image_bytes)
    else:
        confidence = None
    partial = _partial(list(observations))

    # Every code the picture offered, most often read first.
    tally = _tally(observations)
    ranked = sorted(
        tally.items(), key=lambda item: (len(item[1]), sum(item[1])), reverse=True
    )
    most = len(ranked[0][1]) if ranked else 1
    candidates: list[Candidate] = []
    for raw, confidences in ranked[:4]:
        mean = sum(confidences) / len(confidences)
        agreement = len(confidences) / most
        repaired = repair_vin(raw) if vin_check_digit_is_wrong(raw) else None
        candidates.append(
            Candidate(
                raw=raw,
                normalized=repaired or raw,
                confidence=round(mean * (0.6 + 0.4 * agreement), 1),
                source=source,
                bbox=bbox,
                notes="; ".join(
                    part
                    for part in (
                        note,
                        f"прочитано {len(confidences)} раз",
                        "контрольная цифра не сошлась"
                        if vin_check_digit_is_wrong(raw)
                        else "контрольная цифра сошлась",
                    )
                    if part
                ),
            )
        )

    best = vin if is_valid_vin(vin or "") else None
    # The engine's own «confidence» is a sum of scores, not a percentage, so
    # the honest number is how sure the readings were that produced this code.
    supports = tally.get(best or "", [])
    best_confidence = (
        sum(supports) / len(supports) if supports else float(confidence or 0.0)
    )
    missing = partial.count(UNREADABLE) if partial else 0
    need_retake = (
        best is None
        or bool(missing)
        or quality.blur >= 0.6
        or quality.glare >= 0.5
        or quality.angle >= 0.6
    )
    return ReadingReport(
        best_vin=best,
        best_confidence=best_confidence,
        candidates=tuple(candidates),
        partial_vin=partial,
        need_retake=need_retake,
        retake_instructions=(
            _instructions(quality, language=language, missing=missing)
            if need_retake
            else ""
        ),
        image_quality=quality,
    )
