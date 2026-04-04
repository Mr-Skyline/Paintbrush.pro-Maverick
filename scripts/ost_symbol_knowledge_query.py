#!/usr/bin/env python3
"""
Query local symbol knowledge index with one image.
"""

from __future__ import annotations

import argparse
import pathlib
from typing import Any, Dict, List

from ost_symbol_knowledge import compute_symbol_embedding, cosine_similarity, read_json


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Query symbol class from local index")
    p.add_argument("--image", required=True, help="Path to input image")
    p.add_argument("--index-json", required=True, help="Path to symbol index json")
    p.add_argument("--top-k", type=int, default=5, help="Top K classes")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    image_path = pathlib.Path(args.image).expanduser().resolve()
    index_path = pathlib.Path(args.index_json).expanduser().resolve()
    if not image_path.exists():
        print("ERROR: query_image_not_found")
        return 2
    if not index_path.exists():
        print("ERROR: index_json_not_found")
        return 3

    query = compute_symbol_embedding(image_path)
    if not query.get("ok"):
        print("ERROR: query_embedding_failed")
        return 4
    q = query.get("embedding", [])

    idx = read_json(index_path, {})
    protos = idx.get("prototypes", {}) if isinstance(idx, dict) else {}
    ranked: List[Dict[str, Any]] = []
    for cls, row in protos.items():
        if not isinstance(row, dict):
            continue
        proto = row.get("prototype_embedding", [])
        if not isinstance(proto, list):
            continue
        sim = cosine_similarity([float(x) for x in q], [float(x) for x in proto])
        ranked.append(
            {
                "symbol_class": str(cls),
                "similarity": round(float(sim), 6),
                "support_count": int(row.get("count", 0) or 0),
                "example_paths": [str(x) for x in (row.get("example_paths", []) or [])[:3]],
            }
        )
    ranked.sort(key=lambda r: float(r.get("similarity", 0.0)), reverse=True)
    ranked = ranked[: max(1, int(args.top_k))]

    print(
        {
            "ok": True,
            "query_image": str(image_path),
            "index_json": str(index_path),
            "top_matches": ranked,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

