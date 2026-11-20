from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass

import cv2
import numpy as np
import pytesseract
from pytesseract import Output, TesseractError

logger = logging.getLogger(__name__)

# Below this size a cropped region is noise, not text.
_MIN_CROP_PIXELS = 24

VIN_LENGTH = 17
VIN_ALLOWED = frozenset("ABCDEFGHJKLMNPRSTUVWXYZ0123456789")
CYRILLIC_LOOKALIKES = str.maketrans(
    {
        "А": "A",
        "В": "B",
        "С": "C",
        "Е": "E",
        "Н": "H",
        "К": "K",
        "М": "M",
        "Р": "P",
        "Т": "T",
        "Х": "X",
        "У": "Y",
        "І": "1",
    }
)
OCR_AMBIGUOUS = str.maketrans({"I": "1", "O": "0", "Q": "0"})
# Short German abbreviations that stand next to a VIN. They only mark a line as
# belonging to a VIN field; unlike VIN_LABELS they are never cut out of a token,
# because "FN" can also be part of a real VIN.
VIN_CONTEXT_WORDS = re.compile(
    r"(?<![A-Z0-9])(?:"
    r"FGNR|IDENTNR|IDENT-NR|IDENT|FIN|FNR|FZGNR|FAHRTNR|VIN|VN|FN"
    r")",
    re.IGNORECASE,
)
VIN_LABELS = re.compile(
    r"(?:"
    r"FAHRGESTELL[\s._:/-]*NUMMER|"
    r"FAHRZEUG[\s._:/-]*(?:IDENTIFIZIERUNGS|IDENT)[\s._:/-]*NUMMER|"
    r"IDENTIFIZIERUNGS[\s._:/-]*NUMMER|"
    r"IDENT[\s._:/-]*(?:NUMMER|NR)|"
    r"VIN|FIN"
    r")[\s.:#-]*",
    re.IGNORECASE,
)


class OCRUnavailableError(RuntimeError):
    """Raised when Tesseract is missing or cannot be executed."""


@dataclass(frozen=True, slots=True)
class OCRResult:
    vin: str | None
    suffix6: str | None
    confidence: float | None
    raw_text: str
    #: Every code the engine thought it saw, with how sure it was. Kept so
    #: that the person can be shown which characters were read two ways —
    #: that is where a correction is worth a tap, and nowhere else.
    observations: tuple[tuple[str, float], ...] = ()


def normalize_alphanumeric(value: str) -> str:
    value = value.upper().translate(CYRILLIC_LOOKALIKES)
    return re.sub(r"[^A-Z0-9]", "", value)


def is_valid_vin(value: str) -> bool:
    return len(value) == VIN_LENGTH and all(char in VIN_ALLOWED for char in value)


def is_valid_vin_fragment(value: str, lengths: set[int]) -> bool:
    return len(value) in lengths and all(char in VIN_ALLOWED for char in value)


# Words that sit next to a VIN on German paperwork. They are trimmed from the
# edges of an OCR token, so glue such as ``NRWVGZZZ1TZMW123456`` still yields a
# clean 17-character VIN. Longer words are trimmed first.
LABEL_WORDS: tuple[str, ...] = tuple(
    sorted(
        (
            "FAHRZEUGIDENTIFIZIERUNGSNUMMER",
            "FAHRGESTELLNUMMER",
            "IDENTIFIZIERUNGSNUMMER",
            "IDENTIFIKATIONSNUMMER",
            "FAHRGESTELL",
            "FAHRZEUG",
            "GESTELL",
            "NUMMER",
            "IDENT",
            "CHASSIS",
            "SERIEN",
            "FZG",
            "VIN",
            "FIN",
            "FNR",
            "FGNR",
            "VN",
            "FN",
            "NR",
        ),
        key=len,
        reverse=True,
    )
)
LABEL_FRAGMENTS = (
    "FAHRGESTELL",
    "FAHRZEUG",
    "GESTELLNUM",
    "IDENTNUM",
    "IDENTIFIZ",
    "NUMMER",
    "CHASSIS",
)


def _is_plausible_ocr_vin(value: str) -> bool:
    """Decide whether 17 characters can be a VIN and not a piece of a label.

    A real VIN never contains ``I``, ``O`` or ``Q`` and usually carries several
    digits. A candidate with a mathematically valid check digit is accepted even
    when it is digit-poor, because such a combination cannot happen by accident.
    """

    if not is_valid_vin(value):
        return False
    if any(fragment in value for fragment in LABEL_FRAGMENTS):
        return False
    # Four digits, and nothing else, is the rule version twelve used for years
    # on his real fleet. A valid check digit used to excuse a digit-poor
    # candidate, but one reading in eleven has one by accident: the seventeen
    # letters «BSTRNGSE5ATEESENB» from his journal passed that way, with a
    # single digit between them. Positions 12 to 17 of any real VIN are the
    # serial number and are digits, so the rule costs nothing.
    return sum(char.isdigit() for char in value) >= 4


def _collapse_repeated_runs(token: str) -> list[str]:
    """Candidates obtained by removing one duplicated character.

    A photographed VIN frequently gains a character inside a run: ``000001``
    becomes ``0000001``. Removing one character from every repeated run repairs
    the length without touching the VIN's first or last character, which is
    exactly what an edge trim would destroy.
    """

    if not VIN_LENGTH < len(token) <= 24:
        return []
    results = []
    for match in re.finditer(r"(.)\1+", token):
        start, end = match.span()
        if end - start < 2:
            continue
        candidate = token[:start] + token[start + 1 :]
        if len(candidate) == VIN_LENGTH:
            results.append(candidate)
    return results


