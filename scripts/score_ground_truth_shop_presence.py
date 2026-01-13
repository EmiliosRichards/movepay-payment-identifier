from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description="Score model_shop_presence vs gt_shop_presence in a ground-truth worksheet CSV.")
    ap.add_argument("--gt-csv", required=True, help="Ground truth worksheet (with gt_shop_presence filled)")
    ap.add_argument(
        "--pred-column",
        default="model_shop_presence",
        help="Prediction column to score (default: model_shop_presence)",
    )
    args = ap.parse_args()

    p = Path(args.gt_csv)
    rows = list(csv.DictReader(p.open("r", encoding="utf-8", newline="")))
    if not rows:
        print("No rows.")
        return 0

    total = 0
    correct = 0
    mat = defaultdict(lambda: defaultdict(int))
    labels = set()

    for r in rows:
        gt = (r.get("gt_shop_presence") or "").strip().lower()
        pred = (r.get(args.pred_column) or "").strip().lower()
        if not gt:
            continue
        total += 1
        if pred == gt:
            correct += 1
        mat[gt][pred] += 1
        labels.add(gt)
        labels.add(pred)

    labels = sorted(labels)
    print(f"rows_scored: {total}")
    if total:
        print(f"accuracy: {correct}/{total} ({(100.0*correct/total):.1f}%)")

    header = "GT \\ Pred".ljust(14) + "".join(l.rjust(10) for l in labels)
    print(header)
    for gt in labels:
        row = gt.ljust(14)
        for pr in labels:
            row += str(mat[gt][pr]).rjust(10)
        print(row)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())



