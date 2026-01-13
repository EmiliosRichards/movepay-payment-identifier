from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse


def _norm(u: str) -> str:
    s = (u or "").strip()
    if not s:
        return ""
    if "\t" in s:
        s = s.split("\t", 1)[0].strip()
    else:
        s = s.split(" ", 1)[0].strip()
    if s.lower().startswith(("http://", "https://")):
        try:
            p = urlparse(s)
            s = (p.netloc or "") + (p.path or "")
        except Exception:
            pass
    return s.strip().rstrip("/").lower()


def main() -> int:
    ap = argparse.ArgumentParser(description="Score shop_presence from a run CSV against gt_shop_presence in a GT CSV.")
    ap.add_argument("--run-csv", required=True, help="outputs/<run>.csv (has shop_presence)")
    ap.add_argument("--gt-csv", required=True, help="ground_truth/<gt>.csv (has gt_shop_presence)")
    args = ap.parse_args()

    gt_rows = list(csv.DictReader(Path(args.gt_csv).open("r", encoding="utf-8", newline="")))
    gt = {}
    for r in gt_rows:
        k = _norm(r.get("website") or "")
        if not k:
            continue
        gt_val = (r.get("gt_shop_presence") or "").strip().lower()
        if gt_val:
            gt[k] = gt_val

    run_rows = list(csv.DictReader(Path(args.run_csv).open("r", encoding="utf-8", newline="")))
    total = 0
    correct = 0
    missing = 0
    mat = defaultdict(lambda: defaultdict(int))
    labels = set()

    for r in run_rows:
        website = (r.get("website") or r.get("input_url") or "").strip()
        k = _norm(website)
        if not k or k not in gt:
            missing += 1
            continue
        pred = (r.get("shop_presence") or "").strip().lower()
        truth = gt[k]
        if not pred:
            pred = "unknown"
        total += 1
        if pred == truth:
            correct += 1
        mat[truth][pred] += 1
        labels.add(truth)
        labels.add(pred)

    labels = sorted(labels)
    print(f"matched_rows: {total}")
    print(f"missing_gt: {missing}")
    if total:
        print(f"shop_presence_accuracy: {correct}/{total} ({(100.0*correct/total):.1f}%)")
    print("GT \\ Pred".ljust(14) + "".join(l.rjust(10) for l in labels))
    for gt_label in labels:
        row = gt_label.ljust(14)
        for pr in labels:
            row += str(mat[gt_label][pr]).rjust(10)
        print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

