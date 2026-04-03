#!/usr/bin/env python3
"""
Shared OCR adapter with GLM-OCR primary and Tesseract fallback.
"""

from __future__ import annotations

import base64
import json
import os
import pathlib
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

import cv2
import numpy as np
import pytesseract


def _read_json(path: pathlib.Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _candidate_tesseract_paths() -> list[str]:
    return [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]


class OcrEngine:
    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        glm = config.get("glmocr", {}) if isinstance(config.get("glmocr", {}), dict) else {}
        tess = config.get("tesseract", {}) if isinstance(config.get("tesseract", {}), dict) else {}
        self.glm_enabled = bool(glm.get("enabled", True))
        self.glm_endpoint = str(glm.get("endpoint", "http://127.0.0.1:8000/ocr"))
        self.glm_timeout_s = float(glm.get("timeout_s", 3.0))
        self.glm_retries = max(0, int(glm.get("retries", 1)))
        self.glm_api_style = str(glm.get("api_style", "http_json")).lower()
        self.glm_model = str(glm.get("model", "glm-ocr"))
        self.glm_api_key = str(os.environ.get("GLMOCR_API_KEY", glm.get("api_key", "") or ""))
        self.fallback_enabled = bool(config.get("fallback_to_tesseract", True))

        tesseract_cmd = str(os.environ.get("TESSERACT_CMD", tess.get("cmd", "") or "")).strip()
        if tesseract_cmd and pathlib.Path(tesseract_cmd).exists():
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        else:
            for p in _candidate_tesseract_paths():
                if pathlib.Path(p).exists():
                    pytesseract.pytesseract.tesseract_cmd = p
                    break

        self.diagnostics: Dict[str, Any] = {
            "engine_primary": "glmocr",
            "engine_fallback": "tesseract",
            "calls": 0,
            "primary_success": 0,
            "primary_failures": 0,
            "fallback_success": 0,
            "fallback_failures": 0,
            "errors": [],
        }

    def _note_error(self, where: str, error: str) -> None:
        self.diagnostics["errors"].append({"where": where, "error": error})
        self.diagnostics["errors"] = self.diagnostics["errors"][-20:]

    def get_diagnostics(self) -> Dict[str, Any]:
        return dict(self.diagnostics)

    def _image_to_png_bytes(self, image: np.ndarray) -> bytes:
        ok, buf = cv2.imencode(".png", image)
        if not ok:
            raise RuntimeError("png_encode_failed")
        return bytes(buf)

    def _glm_ocr_text_http_json(self, image: np.ndarray, context: str = "") -> str:
        payload = {
            "image_base64": base64.b64encode(self._image_to_png_bytes(image)).decode("ascii"),
            "context": context,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.glm_endpoint, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        if self.glm_api_key:
            req.add_header("Authorization", f"Bearer {self.glm_api_key}")
        with urllib.request.urlopen(req, timeout=self.glm_timeout_s) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
        raw = json.loads(body) if body.strip() else {}
        if isinstance(raw, dict):
            for k in ("text", "output_text", "result", "content"):
                v = raw.get(k)
                if isinstance(v, str) and v.strip():
                    return v
        raise RuntimeError("glm_http_json_no_text")

    def _glm_ocr_text_openai_compat(self, image: np.ndarray, context: str = "") -> str:
        png_b64 = base64.b64encode(self._image_to_png_bytes(image)).decode("ascii")
        prompt = context or "Extract all visible text from this image."
        payload = {
            "model": self.glm_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{png_b64}"}},
                    ],
                }
            ],
            "temperature": 0,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.glm_endpoint, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        if self.glm_api_key:
            req.add_header("Authorization", f"Bearer {self.glm_api_key}")
        with urllib.request.urlopen(req, timeout=self.glm_timeout_s) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
        raw = json.loads(body) if body.strip() else {}
        choices = raw.get("choices", []) if isinstance(raw, dict) else []
        if isinstance(choices, list) and choices:
            msg = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                return content
        raise RuntimeError("glm_openai_no_text")

    def _glm_ocr_text(self, image: np.ndarray, context: str = "") -> str:
        if self.glm_api_style == "openai_chat_completions":
            return self._glm_ocr_text_openai_compat(image=image, context=context)
        return self._glm_ocr_text_http_json(image=image, context=context)

    def _tesseract_text(self, image: np.ndarray, psm: int = 6, whitelist: str = "") -> str:
        cfg = f"--psm {int(psm)}"
        if whitelist:
            cfg += f" -c tessedit_char_whitelist={whitelist}"
        return pytesseract.image_to_string(image, config=cfg).strip()

    def ocr_text(
        self,
        image: np.ndarray,
        *,
        context: str = "",
        psm: int = 6,
        whitelist: str = "",
    ) -> Dict[str, Any]:
        self.diagnostics["calls"] += 1
        last_error = ""
        if self.glm_enabled:
            for _ in range(self.glm_retries + 1):
                try:
                    text = self._glm_ocr_text(image=image, context=context).strip()
                    if text:
                        self.diagnostics["primary_success"] += 1
                        return {
                            "ok": True,
                            "text": text,
                            "engine_used": "glmocr",
                            "fallback_used": False,
                            "fallback_reason": "",
                        }
                    last_error = "empty_glm_text"
                except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
                    last_error = str(exc)
                except Exception as exc:  # pragma: no cover
                    last_error = str(exc)
            self.diagnostics["primary_failures"] += 1
            self._note_error("glmocr", last_error or "glm_unknown_error")

        if self.fallback_enabled:
            try:
                text = self._tesseract_text(image=image, psm=psm, whitelist=whitelist)
                self.diagnostics["fallback_success"] += 1
                return {
                    "ok": bool(text.strip()),
                    "text": text.strip(),
                    "engine_used": "tesseract",
                    "fallback_used": True,
                    "fallback_reason": last_error or "glm_unavailable",
                }
            except Exception as exc:
                self.diagnostics["fallback_failures"] += 1
                self._note_error("tesseract", str(exc))
                return {
                    "ok": False,
                    "text": "",
                    "engine_used": "none",
                    "fallback_used": True,
                    "fallback_reason": last_error or "glm_unavailable",
                    "error": str(exc),
                }

        return {
            "ok": False,
            "text": "",
            "engine_used": "none",
            "fallback_used": False,
            "fallback_reason": "fallback_disabled",
            "error": last_error or "no_ocr_engine_available",
        }

    def ocr_data(
        self,
        image: np.ndarray,
        *,
        context: str = "",
        psm: int = 6,
        whitelist: str = "",
    ) -> Dict[str, Any]:
        txt = self.ocr_text(image=image, context=context, psm=psm, whitelist=whitelist)
        text = str(txt.get("text", "") or "")
        # Structured data parity with pytesseract Output.DICT
        data = {
            "text": [text] if text else [],
            "conf": [95] if text else [],
            "left": [0] if text else [],
            "top": [0] if text else [],
            "width": [int(image.shape[1])] if text else [],
            "height": [int(image.shape[0])] if text else [],
            "line_num": [1] if text else [],
            "par_num": [1] if text else [],
            "block_num": [1] if text else [],
        }
        out = dict(txt)
        out["data"] = data
        return out


def create_ocr_engine(config_path: str = "scripts/ocr_engine.config.json") -> OcrEngine:
    cfg = _read_json(pathlib.Path(config_path))
    return OcrEngine(config=cfg)

