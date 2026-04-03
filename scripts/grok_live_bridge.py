#!/usr/bin/env python3
"""
Interactive Grok bridge for live conversation during training updates.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import time
import urllib.error
from typing import Any, Dict, List

from grok_github_connector import (
    DEFAULT_ENDPOINT,
    DEFAULT_MODEL,
    XAI_DEFAULT_ENDPOINT,
    XAI_DEFAULT_MODEL,
    call_github_models,
    call_xai_openai_compat,
    extract_answer,
    load_env_file,
)


def _append_jsonl(path: pathlib.Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Live Grok chat bridge.")
    parser.add_argument("--mode", choices=["xai", "github"], default="xai")
    parser.add_argument("--env-file", default=".env.txt")
    parser.add_argument("--model", default="")
    parser.add_argument("--endpoint", default="")
    parser.add_argument("--timeout-s", type=float, default=35.0)
    parser.add_argument("--session-file", default="output/grok_bridge/session_latest.jsonl")
    parser.add_argument("--system", default="You are a precise technical assistant helping with OST automation.")
    args = parser.parse_args()

    loaded = load_env_file(pathlib.Path(args.env_file)) if args.env_file else {}

    mode = args.mode
    if mode == "xai":
        auth = loaded.get("XAI_API_KEY", "").strip() or loaded.get("GROK_API_KEY", "").strip()
        if not auth:
            print("error: missing XAI_API_KEY/GROK_API_KEY in env file")
            return 2
        endpoint = args.endpoint.strip() or XAI_DEFAULT_ENDPOINT
        model = args.model.strip() or loaded.get("GROK_MODEL", "").strip() or XAI_DEFAULT_MODEL
    else:
        auth = loaded.get("GITHUB_TOKEN", "").strip()
        if not auth:
            print("error: missing GITHUB_TOKEN in env file")
            return 2
        endpoint = args.endpoint.strip() or DEFAULT_ENDPOINT
        model = args.model.strip() or DEFAULT_MODEL

    session_path = pathlib.Path(args.session_file)
    messages: List[Dict[str, str]] = [{"role": "system", "content": args.system}]
    print(f"live_bridge_ready mode={mode} model={model}")
    print("type '/exit' to stop")

    while True:
        user_text = input("\nYou> ").strip()
        if not user_text:
            continue
        if user_text.lower() in {"/exit", "exit", "quit"}:
            print("bridge_stopped")
            break

        messages.append({"role": "user", "content": user_text})
        started = time.time()
        try:
            if mode == "xai":
                raw = call_xai_openai_compat(
                    api_key=auth,
                    endpoint=endpoint,
                    model=model,
                    messages=messages,
                    timeout_s=args.timeout_s,
                )
            else:
                raw = call_github_models(
                    token=auth,
                    endpoint=endpoint,
                    model=model,
                    messages=messages,
                    timeout_s=args.timeout_s,
                )
            answer = extract_answer(raw) or "(empty response)"
            elapsed_ms = int((time.time() - started) * 1000)
            print(f"\nGrok> {answer}")
            messages.append({"role": "assistant", "content": answer})
            _append_jsonl(
                session_path,
                {
                    "ts": int(time.time()),
                    "mode": mode,
                    "model": model,
                    "elapsed_ms": elapsed_ms,
                    "user": user_text,
                    "assistant": answer,
                },
            )
        except urllib.error.HTTPError as exc:
            print(f"\nerror: http {exc.code} {exc.reason}")
        except urllib.error.URLError as exc:
            print(f"\nerror: url {exc.reason}")
        except Exception as exc:  # pragma: no cover
            print(f"\nerror: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

