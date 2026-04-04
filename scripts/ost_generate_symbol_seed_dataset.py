#!/usr/bin/env python3
"""
Generate a local seed symbol dataset for ingestion bootstrap.
"""

from __future__ import annotations

import argparse
import pathlib
import random

import cv2
import numpy as np


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate seed symbol image dataset")
    p.add_argument("--output-root", required=True)
    p.add_argument("--per-class", type=int, default=120)
    p.add_argument("--size", type=int, default=96)
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


def _blank(size: int) -> np.ndarray:
    return np.full((size, size, 3), 255, dtype=np.uint8)


def _noise(img: np.ndarray) -> np.ndarray:
    n = np.random.normal(0, 7, img.shape).astype(np.int16)
    out = np.clip(img.astype(np.int16) + n, 0, 255).astype(np.uint8)
    return out


def draw_door(size: int) -> np.ndarray:
    img = _blank(size)
    x0, y0 = int(size * 0.18), int(size * 0.22)
    x1, y1 = int(size * 0.72), int(size * 0.78)
    cv2.rectangle(img, (x0, y0), (x1, y1), (0, 0, 0), 2)
    cx, cy = x0, y1
    r = int(size * 0.50)
    cv2.ellipse(img, (cx, cy), (r, r), 0, 270, 360, (0, 0, 0), 2)
    cv2.circle(img, (int(x1 - size * 0.06), int((y0 + y1) / 2)), 2, (0, 0, 0), -1)
    return _noise(img)


def draw_door_frame(size: int) -> np.ndarray:
    img = _blank(size)
    x0, y0 = int(size * 0.2), int(size * 0.2)
    x1, y1 = int(size * 0.8), int(size * 0.8)
    cv2.rectangle(img, (x0, y0), (x1, y1), (0, 0, 0), 3)
    cv2.rectangle(img, (x0 + 8, y0 + 8), (x1 - 8, y1 - 8), (0, 0, 0), 2)
    return _noise(img)


def draw_window(size: int) -> np.ndarray:
    img = _blank(size)
    x0, y0 = int(size * 0.2), int(size * 0.3)
    x1, y1 = int(size * 0.8), int(size * 0.7)
    cv2.rectangle(img, (x0, y0), (x1, y1), (0, 0, 0), 2)
    cv2.line(img, (int((x0 + x1) / 2), y0), (int((x0 + x1) / 2), y1), (0, 0, 0), 2)
    cv2.line(img, (x0, int((y0 + y1) / 2)), (x1, int((y0 + y1) / 2)), (0, 0, 0), 2)
    return _noise(img)


def draw_sink(size: int) -> np.ndarray:
    img = _blank(size)
    c = (int(size * 0.5), int(size * 0.55))
    cv2.ellipse(img, c, (int(size * 0.28), int(size * 0.18)), 0, 0, 360, (0, 0, 0), 2)
    cv2.ellipse(img, c, (int(size * 0.18), int(size * 0.11)), 0, 0, 360, (0, 0, 0), 2)
    cv2.line(img, (int(size * 0.5), int(size * 0.3)), (int(size * 0.5), int(size * 0.4)), (0, 0, 0), 2)
    return _noise(img)


def draw_toilet(size: int) -> np.ndarray:
    img = _blank(size)
    cv2.ellipse(img, (int(size * 0.5), int(size * 0.6)), (int(size * 0.2), int(size * 0.28)), 0, 0, 360, (0, 0, 0), 2)
    cv2.ellipse(img, (int(size * 0.5), int(size * 0.6)), (int(size * 0.12), int(size * 0.2)), 0, 0, 360, (0, 0, 0), 2)
    cv2.rectangle(img, (int(size * 0.39), int(size * 0.22)), (int(size * 0.61), int(size * 0.36)), (0, 0, 0), 2)
    return _noise(img)


def main() -> int:
    args = parse_args()
    random.seed(int(args.seed))
    np.random.seed(int(args.seed))
    root = pathlib.Path(args.output_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    per_class = max(10, int(args.per_class))
    size = max(48, int(args.size))

    classes = {
        "door": draw_door,
        "door_frame": draw_door_frame,
        "window": draw_window,
        "sink": draw_sink,
        "toilet": draw_toilet,
    }
    for cls, fn in classes.items():
        cdir = root / cls
        cdir.mkdir(parents=True, exist_ok=True)
        for i in range(1, per_class + 1):
            img = fn(size)
            angle = random.choice([0, 0, 0, 90, 180, 270])
            if angle != 0:
                M = cv2.getRotationMatrix2D((size / 2, size / 2), angle, 1.0)
                img = cv2.warpAffine(img, M, (size, size), borderValue=(255, 255, 255))
            out = cdir / f"{cls}_{i:04d}.png"
            cv2.imwrite(str(out), img)
    print(str(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

