from __future__ import annotations

import base64
import io

import cv2
import numpy as np
from PIL import Image


def _decode_image_bytes(raw: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(raw)) as img:
        rgb = img.convert("RGB")
        arr = np.array(rgb)
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def decode_input_to_image(file_base64: str, mime_type: str) -> np.ndarray:
    try:
        raw = base64.b64decode(file_base64, validate=True)
    except Exception as exc:
        raise ValueError("Invalid base64 payload") from exc
    if not raw:
        raise ValueError("Empty file payload")

    # PDF pipeline can be enabled with pdf2image + poppler in cloud deploy.
    if "pdf" in (mime_type or "").lower():
        try:
            from pdf2image import convert_from_bytes
        except Exception as exc:
            raise ValueError(
                "PDF input requires pdf2image/poppler at runtime"
            ) from exc
        pages = convert_from_bytes(raw, dpi=300, first_page=1, last_page=1)
        if not pages:
            raise ValueError("No pages decoded from PDF")
        rgb = pages[0].convert("RGB")
        arr = np.array(rgb)
        img = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    else:
        img = _decode_image_bytes(raw)

    # Denoise + adaptive threshold baseline preprocessing.
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    _ = cv2.adaptiveThreshold(
        blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 35, 7
    )
    return img
