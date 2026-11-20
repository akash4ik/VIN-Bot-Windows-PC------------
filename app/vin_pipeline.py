"""The pictures the cloud is shown: one frame, prepared several ways.

Sending the photograph as it arrived from the camera throws away most of the
help. A VIN etched into glass is low-contrast; on a paper invoice it is two
pixels tall; under a windscreen wiper it is half gone. Each of those yields to
a different treatment, and a model looking at one version cannot tell which
version would have worked.

So the cloud is sent the same frame several times over — enlarged, contrast-
stretched, sharpened and thresholded — plus tight crops of the places that
look like a line of stamped characters. It is one request carrying several
views, not several requests: the model weighs them together, and the cost is
one call.

Everything here is CPU-bound OpenCV, so callers must push it into a thread.
Nothing here talks to the network.
"""

from __future__ import annotations

import logging

import cv2
import numpy as np

logger = logging.getLogger(__name__)

#: Wider than this a picture is left alone; narrower, it is enlarged, because
#: a code that is 40 pixels wide is not a reading, it is a guess.
MIN_WIDTH = 1600
#: ...and narrower than this a picture is brought down. A 2560-pixel frame put
#: through CLAHE weighs over a megabyte on its own, and seven of those make a
#: request that is slower to upload than it is to read. The crops are what
#: carry fine detail, and they are cut before anything is reduced.
MAX_WIDTH = 1600
JPEG_QUALITY = 92
#: Google is sent at most this many pictures: the four treatments plus crops.
MAX_PICTURES = 7
VARIANT_NAMES = ("original", "clahe", "sharpen", "binarized")


def _decode(image_bytes: bytes) -> np.ndarray:
    """Read the bytes into a BGR frame, or say plainly that they are not one."""

    if not image_bytes:
        raise ValueError("cannot decode image")
    buffer = np.frombuffer(image_bytes, dtype=np.uint8)
    frame = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("cannot decode image")
    return frame


def _jpeg(frame: np.ndarray) -> bytes:
    """Encode as JPEG. Every picture sent is a JPEG, so the mime type is one."""

    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not ok:
        raise ValueError("cannot decode image")
    return encoded.tobytes()


def _fit(frame: np.ndarray) -> np.ndarray:
    """Bring the frame to a workable width, up or down.

    Small pictures are enlarged because a code forty pixels wide is not a
    reading. Large ones are reduced because a megabyte of sharpened noise is
    slower to send than the detail it adds — and the tight crops, which are
    cut before this runs, keep the fine detail anyway.
    """

    width = frame.shape[1]
    if width == MIN_WIDTH:
        return frame
    if width < MIN_WIDTH:
        scale = MIN_WIDTH / max(1, width)
        return cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_LANCZOS4)
    if width <= MAX_WIDTH:
        return frame
    scale = MAX_WIDTH / width
    return cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)


def picture_variants(image_bytes: bytes) -> dict[str, bytes]:
    """Return the same photograph four ways, always all four.

    ``original`` is enlarged when it is small; ``clahe`` stretches contrast
    without blowing out the bright half, which is what a windscreen photograph
    needs; ``sharpen`` restores edge detail a soft focus has smeared; and
    ``binarized`` throws away everything but the marks, which is the last
    resort for a code printed faintly on paper.

    Raises ValueError when the bytes are not a picture at all.
    """

    frame = _decode(image_bytes)

    original = _fit(frame)

    lab = cv2.cvtColor(original, cv2.COLOR_BGR2LAB)
    lightness, green_red, blue_yellow = cv2.split(lab)
    stretched = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(lightness)
    contrast = cv2.cvtColor(
        cv2.merge((stretched, green_red, blue_yellow)), cv2.COLOR_LAB2BGR
    )

    # Unsharp mask: keep the detail, push back the blur around it.
    smoothed = cv2.GaussianBlur(original, (0, 0), sigmaX=1.0)
    sharpened = cv2.addWeighted(original, 2.5, smoothed, -1.5, 0)
    # The colour version of the denoiser: a colour frame is what we hold.
    sharpened = cv2.fastNlMeansDenoisingColored(
        sharpened, None, h=5, hColor=5, templateWindowSize=7, searchWindowSize=21
    )

    grey = cv2.cvtColor(original, cv2.COLOR_BGR2GRAY)
    thresholded = cv2.adaptiveThreshold(
        grey, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15
    )
    thresholded = cv2.cvtColor(thresholded, cv2.COLOR_GRAY2BGR)

    return {
        "original": _jpeg(original),
        "clahe": _jpeg(contrast),
        "sharpen": _jpeg(sharpened),
        "binarized": _jpeg(thresholded),
    }