def _looks_like_label_junk(piece: str) -> bool:
    """Whether the characters trimmed off a token are label remnants."""

    if not piece:
        return False
    if any(word in piece for word in LABEL_WORDS):
        return True
    # Two or more letters in a row next to a VIN are almost always the remains
    # of "FIN", "Nr." or a similar word, while a single letter or any digit
    # still belongs to the VIN itself.
    return 2 <= len(piece) <= 4 and piece.isalpha()


def _strip_label_edges(token: str) -> str:
    """Remove label words glued to the beginning or the end of a token."""

    changed = True
    while changed and len(token) > VIN_LENGTH:
        changed = False
        for word in LABEL_WORDS:
            if len(token) - len(word) < VIN_LENGTH:
                continue
            if token.startswith(word):
                token = token[len(word) :]
                changed = True
            elif token.endswith(word):
                token = token[: -len(word)]
                changed = True
    return token


def parse_manual_card_vin(value: str) -> tuple[str | None, str] | None:
    normalized = normalize_alphanumeric(value)
    if is_valid_vin(normalized):
        return normalized, normalized[-6:]
    if is_valid_vin_fragment(normalized, {6}):
        return None, normalized
    return None


def parse_search_query(value: str) -> str | None:
    """A search term: the last 4 or 6 VIN characters, or the whole VIN.

    A document usually shows the full VIN, and counting six characters from
    the right by hand is exactly the kind of thing that goes wrong in a
    hurry, so the whole number is accepted and reduced to its last six.
    """

    normalized = normalize_alphanumeric(value)
    if is_valid_vin(normalized):
        return normalized[-6:]
    if is_valid_vin_fragment(normalized, {4, 6}):
        return normalized
    return None


def mask_vin(vin_full: str | None, suffix6: str) -> str:
    if vin_full:
        return f"{'•' * 11}{vin_full[-6:]}"
    return f"{'•' * 11}{suffix6}"


def _ocr_normalize(value: str) -> str:
    return value.upper().translate(CYRILLIC_LOOKALIKES).translate(OCR_AMBIGUOUS)


def _extract_weighted_vin_candidates(text: str) -> dict[str, int]:
    """Extract VINs and rank clean tokens above noisy sliding windows.

    German documents often put ``Fahrgestell-Nummer`` on one line and the VIN
    on the next. OCR may also turn the label into short garbage tokens such as
    ``FN``. A standalone 17-character token is therefore much more trustworthy
    than an arbitrary 17-character window cut from a longer OCR line.
    """
    weighted: dict[str, int] = {}
    previous_line_was_label = False
    lines = text.splitlines() or [text]

    for raw_line in lines:
        has_german_vin_label = bool(
            VIN_LABELS.search(raw_line) or VIN_CONTEXT_WORDS.search(raw_line)
        )
        without_label = VIN_LABELS.sub(" ", raw_line)
        normalized = _ocr_normalize(without_label)
        tokens = [
            _strip_label_edges(token) for token in re.findall(r"[A-Z0-9]+", normalized)
        ]
        tokens = [token for token in tokens if token]
        context_bonus = 2 if has_german_vin_label or previous_line_was_label else 0
        line_has_candidate = False

        def offer(candidate: str, quality: int) -> None:
            nonlocal line_has_candidate
            if not _is_plausible_ocr_vin(candidate):
                return
            weighted[candidate] = max(weighted.get(candidate, 0), quality)
            line_has_candidate = True

        # 1. Best case: Tesseract produced one complete 17-character token. This
        #    prevents label fragments from shifting the selected characters.
        for token in tokens:
            offer(token, 9 + context_bonus)

        # 2. A label or a stray glyph glued to the VIN. Only the edges are
        #    trimmed, and the side that lost a label piece is trusted more, so a
        #    glued "FIN:" can never eat the VIN's final character.
        for token in tokens:
            if VIN_LENGTH < len(token) <= 30:
                prefix_length = len(token) - VIN_LENGTH
                offer(
                    token[prefix_length:],
                    (8 if _looks_like_label_junk(token[:prefix_length]) else 6)
                    + context_bonus,
                )
                offer(
                    token[:VIN_LENGTH],
                    (8 if _looks_like_label_junk(token[VIN_LENGTH:]) else 6)
                    + context_bonus,
                )

        # 2b. One duplicated character too many, for example six zeros instead
        #     of five. The VIN keeps its first and its last character.
        for token in tokens:
            for candidate in _collapse_repeated_runs(token):
                offer(candidate, 5 + context_bonus)

        # 3. VINs printed in groups, for example "WVW ZZZ 1JZ XW0 00001".
        for start in range(len(tokens)):
            joined = ""
            for token in tokens[start:]:
                joined += token
                if len(joined) == VIN_LENGTH:
                    offer(joined, 6 + context_bonus)
                    break
                if len(joined) > VIN_LENGTH:
                    break

        # 4. Windows that begin and end exactly at a word boundary: the OCR
        #    split the VIN, but the groups are still complete words.
        boundaries = [0]
        for token in tokens:
            boundaries.append(boundaries[-1] + len(token))
        compact = "".join(tokens)
        for start_index, start in enumerate(boundaries[:-1]):
            for end in boundaries[start_index + 1 :]:
                if end - start == VIN_LENGTH:
                    offer(compact[start:end], 5 + context_bonus)

        # 5. Last-resort recovery from a noisy line. Low score: such a window
        #    may still be cut out of a longer mixture of characters.
        if VIN_LENGTH <= len(compact) <= 40:
            for start in range(len(compact) - VIN_LENGTH + 1):
                offer(compact[start : start + VIN_LENGTH], 2 + context_bonus)

        previous_line_was_label = has_german_vin_label and not line_has_candidate

    return weighted


