from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml

try:
    import cv2
except Exception as exc:  # pragma: no cover - import guard
    raise RuntimeError(
        "opencv-python is required for takeoff preprocessing. "
        "Install dependencies from takeoff_agent/requirements.txt."
    ) from exc


SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}


@dataclass(slots=True)
class PlanPage:
    page_index: int
    source_name: str
    image_bgr: np.ndarray
    scale_ft_per_px: float
    metadata: dict[str, Any]


def load_config(path: str | Path) -> dict[str, Any]:
    cfg_path = Path(path)
    if not cfg_path.exists():
        raise FileNotFoundError(f"Config file not found: {cfg_path}")
    with cfg_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _estimate_scale_from_text(image_bgr: np.ndarray, default_ft_per_px: float) -> float:
    """
    Best-effort OCR scale extraction.

    We intentionally keep this optional so the pipeline still runs without PaddleOCR.
    Looks for tokens like:
      - 1/8" = 1'
      - SCALE: 1/4"=1'-0"
    """
    try:
        from paddleocr import PaddleOCR  # type: ignore
    except Exception:
        return default_ft_per_px

    ocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
    rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    lines = ocr.ocr(rgb, cls=True) or []

    text = " ".join(
        item[1][0]
        for page_items in lines
        for item in (page_items or [])
        if item and len(item) > 1 and item[1]
    )
    match = re.search(r"(\d+)\s*/\s*(\d+)\s*\"\s*=\s*1\s*'", text)
    if not match:
        return default_ft_per_px

    numerator = float(match.group(1))
    denominator = float(match.group(2))
    if denominator <= 0:
        return default_ft_per_px

    inches_on_plan_for_one_foot = numerator / denominator
    # Conservative fallback: estimate pixel density for plan images around ~96 px/in.
    pixels_per_inch = 96.0
    pixels_per_foot = inches_on_plan_for_one_foot * pixels_per_inch
    return 1.0 / max(pixels_per_foot, 1e-6)


def _pdf_to_images(path: Path, dpi: int) -> list[np.ndarray]:
    try:
        from pdf2image import convert_from_path  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "pdf2image is required for PDF input. "
            "Install dependencies from takeoff_agent/requirements.txt."
        ) from exc

    pages = convert_from_path(str(path), dpi=dpi)
    images_bgr: list[np.ndarray] = []
    for page in pages:
        rgb = np.array(page)
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        images_bgr.append(bgr)
    return images_bgr


def _image_from_path(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Could not read image at {path}")
    return image


def denoise_and_threshold(image_bgr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    thresh = cv2.adaptiveThreshold(
        blurred,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        41,
        5,
    )
    return blurred, thresh


def load_plan_pages(input_path: str | Path, config: dict[str, Any]) -> list[PlanPage]:
    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(f"Input does not exist: {path}")

    dpi = int(config.get("preprocess", {}).get("pdf_dpi", 300))
    default_ft_per_px = float(
        config.get("scale", {}).get("default_ft_per_px", 1.0 / 48.0)
    )
    auto_detect_scale = bool(config.get("scale", {}).get("auto_detect", True))

    if path.suffix.lower() == ".pdf":
        images = _pdf_to_images(path, dpi=dpi)
    elif path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS:
        images = [_image_from_path(path)]
    else:
        raise ValueError(
            f"Unsupported input extension '{path.suffix}'. "
            "Expected PDF, PNG, JPG, WEBP, or TIFF."
        )

    pages: list[PlanPage] = []
    for idx, image in enumerate(images, start=1):
        if auto_detect_scale:
            scale = _estimate_scale_from_text(image, default_ft_per_px)
        else:
            scale = default_ft_per_px

        pages.append(
            PlanPage(
                page_index=idx,
                source_name=path.name,
                image_bgr=image,
                scale_ft_per_px=scale,
                metadata={"width": int(image.shape[1]), "height": int(image.shape[0])},
            )
        )
    return pages
