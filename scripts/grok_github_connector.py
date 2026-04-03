#!/usr/bin/env python3
"""
Connector for Grok troubleshooting via:
  - GitHub Models
  - Direct xAI OpenAI-compatible endpoint

Requires:
  - mode=github: GITHUB_TOKEN env var with `models:read`
  - mode=xai: XAI_API_KEY env var
Optional:
  - GROK_GITHUB_MODEL (default: xai/grok-3-mini)
  - GROK_GITHUB_ENDPOINT (default: https://models.github.ai/inference/chat/completions)
  - GROK_XAI_MODEL (default: grok-4.20-0309-reasoning)
  - GROK_XAI_ENDPOINT (default: https://api.x.ai/v1/chat/completions)
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List


DEFAULT_ENDPOINT = "https://models.github.ai/inference/chat/completions"
DEFAULT_MODEL = "xai/grok-3-mini"
XAI_DEFAULT_ENDPOINT = "https://api.x.ai/v1/chat/completions"
XAI_DEFAULT_MODEL = "grok-4.20-0309-reasoning"


def read_text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def save_json(path: pathlib.Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_env_file(path: pathlib.Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    vals: Dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        key = k.strip()
        if key:
            vals[key] = v.strip().strip('"').strip("'")
    return vals


def build_messages(system_prompt: str, user_prompt: str, context: str) -> List[Dict[str, str]]:
    content = user_prompt
    if context.strip():
        content += "\n\nContext:\n" + context.strip()
    return [
        {"role": "system", "content": system_prompt.strip()},
        {"role": "user", "content": content.strip()},
    ]


def call_github_models(
    token: str,
    endpoint: str,
    model: str,
    messages: List[Dict[str, str]],
    max_tokens: int = 900,
    temperature: float = 0.1,
    timeout_s: float = 30.0,
) -> Dict[str, Any]:
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": int(max_tokens),
        "temperature": float(temperature),
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(endpoint, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        body = resp.read().decode("utf-8", errors="ignore")
    parsed = json.loads(body) if body.strip() else {}
    return parsed if isinstance(parsed, dict) else {"raw": parsed}


def call_xai_openai_compat(
    api_key: str,
    endpoint: str,
    model: str,
    messages: List[Dict[str, str]],
    max_tokens: int = 900,
    temperature: float = 0.1,
    timeout_s: float = 30.0,
) -> Dict[str, Any]:
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": int(max_tokens),
        "temperature": float(temperature),
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(endpoint, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        body = resp.read().decode("utf-8", errors="ignore")
    parsed = json.loads(body) if body.strip() else {}
    return parsed if isinstance(parsed, dict) else {"raw": parsed}


def extract_answer(raw: Dict[str, Any]) -> str:
    choices = raw.get("choices", []) if isinstance(raw, dict) else []
    if isinstance(choices, list) and choices:
        msg = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
        text = msg.get("content")
        if isinstance(text, str):
            return text.strip()
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Ask Grok through GitHub Models.")
    parser.add_argument("--prompt", default="", help="User troubleshooting prompt.")
    parser.add_argument("--prompt-file", default="", help="Path to prompt text file.")
    parser.add_argument("--context-file", default="", help="Optional path to context/log text.")
    parser.add_argument("--output", default="", help="Optional output json path.")
    parser.add_argument("--mode", choices=["github", "xai"], default="github")
    parser.add_argument("--model", default=os.environ.get("GROK_GITHUB_MODEL", DEFAULT_MODEL))
    parser.add_argument("--endpoint", default=os.environ.get("GROK_GITHUB_ENDPOINT", DEFAULT_ENDPOINT))
    parser.add_argument("--max-tokens", type=int, default=900)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--timeout-s", type=float, default=30.0)
    parser.add_argument("--env-file", default=".env.txt", help="Optional env file for API keys.")
    args = parser.parse_args()

    loaded = load_env_file(pathlib.Path(args.env_file)) if args.env_file else {}

    model = args.model
    endpoint = args.endpoint
    auth = ""
    if args.mode == "xai":
        if args.model == DEFAULT_MODEL:
            model = os.environ.get("GROK_XAI_MODEL", XAI_DEFAULT_MODEL)
        if args.endpoint == DEFAULT_ENDPOINT:
            endpoint = os.environ.get("GROK_XAI_ENDPOINT", XAI_DEFAULT_ENDPOINT)
        auth = (
            os.environ.get("XAI_API_KEY", "").strip()
            or loaded.get("XAI_API_KEY", "").strip()
            or loaded.get("GROK_API_KEY", "").strip()
        )
        if not auth:
            print("error: XAI_API_KEY is not set", file=sys.stderr)
            return 2
    else:
        auth = os.environ.get("GITHUB_TOKEN", "").strip() or loaded.get("GITHUB_TOKEN", "").strip()
        if not auth:
            print("error: GITHUB_TOKEN is not set", file=sys.stderr)
            return 2

    prompt_text = args.prompt.strip()
    if args.prompt_file:
        prompt_text = read_text(pathlib.Path(args.prompt_file)).strip()
    if not prompt_text:
        print("error: prompt is empty", file=sys.stderr)
        return 2

    context_text = read_text(pathlib.Path(args.context_file)) if args.context_file else ""
    system_prompt = (
        "You are an expert OST automation troubleshooter. "
        "Return concise root-cause analysis and concrete next actions."
    )
    messages = build_messages(system_prompt=system_prompt, user_prompt=prompt_text, context=context_text)

    started = time.time()
    try:
        if args.mode == "xai":
            raw = call_xai_openai_compat(
                api_key=auth,
                endpoint=endpoint,
                model=model,
                messages=messages,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
                timeout_s=args.timeout_s,
            )
        else:
            raw = call_github_models(
                token=auth,
                endpoint=endpoint,
                model=model,
                messages=messages,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
                timeout_s=args.timeout_s,
            )
    except urllib.error.HTTPError as exc:
        print(f"error: http {exc.code} {exc.reason}", file=sys.stderr)
        return 3
    except urllib.error.URLError as exc:
        print(f"error: url {exc.reason}", file=sys.stderr)
        return 3
    except Exception as exc:  # pragma: no cover
        print(f"error: {exc}", file=sys.stderr)
        return 3

    answer = extract_answer(raw)
    elapsed_ms = int((time.time() - started) * 1000)
    payload = {
        "ok": bool(answer),
        "mode": args.mode,
        "model": model,
        "endpoint": endpoint,
        "elapsed_ms": elapsed_ms,
        "answer": answer,
        "raw": raw,
    }

    if args.output:
        save_json(pathlib.Path(args.output), payload)
    print(json.dumps(payload, indent=2))
    return 0 if payload["ok"] else 4


if __name__ == "__main__":
    raise SystemExit(main())