def extract_vin_candidates(text: str) -> set[str]:
    """Extract plausible 17-character VINs from noisy OCR output."""
    return set(_extract_weighted_vin_candidates(text))


_TRANSLITERATION = {
    **dict.fromkeys("A", 1),
    **dict.fromkeys("B", 2),
    **dict.fromkeys("C", 3),
    **dict.fromkeys("D", 4),
    **dict.fromkeys("E", 5),
    **dict.fromkeys("F", 6),
    **dict.fromkeys("G", 7),
    **dict.fromkeys("H", 8),
    **dict.fromkeys("J", 1),
    **dict.fromkeys("K", 2),
    **dict.fromkeys("L", 3),
    **dict.fromkeys("M", 4),
    **dict.fromkeys("N", 5),
    **dict.fromkeys("P", 7),
    **dict.fromkeys("R", 9),
    **dict.fromkeys("S", 2),
    **dict.fromkeys("T", 3),
    **dict.fromkeys("U", 4),
    **dict.fromkeys("V", 5),
    **dict.fromkeys("W", 6),
    **dict.fromkeys("X", 7),
    **dict.fromkeys("Y", 8),
    **dict.fromkeys("Z", 9),
    **{str(number): number for number in range(10)},
}
_WEIGHTS = (8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2)


def vin_check_digit_matches(vin: str) -> bool:
    """Return True when the ISO/North-American check digit is present and valid."""
    if not is_valid_vin(vin):
        return False
    expected_value = (
        sum(
            _TRANSLITERATION[char] * weight
            for char, weight in zip(vin, _WEIGHTS, strict=True)
        )
        % 11
    )
    expected = "X" if expected_value == 10 else str(expected_value)
    return vin[8] == expected


#: What a check digit may ever be. ISO 3779 allows a digit or an X — nothing
#: else — so a letter at the ninth place is a maker telling you outright that
#: this is not a check digit.
CHECK_DIGIT_CHARS = frozenset("0123456789X")


def check_digit_is_possible(vin: str | None) -> bool:
    """Whether the ninth character could be a check digit at all.

    North America makes the ninth character a check digit; ISO 3779 only
    permits it elsewhere, and European makers are free to write something
    else there. Ford of Europe writes the model code: on a Transit the ninth
    character is «R», on a Fiesta «H». A maker doing that has made no
    mistake — and a rule that says otherwise throws away a reading that was
    right, which is how one photograph came back «не распознано» while the
    correct code sat in the journal all along.
    """

    return bool(vin) and len(vin) >= 9 and vin[8] in CHECK_DIGIT_CHARS


def vin_is_believable(vin: str | None) -> bool:
    """Whether a code may be a real VIN.

    Seventeen characters a VIN is allowed to hold, and a ninth character that
    adds up from the other sixteen — where the maker carries one. Where the
    ninth character is not a check digit there is nothing to add up, and the
    code is judged on its shape alone.
    """

    if not is_valid_vin(vin):
        return False
    return vin_check_digit_matches(vin) or not check_digit_is_possible(vin)


# Manufacturer codes seen on German and European paperwork. Three matching
# characters at the start of a candidate are a strong hint that the window was
# cut in the right place.
KNOWN_WMI = frozenset(
    {
        "WVW",
        "WVG",
        "WV1",
        "WV2",
        "WAU",
        "WUA",
        "WBA",
        "WBS",
        "WBY",
        "WDD",
        "WDB",
        "WDC",
        "W1K",
        "W1N",
        "W1V",
        "TMB",
        "VSS",
        "W0L",
        "W0V",
        "VF1",
        "VF3",
        "VF7",
        "WF0",
        "WF1",
        "TMA",
        "KMH",
        "JTD",
        "SB1",
        "SJN",
        "WMA",
        "WME",
        "XLR",
        "ZCF",
        "ZFA",
        "ZAR",
        "SAL",
        "SAJ",
        "SCA",
        "TRA",
        "TRU",
        "NLH",
        "VNK",
        "YS2",
        "YV1",
        "YV4",
        "WJW",
        "WDF",
        "W09",
        "WEB",
        "WDX",
        "WKK",
        "NMB",
        "MNB",
        "MPA",
        "ADN",
        "VSK",
        "U5Y",
        "TMT",
        "XTA",
    }
)


#: The model year, the tenth character of a VIN. Thirty letters and digits
#: were ever issued — never I, O, Q, U, Z or a zero — and a reading that puts
#: one of those there is reading something that is not a VIN.
VIN_YEAR_CODES = "ABCDEFGHJKLMNPRSTVWXY123456789"


def _looks_like_a_real_vin(value: str) -> bool:
    """Whether seventeen characters are shaped the way a VIN is shaped.

    The check digit is the strongest test there is, and still one reading in
    eleven passes it by accident. A screenshot of the bot's own screen once
    produced «EBPY4HYT0BECB17CU» — seventeen characters out of the VIN
    alphabet, with a check digit that happened to add up. It is not a VIN
    because a VIN is not merely seventeen characters: its tenth character is a
    model year out of a fixed set of thirty, and its last six are the serial
    number, which is digits. The screenshot has neither, and every real code
    on his fleet has both.

    A reading that fails here is dropped rather than shown. He has said from
    the start that a made-up VIN must never appear, and a wrong line in a
    database is worse than an honest «could not read it» with a button to type
    the code in by hand.
    """

    if len(value) != VIN_LENGTH:
        return False
    # The serial number decides. A weight table, a screenshot or a line of
    # small print can produce seventeen characters out of the VIN alphabet —
    # but not six digits in a row at the end, and the last six characters of
    # any real VIN are its serial number.
    #
    # A weight table, a screenshot or a line of small print can produce
    # seventeen characters out of the VIN alphabet — but not five digits in a
    # row at the end, and the tail of any real VIN is its serial number.
    # Five, not six: botching one character is what cameras do, and he would
    # rather have a shaky reading offered with a warning than be told nothing.
    return sum(char.isdigit() for char in value[-6:]) >= 5