def text_crops(image_bytes: bytes, max_crops: int = 3) -> list[bytes]:
    """Tight pictures of the bands that look like a line of characters.

    A code is a wide, thin band of ink. Sobel along X lights up vertical
    strokes, closing joins those strokes into words, and dilating joins the
    words into a line. What is left is filtered by shape: at least three times
    wider than tall, tall enough to hold a character, and large enough not to
    be a speck of dirt.

    The upper bound on that ratio is 25, not the 12 the usual recipe gives,
    and it was measured, not picked: a drawn line reading
    ``1HGBH41JXMN109186`` comes out at 13.8 to one. Seventeen characters is a
    long line, so a ceiling of twelve throws away exactly the thing being
    looked for — which is how this filter first found nothing at all on a
    frame that plainly carried a code.

    Returning nothing is a normal answer, not a failure: plenty of frames
    carry no such band, and the caller carries on without them.
    """

    if max_crops <= 0:
        return []
    frame = _decode(image_bytes)
    if frame.size == 0:
        return []

    grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    sobel = cv2.Sobel(grey, cv2.CV_64F, 1, 0, ksize=3)
    strength = np.absolute(sobel)
    biggest = float(strength.max()) if strength.size else 0.0
    if biggest <= 0.0:
        # A perfectly flat frame has no strokes at all, so no lines either.
        return []
    scaled = np.uint8(strength * (255.0 / biggest))

    _level, binary = cv2.threshold(
        scaled, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (17, 3))
    closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    joined = cv2.dilate(closed, kernel, iterations=1)

    found = cv2.findContours(joined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    # OpenCV 4 hands back (contours, hierarchy); OpenCV 3 added the frame.
    contours = found[0] if len(found) == 2 else found[1]

    height, width = frame.shape[:2]
    frame_area = max(1, height * width)
    boxes: list[tuple[int, int, int, int, int]] = []
    for contour in contours:
        left, top, box_width, box_height = cv2.boundingRect(contour)
        if box_height <= 20:
            continue
        ratio = box_width / max(1, box_height)
        if ratio < 3.0 or ratio > 25.0:
            continue
        if box_width * box_height <= 0.001 * frame_area:
            continue
        # Ten per cent of padding each way: the outermost characters are the
        # ones a tight box cuts in half.
        pad_x = max(1, int(box_width * 0.10))
        pad_y = max(1, int(box_height * 0.10))
        boxes.append(
            (
                box_width * box_height,
                max(0, left - pad_x),
                max(0, top - pad_y),
                min(width, left + box_width + pad_x),
                min(height, top + box_height + pad_y),
            )
        )

    boxes.sort(key=lambda box: box[0], reverse=True)

    crops: list[bytes] = []
    for _area, left, top, right, bottom in boxes[:max_crops]:
        piece = frame[top:bottom, left:right]
        if piece.size:
            crops.append(_jpeg(piece))
    return crops


def cloud_pictures(image_bytes: bytes, max_pictures: int = MAX_PICTURES) -> list[bytes]:
    """The set of pictures to put in front of the model.

    The four treatments first, then as many crops as there is room for. When
    there is room for only some of the crops, the largest go: they are the
    likeliest to be the code.
    """

    variants = picture_variants(image_bytes)
    pictures = [variants[name] for name in VARIANT_NAMES]

    room = max(0, max_pictures - len(pictures))
    if room:
        pictures.extend(text_crops(image_bytes, max_crops=3)[:room])

    if len(pictures) > max_pictures:
        pictures = pictures[:max_pictures]
    return pictures
