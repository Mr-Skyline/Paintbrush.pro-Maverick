from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

import requests


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test CV + app flow")
    parser.add_argument("--api", default="http://localhost:8000", help="CV API base URL")
    parser.add_argument("--project-id", default="kirksey-demo")
    parser.add_argument("--file", required=True, help="Path to blueprint image or PDF")
    args = parser.parse_args()

    fp = Path(args.file)
    if not fp.exists():
        raise SystemExit(f"File not found: {fp}")

    raw = fp.read_bytes()
    b64 = base64.b64encode(raw).decode("utf-8")
    mime = "application/pdf" if fp.suffix.lower() == ".pdf" else "image/png"
    payload = {
        "project_id": args.project_id,
        "source_name": fp.name,
        "mime_type": mime,
        "file_base64": b64,
    }
    res = requests.post(f"{args.api.rstrip('/')}/api/v1/takeoff/process", json=payload, timeout=120)
    res.raise_for_status()
    data = res.json()
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