def structure_bonus(candidate: str) -> float:
    """Extra points for properties a genuine VIN has.

    The bonus is smaller than one quality level, so it only decides between
    candidates that the OCR rated equally — exactly the case where a label glued
    to the VIN used to win and cut off the last character.
    """

    bonus = 0.0
    if candidate[:3] in KNOWN_WMI:
        bonus += 25.0
    if candidate[:1] in "WZ":
        # German and Italian manufacturers: the whole fleet starts this way.
        bonus += 30.0
    digits_at_the_end = sum(char.isdigit() for char in candidate[-6:])
    if digits_at_the_end == 6:
        bonus += 20.0
    elif digits_at_the_end >= 4:
        bonus += 8.0
    if vin_check_digit_matches(candidate):
        bonus += 60.0
    if len(candidate) == VIN_LENGTH and candidate[9] in VIN_YEAR_CODES:
        bonus += 15.0
    return bonus


# A correct check digit is worth three quality levels: a wrong reading has it
# by accident about once in eleven times, so a VIN that survives the check
# outweighs a cleaner looking candidate of the next higher level, while a
# complete 17-character token (nine levels) still wins on its own.
CHECK_DIGIT_WEIGHT = 300.0

# What the camera mixes up on a metal plate or a sticker. Every pair is
# reversible: the reading is only corrected when the check digit confirms it.
VIN_CONFUSIONS: dict[str, str] = {
    "5": "S",
    "S": "5",
    "8": "B",
    "B": "8",
    "2": "Z",
    "Z": "2",
    "6": "G",
    "G": "6",
    "0": "D",
    "D": "0",
    "U": "V",
    "V": "U",
    "T": "7",
    "7": "T",
}


def vin_shape_score(candidate: str) -> float:
    """How much a 17-character string looks like the way a VIN is built.

    Positions 12 to 17 are the serial number and are digits on almost every
    vehicle; positions 1 to 3 are the manufacturer code and are letters on
    every European one; positions 4 to 8 describe the vehicle and are mostly
    digits. The score only ever compares readings that differ in one
    character, so it decides which of them fits the shape better.
    """

    score = 0.0
    score += 2.0 * sum(character.isdigit() for character in candidate[11:])
    score += 1.0 * sum(character.isalpha() for character in candidate[:3])
    score += 1.0 * sum(character.isdigit() for character in candidate[3:8])
    if candidate[:3] in KNOWN_WMI:
        score += 3.0
    return score


def repair_vin(candidate: str) -> str | None:
    """Return the VIN one camera confusion away, or None.

    A photograph of a plate mixes up the characters that look alike; the check
    digit is then the only witness left. Every single substitution from the
    confusion table is tested and the one that produces a valid check digit and
    fits the shape of a VIN best is taken — but only when it clearly beats
    every other candidate. Nothing is returned for a VIN whose check digit
    already matches, for a reading that is not a well formed VIN, and for an
    ambiguous one, where asking the person to check the screen is better than
    guessing.
    """

    if (
        not is_valid_vin(candidate)
        or not check_digit_is_possible(candidate)
        or vin_check_digit_matches(candidate)
    ):
        # With no check digit to test against there is no way to tell a repair
        # from a guess, and a guess is a VIN the plate does not carry.
        return None
    repairs = {
        candidate[:position] + replacement + candidate[position + 1 :]
        for position, character in enumerate(candidate)
        for replacement in (VIN_CONFUSIONS.get(character) or "")
        if vin_check_digit_matches(
            candidate[:position] + replacement + candidate[position + 1 :]
        )
    }
    valid = [repair for repair in repairs if _is_plausible_ocr_vin(repair)]
    if not valid:
        return None
    if len(valid) == 1:
        return valid[0]
    ranked = sorted(((vin_shape_score(item), item) for item in valid), reverse=True)
    best_score, best = ranked[0]
    if best_score > ranked[1][0] and best_score > vin_shape_score(candidate):
        return best
    return None


def _edit_distance(left: str, right: str) -> int:
    """Levenshtein distance, only used on 17-character VIN candidates."""

    if left == right:
        return 0
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current = [i]
        for j, right_char in enumerate(right, start=1):
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def _positional_consensus(candidates: dict[str, float]) -> str:
    """Build one VIN from the best supported character at every position.

    Noise almost never changes more than one or two characters, and different
    reads of the same document then disagree about those characters only. Voting
    per position repairs such a mistake, which no single read can do.
    """

    votes: list[dict[str, float]] = [defaultdict(float) for _ in range(VIN_LENGTH)]
    for candidate, score in candidates.items():
        for position, char in enumerate(candidate):
            votes[position][char] += score
    return "".join(max(vote, key=vote.get) for vote in votes)


