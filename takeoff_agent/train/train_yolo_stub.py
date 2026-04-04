from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="YOLO training stub for blueprint detection")
    parser.add_argument("--data", required=True, help="Path to dataset yaml")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--imgsz", type=int, default=1024)
    parser.add_argument("--model", default="yolo11n.pt")
    args = parser.parse_args()

    data_path = Path(args.data)
    if not data_path.exists():
        raise SystemExit(f"Dataset config not found: {data_path}")

    try:
        from ultralytics import YOLO
    except Exception as exc:
        raise SystemExit(
            "ultralytics is required. Install dependencies from requirements.txt"
        ) from exc

    model = YOLO(args.model)
    model.train(data=str(data_path), epochs=args.epochs, imgsz=args.imgsz)


if __name__ == "__main__":
    main()
