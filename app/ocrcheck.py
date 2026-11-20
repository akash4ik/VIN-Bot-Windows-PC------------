"""Print, line by line, what the bot sees in one photograph.

He says version twelve read «W1VVLCEZ3S4431913» from a picture of the plate in
the door opening and the current build does not. Every plate I can build here
is read by both, so the difference has to be something about that particular
picture, and I cannot look at it. This is the instrument for that: point it at
the file and it prints every single reading — each treatment of the picture
against each layout mode — with the confidence the camera gave it, and then
what the engine made of it all.

    python -m app.ocrcheck "C:\\Users\\Rich\\Desktop\\vin.jpg"

The output is a few dozen short lines. Send them, and the reason is visible.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

from app.ocr import OCRService

# Every layout mode the engine itself uses, plus the two it does not.
PAGE_MODES = (6, 7, 11, 13, 4)


def one_line(text: str, limit: int = 90) -> str:
    flat = " ⏎ ".join(part.strip() for part in text.splitlines() if part.strip())
    return flat[:limit] + ("…" if len(flat) > limit else "")


def describe(image: np.ndarray) -> str:
    height, width = image.shape[:2]
    return f"{width}×{height}"


def report(path: str) -> str:
    service = OCRService()
    payload = Path(path).read_bytes()
    lines: list[str] = [f"Файл: {path}"]

    source = service._decode(payload)
    longest = max(source.shape[:2])
    lines.append(f"Размер после приёма: {describe(source)}")
    image = service._resize_to_longest(source, 1200) if longest < 1200 else source
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    lines.append(f"Размер в работе: {describe(gray)}")

    variants = service._variants(gray)
    names = ["серый", "резкий", "порог", "адаптивный"]
    if len(variants) > 4:
        names.append("крупнее")
    straight = service._deskew(gray)
    if straight is not gray:
        variants += service._variants(straight)[2:]
        names += ["порог (выровнен)", "адаптивный (выровнен)"]

    for name, variant in zip(names, variants):
        for mode in PAGE_MODES:
            try:
                text, confidence = service._read_variant(variant, mode)
            except Exception as exc:  # noqa: BLE001 - a report, not the bot
                lines.append(f"{name:<18} psm{mode:<3} сбой {type(exc).__name__}")
                continue
            lines.append(
                f"{name:<18} psm{mode:<3} {confidence:5.1f}%  {one_line(text)}"
            )

    # The same picture turned inside out, as the engine does when it fails once.
    inverted = [cv2.bitwise_not(variant) for variant in variants[2:4]]
    for index, variant in enumerate(inverted):
        for mode in (7, 6):
            text, confidence = service._read_variant(variant, mode)
            lines.append(
                f"{'наизнанку ' + str(index + 1):<18} psm{mode:<3} "
                f"{confidence:5.1f}%  {one_line(text)}"
            )

    # Unrestricted reads keep labels, spaces and the letters I, O, Q.
    for name, variant in list(zip(names, variants))[:2]:
        for mode in (4, 11):
            text, confidence = service._read_variant(variant, mode, vin_only=False)
            lines.append(
                f"{name + ' (все буквы)':<18} psm{mode:<3} "
                f"{confidence:5.1f}%  {one_line(text)}"
            )

    result = service.recognize(payload)
    lines.append("")
    lines.append(f"Итог движка: VIN={result.vin} уверенность={result.confidence}")
    lines.append(
        "Что бот показал бы: "
        + (
            "ничего, попросил бы снимок получше"
            if result.vin is None
            else f"{result.vin} (сверьте на экране)"
        )
    )
    return "\n".join(lines)


def main() -> None:
    if len(sys.argv) < 2:
        print('Укажите файл: python -m app.ocrcheck "путь\\к\\фото.jpg"')
        print("Можно просто перетащить файл на OCR-CHECK.cmd.")
        return
    try:
        print(report(sys.argv[1]))
    except Exception as exc:  # noqa: BLE001
        print(f"Не удалось разобрать файл: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