def choose_best_candidate(
    observations: list[tuple[str, float]],
    *,
    require_agreement: bool = False,
) -> tuple[str | None, float | None]:
    """Pick the VIN the readings point at.

    ``require_agreement`` is for the turned picture. Text read the wrong way
    round is not read badly, it is scrambled: the letters stay, the order and
    the shapes do not, and a lonely pass happily assembles a well formed
    seventeen characters out of the wreckage. Genuine text, read twice from two
    passes, comes out the same both times — so a turned picture only counts
    when at least two independent passes agree.
    """
    scores: dict[str, float] = defaultdict(float)
    confidences: dict[str, list[float]] = defaultdict(list)
    seen_in: dict[str, set[int]] = defaultdict(set)
    qualities: dict[str, int] = {}

    for index, (text, confidence) in enumerate(observations):
        for candidate, quality in _extract_weighted_vin_candidates(text).items():
            qualities[candidate] = max(qualities.get(candidate, 0), quality)
            check_digit = (
                CHECK_DIGIT_WEIGHT if vin_check_digit_matches(candidate) else 0.0
            )
            scores[candidate] += (
                quality * 100.0
                + max(confidence, 0.0)
                + structure_bonus(candidate)
                + check_digit
            )
            confidences[candidate].append(max(confidence, 0.0))
            seen_in[candidate].add(index)

    # Never auto-accept a candidate that exists only because a 17-character
    # sliding window was cut out of a longer noisy OCR line. Such windows can
    # prepend a label fragment and silently drop the VIN's final character.
    # A valid check digit seen in two independent reads is the one exception.
    strong_candidates = {
        candidate
        for text, _confidence in observations
        for candidate, quality in _extract_weighted_vin_candidates(text).items()
        if quality >= 5
    }
    strong_candidates |= {
        candidate
        for candidate, sources in seen_in.items()
        if len(sources) >= 2 and vin_check_digit_matches(candidate)
    }
    scores = {
        candidate: score
        for candidate, score in scores.items()
        if candidate in strong_candidates
    }
    # Seventeen letters with one digit between them are not a VIN: they are the
    # camera reading a reflection, a seam or a line of small print. A real VIN
    # carries digits — in the serial number alone there are six — or at the very
    # least a check digit that adds up.
    scores = {
        candidate: score
        for candidate, score in scores.items()
        if _is_plausible_ocr_vin(candidate) and _looks_like_a_real_vin(candidate)
    }
    if require_agreement:
        scores = {
            candidate: score
            for candidate, score in scores.items()
            if len(seen_in[candidate]) >= 2
        }
    if not scores:
        return None, None

    # A code whose check digit adds up has proved itself; one that has not is
    # merely a line somebody read several times. The weight table of a plate is
    # read identically by four preparations — and it is still not the VIN. So
    # the codes that prove themselves are judged among themselves first.
    #
    # But only among readings of comparable quality. On his German form the
    # code comes out as one clean seventeen-character token, while a row of
    # stamps elsewhere on the page also happens to add up — a coincidence that
    # occurs once in eleven. Letting any code with a valid check digit win put
    # that stamp above the real code: it took «0908BDSLX14903240» over
    # «W1K1183121N245625». A better reading is not overruled by a luckier one.
    best_quality = max(qualities.values(), default=0)
    proven = {
        candidate: score
        for candidate, score in scores.items()
        if vin_check_digit_matches(candidate)
        and qualities[candidate] >= best_quality - 2
    }
    if proven:
        scores = proven

    # Repair isolated character mistakes by voting per position. Only readings
    # that are close to each other take part, so two different vehicles on one
    # document can never be mixed into a third, non-existent VIN.
    best_single = max(scores, key=scores.get)
    similar = {
        candidate: score
        for candidate, score in scores.items()
        if _edit_distance(candidate, best_single) <= 3
    }
    if len(similar) >= 2:
        merged = _positional_consensus(similar)
        merged_bonus = structure_bonus(merged)
        best_bonus = structure_bonus(best_single)
        # The vote may only overrule the leading reading when it produces a
        # better formed VIN. Otherwise a crowd of shifted near-duplicates would
        # outvote one intact 17-character token, the most reliable reading
        # there is.
        better_formed = merged_bonus > best_bonus or (
            vin_check_digit_matches(merged) and not vin_check_digit_matches(best_single)
        )
        if (
            merged != best_single
            and better_formed
            and _is_plausible_ocr_vin(merged)
            and _looks_like_a_real_vin(merged)
        ):
            merged_score = sum(similar.values())
            if merged_score > scores[best_single]:
                scores[merged] = merged_score
                if merged not in confidences:
                    confidences[merged] = confidences[best_single]

    best = max(scores, key=scores.get)
    repaired = repair_vin(best)
    # Repairing one confused character can turn a line of small print into a
    # code whose check digit adds up — the check digit is satisfied by
    # construction, so it can no longer vouch for the result. A screenshot of
    # the bot's own screen once came out of a repair as «C33S3N3S122413S3T»:
    # seventeen characters, a valid check digit, and a serial number half
    # made of letters. What the repair produces has to look like a VIN too.
    if repaired is not None and not _looks_like_a_real_vin(repaired):
        logger.info(
            "Починка символа дала %s — на VIN это не похоже, чтение оставлено как есть",
            repaired,
        )
        repaired = None
    if repaired is not None:
        logger.info(
            "Прочитанный VIN %s не прошёл проверку контрольной цифры, "
            "исправлен один похожий символ: %s",
            best,
            repaired,
        )
        best = repaired
        confidences.setdefault(best, confidences[best_single])
    average_confidence = sum(confidences[best]) / len(confidences[best])
    return best, round(min(average_confidence, 100.0), 1)


