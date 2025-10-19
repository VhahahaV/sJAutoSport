from __future__ import annotations

import asyncio
from io import BytesIO
from typing import Tuple

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    np = None

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None

try:
    import pytesseract  # type: ignore
except Exception:  # pragma: no cover
    pytesseract = None


def _preprocess(image_bytes: bytes):
    if not Image:
        return None
    image = Image.open(BytesIO(image_bytes))
    image = image.convert("L")
    if cv2 and np:
        arr = np.array(image)
        _, thresh = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        opened = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
        image = Image.fromarray(opened)
    else:
        image = image.point(lambda x: 0 if x < 140 else 255, "1")
    return image


def solve_captcha(image_bytes: bytes) -> Tuple[str, float]:
    if not pytesseract or not Image:
        return "", 0.0
    image = _preprocess(image_bytes)
    if image is None:
        return "", 0.0
    config = "--psm 7 --oem 1 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT, config=config)
    text = (data.get("text") or [])
    text_str = "".join(text).strip().replace(" ", "")
    confidences = [int(c) for c in data.get("conf", []) if c not in (-1, "-1")]
    confidence = (sum(confidences) / len(confidences) / 100.0) if confidences else 0.0
    return text_str, confidence


async def solve_captcha_async(image_bytes: bytes) -> Tuple[str, float]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, solve_captcha, image_bytes)