# Tesseract rates every reading itself, and the rating is not to be trusted as a
# verdict: on damaged plates a correct VIN arrives at fifteen per cent, and one
# of his photographs was read correctly by version twelve at four tenths of a
# per cent. So the figure only decides how loudly the bot asks for a second
# look — never whether the reading is offered at all. Refusing a correct VIN is
# worse than a shaky one, because the correction screen catches the shaky one.
SHAKY_CONFIDENCE = 25.0

# A strip of the picture that is to hold a line of seventeen characters has to
# be several times wider than tall. These are the bounds of "several".
MIN_STRIP_ASPECT = 4.0
MAX_STRIP_ASPECT = 45.0
# The height a strip is blown up to before it is read. Tesseract loses thin
# strokes below roughly twenty pixels and gains nothing above two hundred.
STRIP_TARGET_HEIGHT = 96.0


def vin_check_digit_is_wrong(vin: str | None) -> bool:
    """True when the code carries a check digit and it does not add up.

    The ninth character is computed from the other sixteen, so a code that
    carries one and does not add up is misread somewhere — one character out
    of seventeen, perhaps, but misread. That is proof of a mistake, which is
    a different thing from low confidence: a shaky reading may still be
    right, this one certainly is not. It is still offered, because the person
    can see the plate and one wrong character is easy to put right — but it is
    offered with a warning that says what is wrong.

    Only applied where the ninth character *is* a check digit. Where the
    maker wrote a model code there, saying «не сошлась» is a false alarm,
    and trying to «fix» the character would write a VIN the plate does not
    carry — the one thing this project must never do.
    """

    return (
        bool(vin)
        and check_digit_is_possible(vin)
        and not vin_check_digit_matches(vin)
    )


def _codes_in_readings(
    observations: tuple[tuple[str, float], ...] | list[tuple[str, float]],
) -> dict[str, int]:
    """Every code shape seen in the readings, and how often.

    A reading is a line of raw OCR — the code with a label, a smudge or two
    words of small print stuck to either end. Counting only whole
    seventeen-character readings counts nothing at all: on his own form not
    one of a hundred and three readings came back exactly seventeen
    characters long, and everything built on that comparison — the «?» marks
    on the correction board above all — silently never fired. So each reading
    is searched for a code the way the engine itself searches.
    """

    tally: dict[str, int] = {}
    for text, _confidence in observations:
        for code in extract_vin_candidates(text):
            if not _looks_like_a_real_vin(code):
                continue
            tally[code] = tally.get(code, 0) + 1
    return tally


def is_fixable_vin(value: str | None) -> bool:
    """Seventeen characters, some of which may not have been read.

    A code on its way to being corrected is allowed to carry a «?» where the
    camera could not make a character out — that is the whole point of the
    correction board. A code on its way to the database is not; see
    :func:`is_valid_vin` for that.
    """

    if not value or len(value) != VIN_LENGTH:
        return False
    return all(char in VIN_ALLOWED or char == "?" for char in value)


def unsure_positions(
    vin: str | None,
    observations: tuple[tuple[str, float], ...] | list[tuple[str, float]],
    *,
    share: float = 0.0,
) -> dict[int, list[str]]:
    """Positions where the picture was read two different ways.

    The engine reads one photograph dozens of times — from every side, after
    every kind of preparation — and keeps every code it thought it saw. Where
    those readings disagree about one position, that position is where a
    correction is worth offering: the plate said one thing and the camera
    could not settle on it. Where all readings agree, the character is almost
    certainly right and asking about it only wastes his time.

    Only readings that nearly agree are allowed to vote. A code differing
    from this one in half its characters is not this code read badly — it is
    something else on the page, and letting it vote marks every position.
    ``share`` is how large the minority must be before the position counts as
    genuinely disputed: nothing at all by default, two fifths when the
    question is whether to write the character down or a «?».
    """

    if not vin or len(vin) != VIN_LENGTH:
        return {}
    tally = _codes_in_readings(observations)
    if not tally:
        return {}

    pool: list[str] = []
    for code, count in tally.items():
        differing = sum(a != b for a, b in zip(code, vin, strict=False))
        if differing <= 3:
            pool.extend([code] * count)
    if not pool:
        return {}

    seen: dict[int, dict[str, int]] = {}
    for code in pool:
        for index, char in enumerate(code):
            if char == vin[index] or char not in VIN_ALLOWED:
                continue
            seen.setdefault(index, {})
            seen[index][char] = seen[index].get(char, 0) + 1
    return {
        index: sorted(chars, key=lambda c: chars[c], reverse=True)
        for index, chars in seen.items()
        if sum(chars.values()) / len(pool) > share
    }


#: Every character a VIN may be built from, in the order it is offered for
#: correction. There is no I, O or Q: the standard forbids them, precisely
#: because a person copying a code by hand reads them as 1, 0 and 2.
VIN_ALPHABET: str = "".join(sorted(VIN_ALLOWED))


def single_character_fixes(vin: str | None) -> list[tuple[int, str]]:
    """Every one-character substitution that would make the code add up.

    The ninth character is worked out from the other sixteen, so a code that
    does not add up is wrong somewhere. Try each position against each
    character and the arithmetic usually leaves only one or two candidates —
    on the form that started all this, only «4» at the ninth place of
    «W1K1183121N245625» adds up, and that is the right answer. Those
    candidates are worth showing: one tap on the right one and the code is
    correct, and the rest is not typed again.
    """

    if (
        not vin
        or not is_valid_vin(vin)
        or not check_digit_is_possible(vin)
        or vin_check_digit_matches(vin)
    ):
        # A ninth character that is not a check digit leaves nothing to work
        # back from. Offering to «correct» it would be inventing a VIN.
        return []
    found: list[tuple[int, str]] = []
    for index in range(VIN_LENGTH):
        for char in VIN_ALPHABET:
            if char == vin[index]:
                continue
            trial = vin[:index] + char + vin[index + 1 :]
            if vin_check_digit_matches(trial):
                found.append((index, char))
    return found


#: How many independent readings must agree before a code is believed.
#:
#: The ninth character of a VIN is computed from the other sixteen, so a code
#: that adds up is very likely the real thing — but one reading in eleven
#: adds up *by chance*, and a line of garbage read off an upside-down picture
#: is exactly seventeen characters long. Trusting a single reading ended a
#: search that would have found the true code a moment later: on one of the
#: trial pictures the upside-down line read «97009T9A0S6VDDDES» once and
#: stopped everything, while turning the picture round gave the real code ten
#: times over. A code nobody agrees on is not a code.
SETTLED_READINGS = 3


def _promising(observations: list[tuple[str, float]]) -> bool:
    """Whether the readings hold anything that could be part of a code.

    The first pass cuts lines out of the picture and reads them. On a plate
    that works beautifully. On a whole A4 form it does not: the lines it finds
    are a date here, a signature there, and reading those again with the
    picture turned round is a waste of the person's time. So the second pass
    only runs when the first has turned up something worth turning.
    """

    for text, _confidence in observations:
        for quality in _extract_weighted_vin_candidates(text).values():
            if quality >= 5:
                return True
    return False


def _settled(
    observations: list[tuple[str, float]], at_least: int = SETTLED_READINGS
) -> bool:
    """True when the readings already hold a code that proves itself.

    A code is believed when its check digit adds up *and* several independent
    readings agree on it. Independence matters: the four preparations of a
    strip, its two page-segmentation modes, and the turn of the picture are
    separate witnesses, and a wrong line is not confirmed by all of them the
    way the right one is.
    """

    candidate = choose_best_candidate(observations)[0]
    if candidate is None or not vin_is_believable(candidate):
        return False
    return sum(1 for text, _ in observations if text == candidate) >= at_least


def judged_vin(result: OCRResult) -> tuple[str | None, bool]:
    """Return (the VIN to offer, whether the person should look twice).

    Every candidate that survived the shape rule is offered. Refusing one only
    ever hides the right answer, and the confirmation screen is where a wrong
    one is caught.
    """

    if not result.vin or not result.suffix6:
        return None, False
    confidence = result.confidence
    return result.vin, confidence is not None and confidence < SHAKY_CONFIDENCE


class OCRService:
    def __init__(self, tesseract_cmd: str | None = None) -> None:
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        cv2.setNumThreads(1)

    @staticmethod
    def _decode(image_bytes: bytes) -> np.ndarray:
        array = np.frombuffer(image_bytes, dtype=np.uint8)
        image = cv2.imdecode(array, cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("Неподдерживаемое или повреждённое изображение")

        height, width = image.shape[:2]
        longest = max(height, width)
        if longest > 2600:
            scale = 2600 / longest
            image = cv2.resize(
                image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA
            )
        return image

    @staticmethod
    def _text_and_confidence(data: dict[str, list[object]]) -> tuple[str, float]:
        lines: dict[tuple[int, int, int], list[str]] = defaultdict(list)
        confidences: list[float] = []
        item_count = len(data["text"])
        for index in range(item_count):
            word = str(data["text"][index]).strip()
            if not word:
                continue
            line_key = (
                int(data["block_num"][index]),
                int(data["par_num"][index]),
                int(data["line_num"][index]),
            )
            lines[line_key].append(word)
            try:
                confidence = float(data["conf"][index])
            except (TypeError, ValueError):
                continue
            if confidence >= 0:
                confidences.append(confidence)
        average = sum(confidences) / len(confidences) if confidences else 0.0
        text = "\n".join(" ".join(words) for words in lines.values())
        return text, average

    @classmethod
    def _read_variant(
        cls,
        image: np.ndarray,
        page_segmentation_mode: int,
        *,
        vin_only: bool = True,
    ) -> tuple[str, float]:
        config = f"--oem 3 --psm {page_segmentation_mode}"
        if vin_only:
            config += " -c tessedit_char_whitelist=ABCDEFGHJKLMNPRSTUVWXYZ0123456789"
        try:
            data = pytesseract.image_to_data(
                image,
                lang="eng",
                config=config,
                output_type=Output.DICT,
            )
        except (TesseractError, RuntimeError, OSError):
            # One degenerate crop (a few pixels of a phone photo, for example)
            # must not abort the whole recognition: the remaining variants are
            # still worth reading.
            logger.debug("Tesseract refused a variant, skipping it", exc_info=True)
            return "", 0.0
        return cls._text_and_confidence(data)

    @staticmethod
    def _quarter_turns(gray: np.ndarray) -> list[np.ndarray]:
        """The same picture turned a quarter turn, in the order worth trying.

        A phone held sideways writes the file sideways, and Tesseract only ever
        reads text that runs across the page: upright, such a photograph yields
        nothing at all, not even a fragment. One of his own pictures is exactly
        that — upright it reads «ao = \\ =~ oP», and turned a quarter turn the
        same picture gives «MERCEDES-BENZ» and the figures of a type plate.

        Tesseract's own orientation detector says which way round to try first,
        and its guess leads; the other turns follow, because on a dark plate
        the detector is often unsure.
        """

        clockwise = cv2.rotate(gray, cv2.ROTATE_90_CLOCKWISE)
        counter_clockwise = cv2.rotate(gray, cv2.ROTATE_90_COUNTERCLOCKWISE)
        upside_down = cv2.rotate(gray, cv2.ROTATE_180)
        ordered = [clockwise, counter_clockwise, upside_down]
        try:
            description = pytesseract.image_to_osd(gray)
        except (TesseractError, RuntimeError, OSError):
            return ordered
        match = re.search(r"Rotate:\s*(\d+)", description)
        if match is None:
            return ordered
        if match.group(1) == "90":
            return [clockwise, counter_clockwise, upside_down]
        if match.group(1) == "270":
            return [counter_clockwise, clockwise, upside_down]
        return [upside_down, clockwise, counter_clockwise]

    @classmethod
    def _read_turned(
        cls, gray: np.ndarray
    ) -> tuple[str | None, float | None, list[tuple[str, float]]]:
        """Last resort: read the picture sideways.

        Only a picture that nothing could read upright gets here, so the extra
        half minute is paid by the difficult photograph alone.

        Every turn is read, and the winner is chosen afterwards from all of
        them together. Stopping at the first turn that answers would be a
        mistake: text turned the wrong way round is not read badly, it is
        scrambled into a different, equally well formed seventeen characters,
        and the first turn tried is as likely to be the scrambled one as the
        right one. The ordinary scoring settles it — a genuine reading keeps
        its check digit, and a scrambled one loses it.
        """

        collected: list[tuple[str, float]] = []
        for turned in cls._quarter_turns(gray):
            variants = cls._variants(turned)
            for variant in variants[:2]:
                for page_segmentation_mode in (7, 6, 11):
                    text, confidence = cls._read_variant(
                        variant, page_segmentation_mode
                    )
                    if text:
                        collected.append((text, confidence))
            # Unrestricted, so that a German field name survives to be weighed.
            text, confidence = cls._read_variant(variants[0], 11, vin_only=False)
            if text:
                collected.append((text, confidence))
            # His plate is black: the characters are light on dark, and only
            # the negative shows them. One inverted pass per turn is enough.
            for page_segmentation_mode in (7, 6):
                text, confidence = cls._read_variant(
                    cv2.bitwise_not(variants[2]), page_segmentation_mode
                )
                if text:
                    collected.append((text, confidence))
        if not collected:
            return None, None, collected
        vin, found = choose_best_candidate(collected, require_agreement=True)
        if vin:
            logger.info("VIN найден только на повёрнутом снимке: %s", vin)
        return vin, found, collected

    @classmethod
    def _read_inside_out(
        cls,
        observations: list[tuple[str, float]],
        variants: list[np.ndarray],
    ) -> tuple[str | None, float | None]:
        """Second sweep, for a plate printed light on a dark ground.

        Only the binarised copies are turned inside out: inverting a grey
        photograph turns the text into a bright ghost that reads worse than
        the original. Four extra passes, and only on a picture nothing else
        could read. A code that comes out of this with its check digit broken
        has one character repaired, where the repair is unambiguous.
        """

        for variant in variants[:2]:
            binary = cv2.threshold(
                variant, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
            )[1]
            inverted = cv2.bitwise_not(binary)
            for page_segmentation_mode in (7, 13):
                reading, confidence = cls._read_variant(
                    inverted, page_segmentation_mode
                )
                if reading:
                    observations.append((reading, confidence))
        vin, confidence = choose_best_candidate(observations)
        if vin is not None and vin_check_digit_is_wrong(vin):
            repaired = repair_vin(vin)
            if repaired is not None:
                logger.info(
                    "Прочитанный VIN %s не прошёл проверку контрольной цифры, "
                    "исправлен один похожий символ: %s",
                    vin,
                    repaired,
                )
                vin = repaired
        return vin, confidence

    def recognize(self, image_bytes: bytes) -> OCRResult:
        """Read a VIN off a photograph.

        The reading itself lives in :mod:`app.vin_reader`, written from
        scratch: it looks at the picture from every side a phone could have
        taken it from, lets Tesseract find the lines, judges each line by what
        is written in it — never by a word beside it — and believes a code only
        when several readings agree and the check digit holds.
        """

        from .vin_reader import read as read_vin

        try:
            vin, confidence, observations = read_vin(image_bytes)
        except pytesseract.TesseractNotFoundError as exc:
            raise OCRUnavailableError("Исполняемый файл Tesseract не найден") from exc
        except pytesseract.TesseractError as exc:
            raise OCRUnavailableError(f"Ошибка Tesseract: {exc}") from exc

        raw_text = "\n".join(text for text, _ in observations)[:4000]
        if vin:
            note = f" (уверенность {confidence}%)"
            if vin_check_digit_is_wrong(vin):
                note += (
                    " — контрольная цифра не сошлась, минимум один символ прочитан "
                    "неверно, человеку показано предупреждение"
                )
            elif confidence is not None and confidence < SHAKY_CONFIDENCE:
                note += " — прочитано неуверенно, человеку показано предупреждение"
            logger.info("VIN прочитан: %s%s", vin, note)
        elif raw_text.strip():
            logger.info(
                "VIN на фото не найден. Что прочиталось: %s",
                " | ".join(raw_text.split())[:600],
            )
        else:
            logger.info("VIN на фото не найден: на снимке нет читаемого текста.")
        return OCRResult(
            vin=vin,
            suffix6=vin[-6:] if vin else None,
            confidence=confidence,
            raw_text=raw_text,
            observations=tuple(observations),
        )
